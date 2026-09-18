"""Authentication and credential management subcommands for thingsboard_admin."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.tools.commands.base import BaseCommand
from app.tools.thingsboard_client import ThingsboardClient, ThingsboardConfig

logger = logging.getLogger("tb_admin.auth")

DEFAULT_SYSADMIN_EMAIL = "sysadmin@thingsboard.org"
DEFAULT_SYSADMIN_PASSWORD = "sysadmin"
ACCESS_TOKEN = "ACCESS_TOKEN"
TOKEN_MAP_MODE = 0o600


def _tenant_admin_token(client: ThingsboardClient, tenant_id: str) -> Optional[str]:
    """Borrow a tenant admin's token; device APIs are not visible to sysadmin."""
    response = client._request("GET", f"/api/tenant/{tenant_id}/users?pageSize=100&page=0")
    if response.status_code not in (200, 201):
        logger.warning("Could not list users for tenant %s: %s", tenant_id, response.status_code)
        return None

    for user in response.json().get("data", []):
        if user.get("authority") != "TENANT_ADMIN":
            continue
        user_id = user.get("id", {}).get("id")
        token_response = client._request("GET", f"/api/user/{user_id}/token")
        if token_response.status_code in (200, 201):
            return token_response.json().get("token")
        logger.warning("Impersonation of %s failed: %s", user.get("email"), token_response.status_code)
    return None


def _collect_devices(client: ThingsboardClient) -> dict[str, dict]:
    """Walk every tenant and return the bridge's `devices` map, live from TB."""
    devices: dict[str, dict] = {}
    for tenant in client.list_tenants():
        tenant_id = tenant.get("id", {}).get("id")
        tenant_name = tenant.get("name", "<unnamed>")

        token = _tenant_admin_token(client, tenant_id)
        if not token:
            logger.warning("Skipping tenant %s: no usable tenant-admin token", tenant_name)
            continue

        with client.impersonate(token):
            for device in client.list_devices():
                name = device.get("name", "")
                parts = name.split(".")
                if len(parts) != 3:
                    logger.warning("Skipping device %r: name is not <customer>.<site>.<turbine>", name)
                    continue

                device_id = device.get("id", {}).get("id")
                credentials = client.get_device_credentials(device_id) or {}
                if credentials.get("credentialsType") != ACCESS_TOKEN:
                    logger.warning("Skipping device %r: credentials are %s, not %s", name, credentials.get("credentialsType"), ACCESS_TOKEN)
                    continue

                customer_id, site_id, turbine_id = parts
                devices[f"{customer_id}/{site_id}/{turbine_id}"] = {
                    "customer_id": customer_id,
                    "site_id": site_id,
                    "turbine_id": turbine_id,
                    "device_name": name,
                    "token": credentials.get("credentialsId"),
                }
    return devices


def _write_token_map(path: Path, devices: dict[str, dict]) -> None:
    document = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "thingsboard",
        "devices": devices,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".json.tmp")
    staging.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.chmod(staging, TOKEN_MAP_MODE)
    staging.replace(path)


def _refresh_provisioning_snapshots(devices: dict[str, dict], results_dir: Path) -> list[Path]:
    by_turbine = {entry["turbine_id"]: entry["token"] for entry in devices.values()}
    refreshed: list[Path] = []
    for snapshot in sorted(results_dir.glob("provisioning-*.json")):
        try:
            document = json.loads(snapshot.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tokens = document.get("tokens")
        if not isinstance(tokens, dict):
            continue
        updated = {name: by_turbine.get(name, token) for name, token in tokens.items()}
        if updated == tokens:
            continue
        document["tokens"] = updated
        document["tokens_refreshed_at"] = datetime.now(timezone.utc).isoformat()
        snapshot.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        refreshed.append(snapshot)
    return refreshed


class AuthCommand(BaseCommand):
    """Authentication and security administration command."""

    @classmethod
    def run_secure_admin(cls, args: argparse.Namespace) -> int:
        """Rotates ThingsBoard sysadmin password away from vendor default."""
        cfg, _ = cls.init_tb_client(args)
        target_email = cfg.sysadmin_email or DEFAULT_SYSADMIN_EMAIL
        target_password = cfg.sysadmin_password or ""

        if not target_password or target_password == DEFAULT_SYSADMIN_PASSWORD:
            logger.error("TB_SYSADMIN_PASSWORD is unset or still the default -- set a real password in .env.")
            return 1

        _, client = cls.init_tb_client(args, admin_email=target_email, admin_password=target_password)

        if client.login_as_user(target_email, target_password):
            logger.info("✓ Sysadmin password already rotated")
            return 0

        token = client.login_as_user(DEFAULT_SYSADMIN_EMAIL, DEFAULT_SYSADMIN_PASSWORD)
        if not token:
            logger.error("❌ Neither the target password nor the vendor default worked -- can't rotate.")
            return 1

        with client.impersonate(token):
            if client.change_password(DEFAULT_SYSADMIN_PASSWORD, target_password):
                logger.info("✓ Sysadmin password rotated")
                return 0

        logger.error("❌ Password change request failed")
        return 1

    @classmethod
    def run_export_tokens(cls, args: argparse.Namespace) -> int:
        """Exports ThingsBoard device access tokens for the Kafka-MQTT bridge."""
        cfg, _ = cls.init_tb_client(args)
        if not cfg.sysadmin_password:
            logger.error("TB_SYSADMIN_PASSWORD is not set; refusing to run.")
            return 1

        _, client = cls.init_tb_client(
            args,
            admin_email=cfg.sysadmin_email,
            admin_password=cfg.sysadmin_password,
        )
        if not client.authenticate():
            logger.error("ThingsBoard authentication failed; check TB_SYSADMIN_* in .env")
            return 1

        devices = _collect_devices(client)
        if not devices:
            logger.error("No access-token devices found; refusing to write an empty map")
            return 1

        repo_root = Path(__file__).resolve().parents[3]
        override = os.getenv("TB_DEVICE_TOKEN_MAP")
        path = Path(override) if override else (repo_root / "provisioning" / "results" / "device-tokens.json")

        if getattr(args, "check", False):
            try:
                existing = json.loads(path.read_text(encoding="utf-8")).get("devices", {})
            except (OSError, json.JSONDecodeError):
                logger.error("No readable token map at %s", path)
                return 1
            drifted = [k for k, entry in devices.items() if existing.get(k, {}).get("token") != entry["token"]]
            if drifted or set(existing) != set(devices):
                logger.error("Token map at %s is stale: %s", path, drifted or "device set differs")
                return 1
            logger.info("Token map at %s matches ThingsBoard (%d device(s))", path, len(devices))
            return 0

        _write_token_map(path, devices)
        logger.info("Wrote %d device token(s) to %s", len(devices), path)
        for snapshot in _refresh_provisioning_snapshots(devices, path.parent):
            logger.info("Refreshed stale tokens in %s", snapshot.name)
        return 0


run_secure_admin = AuthCommand.run_secure_admin
run_export_tokens = AuthCommand.run_export_tokens


def register_auth_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("auth", help="Authentication and security management")
    auth_subs = parser.add_subparsers(dest="auth_command", required=True)

    secure_p = auth_subs.add_parser("secure", help="Rotate vendor default sysadmin password")
    secure_p.set_defaults(handler=AuthCommand.run_secure_admin)

    export_p = auth_subs.add_parser("export-tokens", help="Export device access tokens")
    export_p.add_argument("--check", action="store_true", help="Check for drift against existing token map")
    export_p.set_defaults(handler=AuthCommand.run_export_tokens)
