"""Configuration and 4-tier credential resolution for ThingsBoard."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class ThingsboardConfig:
    """Configuration for Thingsboard connection and credentials."""

    host: str = "thingsboard"
    port: int = 8080
    tenant_name: str = "zephyr-energy"
    tenant_email: str = "zephyr-energy_admin@example.com"
    tenant_password: Optional[str] = None
    sysadmin_email: str = "sysadmin@thingsboard.org"
    sysadmin_password: Optional[str] = None
    timeout_s: float = 30.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _find_snapshot_password(results_dir: Path) -> Optional[str]:
    """Inspect latest provisioning results JSON for tenant password if present."""
    if not results_dir.exists():
        return None
    snapshots = sorted(results_dir.glob("provisioning-*.json"), reverse=True)
    for snapshot in snapshots:
        try:
            data = json.loads(snapshot.read_text(encoding="utf-8"))
            pwd = data.get("tenant_password") or data.get("admin_password")
            if pwd:
                return str(pwd)
        except (OSError, json.JSONDecodeError):
            continue
    return None


def resolve_config(
    cli_args: Optional[Any] = None,
    repo_root: Optional[Path] = None,
) -> ThingsboardConfig:
    """4-tier precedence resolution:

    1. CLI flag (if provided on cli_args)
    2. Environment variable
    3. provisioning-results JSON file
    4. Default value
    """
    root = repo_root or Path(__file__).resolve().parents[3]
    results_dir = root / "provisioning" / "results"

    # 1. Host & Port
    host = getattr(cli_args, "tb_host", None) or os.getenv("TB_HOST") or "thingsboard"
    port_val = getattr(cli_args, "tb_port", None) or os.getenv("TB_PORT") or 8080
    port = int(port_val)

    # 2. Tenant name & email
    tenant_name = (
        getattr(cli_args, "tenant_name", None)
        or os.getenv("TENANT_NAME")
        or "zephyr-energy"
    )
    tenant_email = (
        getattr(cli_args, "tenant_email", None)
        or os.getenv("TENANT_EMAIL")
        or os.getenv("TB_TENANT_ADMIN_EMAIL")
        or "zephyr-energy_admin@example.com"
    )

    # 3. Tenant password
    tenant_password = (
        getattr(cli_args, "tenant_password", None)
        or os.getenv("TB_TENANT_ADMIN_PASSWORD")
        or os.getenv("TB_ADMIN_PASSWORD")
        or _find_snapshot_password(results_dir)
    )

    # 4. Sysadmin credentials
    sysadmin_email = (
        getattr(cli_args, "sysadmin_email", None)
        or getattr(cli_args, "tb_sysadmin_email", None)
        or os.getenv("TB_SYSADMIN_EMAIL")
        or "sysadmin@thingsboard.org"
    )
    sysadmin_password = (
        getattr(cli_args, "sysadmin_password", None)
        or getattr(cli_args, "tb_sysadmin_password", None)
        or os.getenv("TB_SYSADMIN_PASSWORD")
    )

    timeout_s = float(getattr(cli_args, "timeout_s", 30.0) or 30.0)

    return ThingsboardConfig(
        host=host,
        port=port,
        tenant_name=tenant_name,
        tenant_email=tenant_email,
        tenant_password=tenant_password,
        sysadmin_email=sysadmin_email,
        sysadmin_password=sysadmin_password,
        timeout_s=timeout_s,
    )
