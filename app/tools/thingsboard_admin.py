#!/usr/bin/env python3
"""Canonical CLI administration tool for Wind Turbine Digital Twin in ThingsBoard."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

# Ensure repository root is on sys.path
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
    """Build the canonical argument parser with all global options and subcommands."""
    parser = argparse.ArgumentParser(
        prog="thingsboard_admin.py",
        description="Canonical CLI tool for Wind Turbine Digital Twin ThingsBoard administration.",
    )

    # Global options
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

    # Register each domain's subparsers
    register_auth_parser(subparsers)
    register_entity_parser(subparsers)
    register_widget_parser(subparsers)
    register_rulechain_parser(subparsers)
    register_metadata_parser(subparsers)
    register_health_parser(subparsers)
    register_dashboard_parser(subparsers)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
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
