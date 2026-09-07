#!/usr/bin/env python3
"""
generate_sensor_mappings.py - Render config/sensor_mappings.json.

sensor_mappings.json is consumed by Grafana (panel field overrides that
rename TT_109A -> "Gearbox Bearing Temp A") and by any tooling that needs
sensor units. It is generated rather than hand-maintained so it cannot
drift from sensor_profiles.py, which the simulator uses.

Regenerate after editing sensor_profiles.py:
    python app/tools/generate_sensor_mappings.py

test_sensor_mappings.py fails if the committed file is stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "app" / "src"))

from sensor_profiles import SENSOR_PROFILES

OUTPUT_PATH = REPO_ROOT / "app" / "config" / "sensor_mappings.json"
SCHEMA_VERSION = "1.0"


def build_mappings() -> dict:
    """Assemble the full mappings document from the profile catalog."""
    sensors = {}
    for profile in SENSOR_PROFILES:
        # Normal range spans idle..full-load, widened by the noise band so
        # a healthy machine at either extreme is not flagged by a
        # dashboard threshold on every tick, then clipped to the channel's
        # absolute range -- otherwise a channel that cannot read negative
        # (flow, vibration) would advertise a negative normal minimum.
        low = max(
            profile.min_value,
            min(profile.idle_value, profile.load_value) - 3 * profile.noise_std,
        )
        high = min(
            profile.max_value,
            max(profile.idle_value, profile.load_value) + 3 * profile.noise_std,
        )
        sensors[profile.measurement] = {
            "display_name": profile.display_name,
            "unit": profile.unit,
            "grafana_unit": profile.grafana_unit,
            "category": str(profile.category),
            "normal_range": {"min": round(low, 4), "max": round(high, 4)},
            "thresholds": {
                "warning": round(high, 4),
                "critical": round(profile.max_value, 4),
            },
            "absolute_range": {
                "min": round(profile.min_value, 4),
                "max": round(profile.max_value, 4),
            },
        }

    by_category: dict[str, list[str]] = {}
    for profile in SENSOR_PROFILES:
        by_category.setdefault(str(profile.category), []).append(profile.measurement)

    return {
        "metadata": {
            "version": SCHEMA_VERSION,
            "description": (
                "Display names, units and operating ranges for the 61 turbine "
                "sensor channels. GENERATED from app/src/sensor_profiles.py by "
                "app/tools/generate_sensor_mappings.py -- do not edit by hand."
            ),
            "sensor_count": len(SENSOR_PROFILES),
            "source_of_truth": "app/src/sensor_profiles.py",
        },
        "categories": by_category,
        "sensors": sensors,
    }


def main() -> int:
    document = build_mappings()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(document['sensors'])} sensor mappings to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
