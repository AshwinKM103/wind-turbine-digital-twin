"""Entity provisioning subcommands for thingsboard_admin."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from app.tools.commands.base import BaseCommand
from app.tools.subsystem_registry import STEAM_TURBINE_RIG_ASSET_ID, SUBSYSTEMS
from app.tools.thingsboard_client import ThingsboardClient, ThingsboardConfig

logger = logging.getLogger("tb_admin.entity")


def _get_or_create_asset(
    client: ThingsboardClient, name: str, asset_type: str, asset_id: Optional[str] = None
) -> Optional[str]:
    resp = client._request("GET", f"/api/tenant/assets?pageSize=100&page=0&type={asset_type}")
    if resp.status_code == 200:
        data = resp.json().get("data", [])
        for item in data:
            if item.get("name") == name:
                existing_id = item.get("id", {}).get("id")
                logger.info("✓ Asset '%s' already exists (ID: %s)", name, existing_id)
                return existing_id

    payload: dict[str, Any] = {"name": name, "type": asset_type, "label": name}
    if asset_id:
        payload["id"] = {"id": asset_id, "entityType": "ASSET"}

    create_resp = client._request("POST", "/api/asset", json=payload)
    if create_resp.status_code in (200, 201):
        created_id = create_resp.json().get("id", {}).get("id")
        logger.info("✓ Asset '%s' created (ID: %s)", name, created_id)
        return created_id
    elif create_resp.status_code in (400, 409) and asset_id:
        payload.pop("id", None)
        retry_resp = client._request("POST", "/api/asset", json=payload)
        if retry_resp.status_code in (200, 201):
            created_id = retry_resp.json().get("id", {}).get("id")
            logger.info("✓ Asset '%s' created with generated ID (ID: %s)", name, created_id)
            return created_id

    logger.warning("Failed to create asset '%s': HTTP %s (%s)", name, create_resp.status_code, create_resp.text)
    return None


def _create_relation(
    client: ThingsboardClient,
    from_id: str,
    from_type: str,
    to_id: str,
    to_type: str,
    relation_type: str = "Contains",
) -> bool:
    payload = {
        "from": {"id": from_id, "entityType": from_type},
        "to": {"id": to_id, "entityType": to_type},
        "type": relation_type,
        "typeGroup": "COMMON",
    }
    resp = client._request("POST", "/api/relation", json=payload)
    return resp.status_code in (200, 201)


class EntityCommand(BaseCommand):
    """Entity provisioning command."""

    @classmethod
    def run_provision_entities(cls, args: argparse.Namespace) -> int:
        """Idempotently provisions Tenant, Tenant Admin, Device, and 14 Assets."""
        cfg, _ = cls.init_tb_client(args)
        if not cfg.sysadmin_password:
            logger.error("TB_SYSADMIN_PASSWORD is required.")
            return 1
        if not cfg.tenant_password:
            logger.error("TB_TENANT_ADMIN_PASSWORD is required.")
            return 1

        _, client = cls.init_tb_client(
            args,
            admin_email=cfg.sysadmin_email,
            admin_password=cfg.sysadmin_password,
        )
        if not client.authenticate():
            logger.error("Sysadmin authentication failed against %s:%s", cfg.host, cfg.port)
            return 1

        logger.info("Connected to ThingsBoard as sysadmin.")

        tenant_ok, tenant_id = client.create_tenant(cfg.tenant_name)
        if not (tenant_ok and tenant_id):
            logger.error("Failed to create/locate tenant '%s'", cfg.tenant_name)
            return 1
        logger.info("Tenant '%s' verified (ID: %s)", cfg.tenant_name, tenant_id)

        user_ok, user_id, temp_pwd = client.create_user(
            tenant_id=tenant_id,
            email=cfg.tenant_email,
            authority="TENANT_ADMIN",
            first_name="Admin",
            last_name=cfg.tenant_name,
        )

        tenant_jwt = client.login_as_user(cfg.tenant_email, cfg.tenant_password)
        if tenant_jwt:
            logger.info("✓ Tenant admin '%s' authenticated with configured password.", cfg.tenant_email)
        elif user_id:
            client.activate_user(user_id, cfg.tenant_password)
            tenant_jwt = client.login_as_user(cfg.tenant_email, cfg.tenant_password)
            if not tenant_jwt and temp_pwd:
                tenant_jwt = client.login_as_user(cfg.tenant_email, temp_pwd)

        if not tenant_jwt and user_id:
            logger.warning("Could not login directly as tenant admin; attempting token impersonation...")
            resp = client._request("GET", f"/api/user/{user_id}/token")
            if resp.status_code in (200, 201):
                tenant_jwt = resp.json().get("token")

        if not tenant_jwt:
            logger.error("Failed to acquire authentication token for tenant admin '%s'", cfg.tenant_email)
            return 1

        created_devices = {}
        created_assets = {}
        site_id = getattr(args, "site_id", None) or os.getenv("SITE_ID", "cascade-ridge")
        turbines_str = getattr(args, "turbine_ids", None) or os.getenv("TURBINE_IDS", "boreas")
        turbines = [t.strip() for t in turbines_str.split(",") if t.strip()]

        with client.impersonate(tenant_jwt):
            for turb in turbines:
                device_name = f"{cfg.tenant_name}.{site_id}.{turb}"
                dev = client.find_device_by_name(device_name)
                if dev:
                    dev_id = dev.get("id", {}).get("id")
                    logger.info("✓ Device '%s' already exists (ID: %s)", device_name, dev_id)
                    created_devices[turb] = dev_id
                else:
                    ok, dev_id = client.create_device(
                        device_name,
                        device_type="turbine",
                        label=f"{turb.title()} Turbine",
                        attributes={
                            "site_id": site_id,
                            "turbine_id": turb,
                            "customer_id": cfg.tenant_name,
                        },
                    )
                    if ok and dev_id:
                        logger.info("✓ Device '%s' created (ID: %s)", device_name, dev_id)
                        created_devices[turb] = dev_id

            rig_id = _get_or_create_asset(client, "Steam Turbine Rig Prototype", "turbine_rig", STEAM_TURBINE_RIG_ASSET_ID)
            if rig_id:
                created_assets["root_rig"] = rig_id

            for sub in SUBSYSTEMS:
                sub_id = _get_or_create_asset(client, sub.name, "subsystem", sub.asset_id)
                if sub_id:
                    created_assets[sub.name] = sub_id
                    if rig_id:
                        _create_relation(client, rig_id, "ASSET", sub_id, "ASSET", "Contains")

            if rig_id:
                for turb, dev_id in created_devices.items():
                    _create_relation(client, rig_id, "ASSET", dev_id, "DEVICE", "Monitors")

        repo_root = Path(__file__).resolve().parents[3]
        output_dir = Path(getattr(args, "output_dir", None) or os.getenv("PROVISIONING_OUTPUT", str(repo_root / "provisioning" / "results")))
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "status": "SUCCESS",
            "timestamp": int(time.time()),
            "tenant_name": cfg.tenant_name,
            "tenant_id": tenant_id,
            "tenant_email": cfg.tenant_email,
            "devices": created_devices,
            "assets": created_assets,
        }
        out_file = output_dir / f"provisioning-{cfg.tenant_name}-{int(time.time())}.json"
        out_file.write_text(json.dumps(summary, indent=2) + "\n")
        try:
            out_file.chmod(0o600)
        except OSError:
            pass

        logger.info("✅ Entity provisioning completed successfully.")
        return 0


run_provision_entities = EntityCommand.run_provision_entities


def register_entity_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("entity", help="Entity provisioning management")
    entity_subs = parser.add_subparsers(dest="entity_command", required=True)

    prov_p = entity_subs.add_parser("provision", help="Provision tenant, device, and assets")
    prov_p.add_argument("--site-id", default=None, help="Site identifier")
    prov_p.add_argument("--turbine-ids", default=None, help="Comma-separated turbine IDs")
    prov_p.add_argument("--device-id", default=None, help="Turbine device UUID")
    prov_p.add_argument("--output-dir", default=None, help="Output directory for provisioning snapshots")
    prov_p.set_defaults(handler=EntityCommand.run_provision_entities)
