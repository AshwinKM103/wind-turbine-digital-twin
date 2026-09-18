"""
Base command class providing shared patterns for CLI administration commands.

Encapsulates common command-line argument parsing, session authentication initialization,
ThingsBoard client instantiation, and standardized error handling.

The implementation supports:

    - Standardized connection flag registration across subparsers
    - Authenticated ThingsboardSession and ThingsboardHttpClient creation
    - Legacy and unified ThingsboardClient factory methods

Key classes / functions:

    - BaseCommand: Mixin and base class exposing shared CLI command helpers.

"""

from __future__ import annotations

import argparse
import logging
from typing import Optional, Tuple

from app.tools.thingsboard_client import ThingsboardClient, ThingsboardConfig as TBClientConfig
from app.tools.thingsboard_core.thingsboard_config import ThingsboardConfig, resolve_config
from app.tools.thingsboard_core.http_client import ThingsboardHttpClient, ThingsboardSession

logger = logging.getLogger("tb_admin.base")


class BaseCommand:
    """
    Mixin or base class for thingsboard_admin CLI commands with shared patterns.

    Provides common helper routines for argument parsing, authentication session
    lifecycle management, client bootstrapping, and exception logging.

    """

    @classmethod
    def parse_standard_args(cls, parser: argparse.ArgumentParser) -> None:
        """
        Add standard ThingsBoard connection parameters to an argument parser.

        Args:
            parser (argparse.ArgumentParser): Target argument parser to enrich.

        """
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
        """
        Resolve config and initialize authenticated Thingsboard session and HTTP client.

        Args:
            args (argparse.Namespace): Parsed CLI command arguments.
            require_password (bool, optional): Whether password is strictly required. Defaults to True.
            is_sysadmin (bool, optional): Whether to use sysadmin credentials. Defaults to False.

        Returns:
            Tuple[ThingsboardConfig, Optional[ThingsboardSession], Optional[ThingsboardHttpClient]]:
                Tuple of resolved configuration, active session, and HTTP client.

        """
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
        """
        Resolve configuration and instantiate a ThingsboardClient.

        Args:
            args (argparse.Namespace): Parsed CLI command arguments.
            admin_email (Optional[str], optional): Explicit admin email override. Defaults to None.
            admin_password (Optional[str], optional): Explicit admin password override. Defaults to None.

        Returns:
            Tuple[ThingsboardConfig, ThingsboardClient]: Resolved config and client instance.

        """
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
        """
        Standardized exception reporting and non-zero exit status generation.

        Args:
            exc (Exception): Caught exception instance.
            context (str, optional): Context description. Defaults to "Command execution".

        Returns:
            int: Standard error exit status code (1).

        """
        logger.error("%s failed: %s", context, exc)
        return 1
