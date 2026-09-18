"""Base command class providing shared patterns for CLI commands."""

from __future__ import annotations

import argparse
import logging
from typing import Optional, Tuple

from app.tools.thingsboard_client import ThingsboardClient, ThingsboardConfig as TBClientConfig
from app.tools.thingsboard_core.thingsboard_config import ThingsboardConfig, resolve_config
from app.tools.thingsboard_core.http_client import ThingsboardHttpClient, ThingsboardSession

logger = logging.getLogger("tb_admin.base")


class BaseCommand:
    """Mixin or base class for thingsboard_admin CLI commands with shared patterns."""

    @classmethod
    def parse_standard_args(cls, parser: argparse.ArgumentParser) -> None:
        """Add standard ThingsBoard connection parameters to an argument parser."""
        parser.add_argument("--host", dest="host", help="Thingsboard server host")
        parser.add_argument("--port", dest="port", type=int, help="Thingsboard server port")
        parser.add_argument("--username", dest="username", help="Thingsboard admin/tenant username/email")
        parser.add_argument("--password", dest="password", help="Thingsboard password")

    @classmethod
    def init_session(
        cls,
        args: argparse.Namespace,
        require_password: bool = True,
        is_sysadmin: bool = False,
    ) -> Tuple[ThingsboardConfig, Optional[ThingsboardSession], Optional[ThingsboardHttpClient]]:
        """Resolve config and initialize authenticated Thingsboard session and HTTP client."""
        cfg = resolve_config(args)
        password = cfg.sysadmin_password if is_sysadmin else cfg.tenant_password
        email = cfg.sysadmin_email if is_sysadmin else cfg.tenant_email

        if require_password and not password:
            logger.error("Authentication password is required for this command.")
            return cfg, None, None

        session = ThingsboardSession(cfg.base_url, timeout_s=cfg.timeout_s)
        if password and email:
            session.login(email, password)
        http = ThingsboardHttpClient(session)
        return cfg, session, http

    @classmethod
    def init_tb_client(
        cls,
        args: argparse.Namespace,
        admin_email: Optional[str] = None,
        admin_password: Optional[str] = None,
    ) -> Tuple[ThingsboardConfig, ThingsboardClient]:
        """Resolve config and instantiate ThingsboardClient."""
        cfg = resolve_config(args)
        email = admin_email if admin_email is not None else cfg.tenant_email
        password = admin_password if admin_password is not None else (cfg.tenant_password or "")
        client = ThingsboardClient(
            TBClientConfig(
                host=cfg.host,
                port=cfg.port,
                admin_email=email,
                admin_password=password,
            )
        )
        return cfg, client

    @classmethod
    def handle_error(cls, exc: Exception, context: str = "Command execution") -> int:
        """Standardized exception reporting."""
        logger.error("%s failed: %s", context, exc)
        return 1
