"""Allowlisted dashboard navigation actions and resolution for the turbine copilot.

Enforces strict allowlisting for UI dashboard navigation suggestions, resolving symbolic
dashboard keys to verified ThingsBoard dashboard UUIDs without equipment write access.

Exported Classes:
    DashboardActionError: Raised when a requested dashboard key is not in allowlist.

Exported Functions:
    build_open_dashboard_action: Resolves allowlisted key to an OPEN_DASHBOARD action dictionary.
"""


from __future__ import annotations

DASHBOARD_ALLOWLIST: dict[str, dict[str, str]] = {
    "safety_alarms": {
        "dashboardId": "0774c890-b19a-11f1-a9d0-15449c55f7bc",
        "title": "Turbine Safety & Alarm Thresholds",
    },
    "thermodynamics": {
        "dashboardId": "1d1d0d50-b196-11f1-a9d0-15449c55f7bc",
        "title": "Turbine Thermodynamics & Process Dynamics",
    },
    "3d_digital_twin": {
        "dashboardId": "3503e260-b0cc-11f1-9bfc-5d2538928d0b",
        "title": "Turbine 3D Digital Twin (Babylon.js — Animated)",
    },
    "scada_mimic": {
        "dashboardId": "c5704b70-b04c-11f1-9bfc-5d2538928d0b",
        "title": "Turbine Process SCADA Mimic",
    },
    "rotordynamics": {
        "dashboardId": "c578fe00-b04c-11f1-9bfc-5d2538928d0b",
        "title": "Turbine Rotordynamics & Vibration",
    },
}


class DashboardActionError(Exception):
    """Raised when a requested dashboard key isn't in the allowlist."""


def build_open_dashboard_action(dashboard_key: str) -> dict[str, str]:
    """Resolves an allowlisted dashboard key to a navigation intent object.

    Args:
        dashboard_key: One of DASHBOARD_ALLOWLIST's keys.

    Returns:
        {"action": "OPEN_DASHBOARD", "dashboardId": ..., "dashboardKey": ..., "label": ...}

    Raises:
        DashboardActionError: If dashboard_key is not in the allowlist.
    """
    entry = DASHBOARD_ALLOWLIST.get(dashboard_key)
    if not entry:
        known = ", ".join(DASHBOARD_ALLOWLIST.keys())
        raise DashboardActionError(
            f"Unknown dashboard '{dashboard_key}'. Known dashboards: {known}"
        )

    return {
        "action": "OPEN_DASHBOARD",
        "dashboardId": entry["dashboardId"],
        "dashboardKey": dashboard_key,
        "label": f"Open {entry['title']}",
    }
