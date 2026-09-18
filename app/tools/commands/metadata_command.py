"""Metadata synchronization subcommands for thingsboard_admin."""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any

from app.tools.commands.base import BaseCommand
from app.tools.subsystem_registry import (
    SUBSYSTEMS,
    Subsystem,
    resolve_limits,
    score_subsystem,
)

logger = logging.getLogger("tb_admin.metadata")

MANAGED_KEYS = (
    "meshId",
    "primarySensors",
    "position3D",
    "position2D",
    "orientation",
    "displayTier",
    "limitSensor",
    "limitSource",
    "warningLimit",
    "alarmLimit",
    "criticalLimit",
)


def _build_attributes(sub: Subsystem, shared_thresholds: dict[str, float]) -> dict[str, Any]:
    limits = resolve_limits(sub, shared_thresholds)
    attrs: dict[str, Any] = {
        "meshId": sub.mesh_id,
        "primarySensors": sub.primary_sensors,
        "position3D": sub.position_3d,
        "position2D": sub.position_2d,
        "orientation": sub.orientation,
        "displayTier": sub.display_tier,
    }
    if limits:
        attrs["limitSensor"] = limits.sensor_key
        attrs["limitSource"] = limits.source
        if limits.warning is not None:
            attrs["warningLimit"] = limits.warning
        if limits.alarm is not None:
            attrs["alarmLimit"] = limits.alarm
        if limits.critical is not None:
            attrs["criticalLimit"] = limits.critical
    return attrs


class MetadataCommand(BaseCommand):
    """Metadata synchronization command."""

    @classmethod
    def run_sync_metadata(cls, args: argparse.Namespace) -> int:
        """Synchronizes 2D SVG coords, 3D GLB tags, and threshold limits onto subsystem assets."""
        cfg, session, http = cls.init_session(args, require_password=True, is_sysadmin=False)
        if not http:
            return 1

        turbine_device_id = getattr(args, "device_id", None) or os.getenv("TB_DEVICE_ID", "f82c5c10-afee-11f1-b871-bd111a5de747")
        shared_thresholds: dict[str, float] = {}
        try:
            items = http.get(f"/api/plugins/telemetry/DEVICE/{turbine_device_id}/values/attributes/SHARED_SCOPE")
            if isinstance(items, list):
                for it in items:
                    k = it.get("key", "")
                    if k.startswith("threshold_"):
                        try:
                            shared_thresholds[k] = float(it.get("value"))
                        except (ValueError, TypeError):
                            pass
        except Exception as e:
            logger.warning("Could not fetch shared thresholds for device %s: %s", turbine_device_id, e)

        dry_run = getattr(args, "dry_run", False)
        verify_only = getattr(args, "verify_only", False)
        synced = 0

        for sub in SUBSYSTEMS:
            attrs = _build_attributes(sub, shared_thresholds)
            if verify_only or dry_run:
                logger.info("[DRY-RUN] Would sync %s (%s): %d attributes", sub.name, sub.asset_id, len(attrs))
                continue

            try:
                http.post(f"/api/plugins/telemetry/ASSET/{sub.asset_id}/SERVER_SCOPE", data=attrs)
                synced += 1
                logger.info("✓ Synced metadata for %s (%s)", sub.name, sub.asset_id)
            except Exception as e:
                logger.warning("Failed to sync metadata for %s: %s", sub.name, e)

        logger.info("Metadata sync complete: %d / %d subsystems updated", synced, len(SUBSYSTEMS))
        return 0


run_sync_metadata = MetadataCommand.run_sync_metadata


def register_metadata_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("metadata", help="Digital twin metadata management")
    meta_subs = parser.add_subparsers(dest="metadata_command", required=True)

    sync_p = meta_subs.add_parser("sync", help="Sync 2D/3D metadata and limits to subsystem assets")
    sync_p.add_argument("--device-id", default=None, help="Device ID to read thresholds from")
    sync_p.add_argument("--dry-run", action="store_true", help="Print changes without applying")
    sync_p.add_argument("--verify-only", action="store_true", help="Only verify existing metadata")
    sync_p.set_defaults(handler=MetadataCommand.run_sync_metadata)
