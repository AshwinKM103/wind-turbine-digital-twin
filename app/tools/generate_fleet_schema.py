#!/usr/bin/env python3
"""
IoTDB fleet schema SQL generator.

Generates and renders config/iotdb-schema-fleet.sql from fleet topology defined
in fleet.json, attaching device templates and setting TTL policies per customer.

The implementation supports:

    - Multi-tenant site-level device template binding
    - Idempotent device activation for all configured turbines
    - Retention TTL configuration across customer subtrees

Key classes / functions:

    - render: Generate raw SQL statements from fleet configuration.
    - main: Write rendered SQL to target configuration file.

"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "app" / "src"))

from fleet import load_fleet
from kafka_consumer import quote_path_node

OUTPUT_PATH = REPO_ROOT / "app" / "config" / "iotdb-schema-fleet.sql"
TTL_MS = 30 * 24 * 60 * 60 * 1000


def render() -> str:
    """
    Render SQL commands to bind device templates and set TTLs for the fleet.

    Returns:
        str: Multiline SQL script formatted for IoTDB CLI execution.

    Example:
        >>> sql = render()
        >>> "SET DEVICE TEMPLATE turbine_template" in sql
        True

    """
    fleet = load_fleet()
    lines = [
        "-- " + "=" * 74,
        "-- Wind Turbine Digital Twin - Fleet schema (multi-customer)",
        "-- " + "=" * 74,
        "-- GENERATED from app/config/fleet.json by app/tools/generate_fleet_schema.py",
        "-- Do not edit by hand: edit fleet.json and regenerate.",
        "--",
        "-- Prerequisite: app/config/iotdb-schema.sql has already created the",
        "-- root.digitaltwin database and the turbine_template device template.",
        "-- " + "=" * 74,
        "",
    ]


    for customer in fleet.customers:
        sites = sorted({t.site_id for t in customer.turbines})
        customer_node = quote_path_node(customer.customer_id)
        lines.append(
            f"-- {customer.display_name}: {len(customer.turbines)} turbine(s) "
            f"across {len(sites)} site(s)"
        )
        for site_id in sites:
            # Attaching at the site level means a turbine added later
            # inherits the schema on first write, with no migration.
            lines.append(
                f"SET DEVICE TEMPLATE turbine_template TO "
                f"{fleet.device_path_root}.{customer_node}.{quote_path_node(site_id)};"
            )
        for turbine in customer.turbines:
            device_path = (
                f"{fleet.device_path_root}.{customer_node}."
                f"{quote_path_node(turbine.site_id)}.{quote_path_node(turbine.turbine_id)}"
            )
            lines.append(f"CREATE TIMESERIES USING DEVICE TEMPLATE ON {device_path};")
        lines.append(
            f"SET TTL TO {fleet.device_path_root}.{customer_node} {TTL_MS};"
        )
        lines.append("")

    lines += [
        "-- " + "=" * 74,
        "-- Verification:",
        f"--   SHOW DEVICES {fleet.device_path_root}.**;",
        (
            "--   (expect exactly "
            f"{len(fleet.turbines)} devices, one per turbine in fleet.json)"
        ),
        "-- " + "=" * 74,
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUTPUT_PATH.write_text(render())
    fleet = load_fleet()
    print(f"Wrote schema for {len(fleet.turbines)} turbines to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
