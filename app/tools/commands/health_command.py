"""
Subsystem health score seeding subcommands for ThingsBoard administration.

Populates initial baseline numeric health scores, alert counters, and health status
telemetry attributes across all registered turbine rig and subsystem assets.

The implementation supports:

    - Server-scope attribute and timeseries initialization across asset hierarchy
    - Configurable baseline score seeding (default 100)
    - Status evaluation mapped to score thresholds

Key classes / functions:

    - HealthCommand: CLI command handler for subsystem health score seeding.
    - register_health_parser: Subparser registration entry point.

"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any

from app.tools.commands.base import BaseCommand
from app.tools.subsystem_registry import STEAM_TURBINE_RIG_ASSET_ID, SUBSYSTEMS

logger = logging.getLogger("tb_admin.health")


class HealthCommand(BaseCommand):
    """
    Subsystem health score initialization command.

    Encapsulates routines to seed initial health scores across turbine subsystem assets.

    """

    @classmethod
    def run_seed_health(cls, args: argparse.Namespace) -> int:
        """
        Seed baseline subsystem health scores across asset attributes and timeseries.

        Args:
            args (argparse.Namespace): Parsed CLI command options with baseline score.

        Returns:
            int: 0 on success, non-zero on failure.

        """
        cfg, session, http = cls.init_session(args, require_password=True, is_sysadmin=False)
        if not http:
            return 1

        default_score = float(getattr(args, "score", 100.0) or 100.0)
        now_ms = int(time.time() * 1000)

        rig_payload = {
            "healthScore": default_score,
            "healthStatus": "HEALTHY" if default_score >= 90 else "DEGRADED",
            "activeAlertsCount": 0,
            "lastUpdated": now_ms,
        }
        try:
            http.post(f"/api/plugins/telemetry/ASSET/{STEAM_TURBINE_RIG_ASSET_ID}/SERVER_SCOPE", data=rig_payload)
            http.post(f"/api/plugins/telemetry/ASSET/{STEAM_TURBINE_RIG_ASSET_ID}/timeseries/ANY", data=rig_payload)
            logger.info("✓ Seeded health for Root Rig (%s)", STEAM_TURBINE_RIG_ASSET_ID)
        except Exception as e:
            logger.warning("Failed seeding health for Root Rig: %s", e)

        updated = 0
        for sub in SUBSYSTEMS:
            sub_payload = {
                "healthScore": default_score,
                "healthStatus": "HEALTHY" if default_score >= 90 else "DEGRADED",
                "activeAlertsCount": 0,
                "lastUpdated": now_ms,
            }
            try:
                http.post(f"/api/plugins/telemetry/ASSET/{sub.asset_id}/SERVER_SCOPE", data=sub_payload)
                http.post(f"/api/plugins/telemetry/ASSET/{sub.asset_id}/timeseries/ANY", data=sub_payload)
                updated += 1
                logger.info("✓ Seeded health for %s (%s)", sub.name, sub.asset_id)
            except Exception as e:
                logger.warning("Failed seeding health for %s: %s", sub.name, e)

        logger.info("Health seeding complete: %d / %d assets initialized", updated + 1, len(SUBSYSTEMS) + 1)
        return 0


run_seed_health = HealthCommand.run_seed_health


def register_health_parser(subparsers: argparse._SubParsersAction) -> None:
    """
    Register health seeding subcommands with main CLI parser.

    Args:
        subparsers (argparse._SubParsersAction): Subparser container to populate.

    """
    parser = subparsers.add_parser("health", help="Subsystem health management")
    health_subs = parser.add_subparsers(dest="health_command", required=True)

    seed_p = health_subs.add_parser("seed", help="Seed baseline numeric health scores across assets")
    seed_p.add_argument("--score", type=float, default=100.0, help="Baseline score value (default 100)")
    seed_p.set_defaults(handler=HealthCommand.run_seed_health)
