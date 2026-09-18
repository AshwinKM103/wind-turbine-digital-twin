"""
Canonical CLI administration tool for Wind Turbine Digital Twin in ThingsBoard.

Provides command-line interfaces for managing authentication, device topologies,
custom dashboard widgets, rule chains, device metadata, health checks, and dashboard configurations.

The implementation supports:

    - Domain subcommand registration (auth, entity, widget, rulechain, metadata, health, dashboard)
    - Output formatting in plain text or structured JSON
    - Dynamic credential resolution from environment and CLI flags

Key classes / functions:

    - build_parser: Construct CLI argument parser hierarchy with registered domain subparsers.
    - main: Primary CLI execution dispatching to selected subcommand handler.

"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.tools.commands import (
    register_auth_parser,
    register_dashboard_parser,
    register_entity_parser,
    register_health_parser,
    register_metadata_parser,
    register_rulechain_parser,
    register_widget_parser,
)

logger = logging.getLogger("tb_admin")


def build_parser() -> argparse.ArgumentParser:
    """
    Build the canonical argument parser with global options and domain subcommands.

    Returns:
        argparse.ArgumentParser: Fully configured CLI argument parser.

    """
    parser = argparse.ArgumentParser(
        prog="thingsboard_admin.py",
        description="Canonical CLI tool for Wind Turbine Digital Twin ThingsBoard administration.",
    )

    parser.add_argument("--tb-host", default=None, help="ThingsBoard host (default: $TB_HOST or 'thingsboard')")
    parser.add_argument("--tb-port", type=int, default=None, help="ThingsBoard HTTP port (default: $TB_PORT or 8080)")
    parser.add_argument("--tenant-name", default=None, help="Tenant name (default: $TENANT_NAME or 'zephyr-energy')")
    parser.add_argument("--tenant-email", default=None, help="Tenant admin email")
    parser.add_argument("--tenant-password", default=None, help="Tenant admin password")
    parser.add_argument("--sysadmin-email", default=None, help="Sysadmin email")
    parser.add_argument("--sysadmin-password", default=None, help="Sysadmin password")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress non-error messages")

    subparsers = parser.add_subparsers(dest="command", required=True)

    register_auth_parser(subparsers)
    register_entity_parser(subparsers)
    register_widget_parser(subparsers)
    register_rulechain_parser(subparsers)
    register_metadata_parser(subparsers)
    register_health_parser(subparsers)
    register_dashboard_parser(subparsers)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Parse arguments and execute corresponding administrative subcommand handler.

    Args:
        argv (Optional[Sequence[str]], optional): Command-line argument vector. Defaults to None (sys.argv[1:]).

    Returns:
        int: Process exit code (0 for success, non-zero for error or interruption).

    """
    parser = build_parser()
    args = parser.parse_args(argv)

    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.ERROR

    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    handler = getattr(args, "handler", None)
    if not handler:
        parser.print_help()
        return 2

    try:
        res = handler(args)
        return res if res is not None else 0
    except KeyboardInterrupt:
        logger.warning("Operation interrupted by user.")
        return 130
    except Exception as e:
        logger.error("Operation failed: %s", e, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
