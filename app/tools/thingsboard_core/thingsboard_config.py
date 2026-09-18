"""Configuration and 4-tier credential resolution for ThingsBoard.

Provides typed immutable configuration storage and hierarchical credential resolution
(CLI argument -> Environment Variable -> Provisioning JSON Snapshot -> Built-in Default)
for connecting to ThingsBoard instances as tenant admin or sysadmin.

Exported Classes:
    ThingsboardConfig: Immutable configuration holder for ThingsBoard endpoints and secrets.

Exported Functions:
    resolve_config: Resolves ThingsBoard configuration using 4-tier precedence.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class ThingsboardConfig:
    """Configuration container for ThingsBoard connection endpoints and credentials.

    Attributes:
        host: Hostname or IP address of the ThingsBoard service.
        port: HTTP REST API port.
        tenant_name: Name identifier of the target tenant.
        tenant_email: Email address of the tenant administrator account.
        tenant_password: Optional secret password for tenant admin.
        sysadmin_email: Email address for the root system administrator.
        sysadmin_password: Optional secret password for root system administrator.
        timeout_s: HTTP request timeout in seconds.
    """

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
        """Returns the base URL formatted as 'http://<host>:<port>'."""
        return f"http://{self.host}:{self.port}"


def _find_snapshot_password(results_dir: Path) -> Optional[str]:
    """Inspects the latest provisioning results JSON file for a saved password.

    Args:
        results_dir: Path to directory containing provisioning JSON outputs.

    Returns:
        Discovered password string if present in snapshot, else None.
    """
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
    """Resolves ThingsBoard connection configuration using 4-tier precedence.

    Resolution hierarchy:
        1. CLI argument (attributes on cli_args)
        2. Environment variable
        3. Local provisioning-results snapshot file
        4. Built-in system default

    Args:
        cli_args: Optional argparse Namespace containing command-line overrides.
        repo_root: Optional custom repository root Path for locating provisioning snapshots.

    Returns:
        Frozen ThingsboardConfig populated with highest-priority discovered values.

    Example:
        >>> config = resolve_config()
        >>> print(config.base_url)
        http://thingsboard:8080
    """
    root = repo_root or Path(__file__).resolve().parents[3]
    results_dir = root / "provisioning" / "results"

    host = getattr(cli_args, "tb_host", None) or os.getenv("TB_HOST") or "thingsboard"
    port_val = getattr(cli_args, "tb_port", None) or os.getenv("TB_PORT") or 8080
    port = int(port_val)

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

    tenant_password = (
        getattr(cli_args, "tenant_password", None)
        or os.getenv("TB_TENANT_ADMIN_PASSWORD")
        or os.getenv("TB_ADMIN_PASSWORD")
        or _find_snapshot_password(results_dir)
    )

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

