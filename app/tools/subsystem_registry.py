#!/usr/bin/env python3
"""
Registry and scoring model for 14 turbine subsystem digital twin assets.

Defines static asset metadata, 2D/3D coordinates, sensor threshold bindings,
and continuous piecewise linear health score evaluation.

The implementation supports:

    - 3D local coordinate and SVG 2D layout definitions
    - Shared scope dynamic threshold overrides and fallback resolution
    - Piecewise linear continuous health score evaluation (0-100)

Key classes / functions:

    - Subsystem: Digital-twin metadata for a ThingsBoard subsystem asset.
    - SensorLimits: Warning and alarm boundaries for scored telemetry keys.
    - score_subsystem: Evaluate health score, status, and alert count for an asset.

"""

from __future__ import annotations

from dataclasses import dataclass

PERFECT_SCORE = 100.0
NOMINAL_FLOOR = 90.0
WARN_FLOOR = 60.0
ZERO_SCORE = 0.0

WARNING_STATUS_THRESHOLD = NOMINAL_FLOOR
ALARM_STATUS_THRESHOLD = WARN_FLOOR

STEAM_TURBINE_RIG_ASSET_ID = "9f243750-b002-11f1-b871-bd111a5de747"


@dataclass(frozen=True)
class SensorLimits:
    """
    Warning and alarm boundary limits for a telemetry key.

    Args:
        warn (float): Warning boundary value.
        alarm (float): Critical alarm boundary value.
        source (str, optional): Provenance of the limit values. Defaults to 'static_default'.

    """

    warn: float
    alarm: float
    source: str = "static_default"

    @property
    def critical(self) -> float:
        """
        Value at which the health score reaches zero.

        Returns:
            float: Alarm threshold plus difference between alarm and warning.

        """
        return self.alarm + (self.alarm - self.warn)


@dataclass(frozen=True)
class ScoredSensor:
    """
    Telemetry key contributing to a subsystem's health score.

    Args:
        key (str): Sensor telemetry key name.
        fallback (SensorLimits): Default warning and alarm limit boundaries.

    """

    key: str
    fallback: SensorLimits


@dataclass(frozen=True)
class Subsystem:
    """
    Static digital-twin metadata for one ThingsBoard asset.

    Args:
        asset_id (str): ThingsBoard asset UUID.
        name (str): Human-readable subsystem name.
        mesh_id (str): Identifier of the corresponding 3D GLB mesh node.
        display_tier (str): Visual priority tier ('primary', 'secondary').
        position_3d (dict[str, float]): Local 3D coordinates in meters.
        position_2d (dict[str, float]): 2D diagram coordinate points in SVG viewBox.
        primary_sensors (tuple[str, ...]): Headline sensor keys bound to this asset.
        scored_sensors (tuple[ScoredSensor, ...]): Channels evaluated for health scoring.

    """

    asset_id: str
    name: str
    mesh_id: str
    display_tier: str
    position_3d: dict[str, float]
    position_2d: dict[str, float]
    primary_sensors: tuple[str, ...]
    scored_sensors: tuple[ScoredSensor, ...]

    @property
    def orientation(self) -> dict[str, float]:

        """Returns default Euler orientation angles."""
        return {"x": 0.0, "y": 0.0, "z": 0.0}

    @property
    def limit_sensor(self) -> str | None:
        """The sensor whose limits are published as the asset-level limits."""
        return self.scored_sensors[0].key if self.scored_sensors else None


def _pos3(x: float, y: float, z: float) -> dict[str, float]:
    """Constructs 3D vector dictionary."""
    return {"x": x, "y": y, "z": z}


def _pos2(x: float, y: float) -> dict[str, float]:
    """Constructs 2D vector dictionary."""
    return {"x": x, "y": y}


def _sensor(key: str, warn: float, alarm: float) -> ScoredSensor:
    """Constructs ScoredSensor with default fallback limits."""
    return ScoredSensor(key=key, fallback=SensorLimits(warn=warn, alarm=alarm))


# 3D coordinates in turbine GLB local space; 2D coordinates in SVG viewBox.
# Fallback warning and alarm limits calibrated to observed sensor operational ranges.
SUBSYSTEMS: tuple[Subsystem, ...] = (
    Subsystem(
        asset_id="9f2792b0-b002-11f1-b871-bd111a5de747",
        name="Inlet Steam Admission",
        mesh_id="SteamAdmission.001",
        display_tier="secondary",
        position_3d=_pos3(-6.0, 1.2, 0.0),
        position_2d=_pos2(105.0, 125.0),
        primary_sensors=("PT_109A", "TT_109A", "FT_110A"),
        scored_sensors=(_sensor("PT_109A", 35.0, 38.0), _sensor("TT_109A", 300.0, 350.0)),
    ),
    Subsystem(
        asset_id="9f3bb6f0-b002-11f1-b871-bd111a5de747",
        name="Emergency Stop Valve (ESV)",
        mesh_id="SteamAdmission.002",
        display_tier="secondary",
        position_3d=_pos3(-4.8, 1.2, 0.0),
        position_2d=_pos2(225.0, 100.0),
        primary_sensors=("PT_111B",),
        scored_sensors=(_sensor("PT_111B", 35.0, 37.0),),
    ),
    Subsystem(
        asset_id="9f497290-b002-11f1-b871-bd111a5de747",
        name="Throttle Valve 1 (TV1)",
        mesh_id="SteamAdmission.003",
        display_tier="secondary",
        position_3d=_pos3(-3.6, 1.0, 0.0),
        position_2d=_pos2(325.0, 105.0),
        primary_sensors=("PT_111", "TT_111"),
        scored_sensors=(_sensor("PT_111", 10.0, 13.0), _sensor("TT_111", 300.0, 350.0)),
    ),
    Subsystem(
        asset_id="9f5d96d0-b002-11f1-b871-bd111a5de747",
        name="Throttle Valve 2 (TV2)",
        mesh_id="SteamAdmission.004",
        display_tier="secondary",
        position_3d=_pos3(-2.6, 1.0, 0.0),
        position_2d=_pos2(455.0, 105.0),
        primary_sensors=("PT_112", "TT_112"),
        scored_sensors=(_sensor("PT_112", 3.0, 4.0), _sensor("TT_112", 300.0, 350.0)),
    ),
    Subsystem(
        asset_id="9f6b2b60-b002-11f1-b871-bd111a5de747",
        name="Wheel Case",
        mesh_id="Turbine.002",
        display_tier="secondary",
        position_3d=_pos3(-1.2, 0.6, 0.0),
        position_2d=_pos2(525.0, 422.0),
        primary_sensors=("PT_120", "TT_120"),
        scored_sensors=(_sensor("PT_120", 3.0, 4.0), _sensor("TT_120", 300.0, 350.0)),
    ),
    Subsystem(
        asset_id="9f7c9080-b002-11f1-b871-bd111a5de747",
        name="Turbine Core & Rotor",
        mesh_id="Turbine.001",
        display_tier="primary",
        position_3d=_pos3(0.0, 0.6, 0.0),
        position_2d=_pos2(605.0, 175.0),
        primary_sensors=("XT_600", "XT_601", "PYRO_T"),
        scored_sensors=(
            _sensor("XT_600", 4.5, 6.0),
            _sensor("XT_601", 4.5, 6.0),
            _sensor("ZT_600", 3.0, 4.5),
            _sensor("PYRO_T", 33.0, 41.0),
            _sensor("PT_109A", 35.0, 38.0),
        ),
    ),
    Subsystem(
        asset_id="9f903f90-b002-11f1-b871-bd111a5de747",
        name="Intermediate GBC",
        mesh_id="Turbine.003",
        display_tier="secondary",
        position_3d=_pos3(1.4, 0.5, 0.0),
        position_2d=_pos2(655.0, 422.0),
        primary_sensors=("PT_111C", "TT_111C"),
        scored_sensors=(_sensor("PT_111C", 0.9, 1.1), _sensor("TT_111C", 300.0, 350.0)),
    ),
    Subsystem(
        asset_id="9fa2b620-b002-11f1-b871-bd111a5de747",
        name="Gearbox",
        mesh_id="Gearbox.001",
        display_tier="primary",
        position_3d=_pos3(2.8, 0.4, 0.0),
        position_2d=_pos2(795.0, 145.0),
        primary_sensors=("XT_604", "XT_605", "PYRO_GB", "GB_TRQ"),
        scored_sensors=(
            _sensor("XT_604", 4.0, 5.5),
            _sensor("XT_605", 4.0, 5.5),
            _sensor("PYRO_GB", 40.0, 50.0),
        ),
    ),
    Subsystem(
        asset_id="9fb74f90-b002-11f1-b871-bd111a5de747",
        name="Dynamometer",
        mesh_id="Dyno.001",
        display_tier="primary",
        position_3d=_pos3(4.6, 0.4, 0.0),
        position_2d=_pos2(912.0, 175.0),
        primary_sensors=("PT_253", "DYNO_WATER_O_L"),
        # Fallback limits calibrated with headroom above observed CSV operating range.
        scored_sensors=(_sensor("PT_253", 26.0, 29.0), _sensor("DYNO_WATER_O_L", 60.0, 75.0)),
    ),
    Subsystem(
        asset_id="9fc7ca50-b002-11f1-b871-bd111a5de747",
        name="Exhaust & Hydraulics",
        mesh_id="Exhaust.001",
        display_tier="auxiliary",
        position_3d=_pos3(0.4, -1.0, 1.6),
        position_2d=_pos2(805.0, 377.0),
        primary_sensors=("PT_150A", "TT_150A"),
        scored_sensors=(_sensor("PT_150A", 0.20, 0.25), _sensor("TT_150A", 300.0, 350.0)),
    ),
    Subsystem(
        asset_id="9fdbee90-b002-11f1-b871-bd111a5de747",
        name="Gland Leakage Line 1",
        mesh_id="Leakage.001",
        display_tier="auxiliary",
        position_3d=_pos3(-1.0, -0.8, -1.8),
        position_2d=_pos2(95.0, 324.0),
        primary_sensors=("PT_162", "TT_162"),
        scored_sensors=(_sensor("PT_162", 2.0, 3.0), _sensor("TT_162", 250.0, 300.0)),
    ),
    Subsystem(
        asset_id="9fec1b30-b002-11f1-b871-bd111a5de747",
        name="Gland Leakage Line 2",
        mesh_id="Leakage.002",
        display_tier="auxiliary",
        position_3d=_pos3(-0.2, -0.8, -1.8),
        position_2d=_pos2(95.0, 379.0),
        primary_sensors=("PT_161", "TT_161"),
        scored_sensors=(_sensor("PT_161", 2.0, 3.0), _sensor("TT_161", 250.0, 300.0)),
    ),
    Subsystem(
        asset_id="9ffd8050-b002-11f1-b871-bd111a5de747",
        name="Gland Leakage Line 3 (Upstream)",
        mesh_id="Leakage.003",
        display_tier="auxiliary",
        position_3d=_pos3(0.6, -0.8, -1.8),
        position_2d=_pos2(95.0, 432.0),
        primary_sensors=("PT_160", "TT_160"),
        scored_sensors=(_sensor("PT_160", 2.0, 3.0), _sensor("TT_160", 250.0, 300.0)),
    ),
    Subsystem(
        asset_id="a00bd830-b002-11f1-b871-bd111a5de747",
        name="Gland Leakage Line 3 (Downstream)",
        mesh_id="Leakage.004",
        display_tier="auxiliary",
        position_3d=_pos3(1.4, -0.8, -1.8),
        position_2d=_pos2(160.0, 455.0),
        primary_sensors=("PT_163", "TT_163"),
        scored_sensors=(_sensor("PT_163", 2.0, 3.0), _sensor("TT_163", 250.0, 300.0)),
    ),
)

SUBSYSTEMS_BY_ASSET_ID: dict[str, Subsystem] = {s.asset_id: s for s in SUBSYSTEMS}


def resolve_limits(sensor: ScoredSensor, device_thresholds: dict[str, float]) -> SensorLimits:
    """
    Resolve sensor limits from device shared scope thresholds or static fallbacks.

    Args:
        sensor (ScoredSensor): Sensor definition containing static fallback limits.
        device_thresholds (dict[str, float]): Dictionary of device-level threshold attributes.

    Returns:
        SensorLimits: Resolved warning and alarm threshold values.

    """
    warn = device_thresholds.get(f"threshold_{sensor.key}_warn")
    alarm = device_thresholds.get(f"threshold_{sensor.key}_alarm")
    if warn is None or alarm is None or alarm <= warn:
        return sensor.fallback
    return SensorLimits(warn=float(warn), alarm=float(alarm), source="device_shared_scope")


def score_value(value: float, limits: SensorLimits) -> float:
    """
    Map an observed measurement value to a continuous 0-100 health score.

    Args:
        value (float): Observed telemetry value.
        limits (SensorLimits): Operational limit thresholds.

    Returns:
        float: Calculated health score between 0.0 and 100.0.

    Example:
        >>> limits = SensorLimits(warn=30.0, alarm=40.0)
        >>> score_value(25.0, limits)
        91.66666666666667

    """
    span = limits.alarm - limits.warn
    if limits.warn <= 0.0 or span <= 0.0:
        return PERFECT_SCORE

    if value <= limits.warn:
        approach = max(0.0, min(1.0, value / limits.warn))
        return PERFECT_SCORE - (PERFECT_SCORE - NOMINAL_FLOOR) * approach

    if value <= limits.alarm:
        into_warn_band = (value - limits.warn) / span
        return NOMINAL_FLOOR - (NOMINAL_FLOOR - WARN_FLOOR) * into_warn_band

    past_alarm = min(1.0, (value - limits.alarm) / span)
    return WARN_FLOOR - (WARN_FLOOR - ZERO_SCORE) * past_alarm


def status_for_score(score: float) -> str:
    """
    Classify a health score into NORMAL, WARNING, or ALARM status.

    Args:
        score (float): Computed health score (0-100).

    Returns:
        str: Status tag ('NORMAL', 'WARNING', or 'ALARM').

    """
    if score <= ALARM_STATUS_THRESHOLD:
        return "ALARM"
    if score <= WARNING_STATUS_THRESHOLD:
        return "WARNING"
    return "NORMAL"


def score_subsystem(
    subsystem: Subsystem,
    metrics: dict[str, float],
    device_thresholds: dict[str, float],
) -> tuple[float, str, int]:
    """
    Compute health score, status, and alert count for a subsystem.

    Args:
        subsystem (Subsystem): Subsystem asset metadata.
        metrics (dict[str, float]): Current telemetry sensor readings.
        device_thresholds (dict[str, float]): Active device threshold attributes.

    Returns:
        tuple[float, str, int]: Tuple of (health_score, health_status, active_alerts_count).

    Example:
        >>> sub = SUBSYSTEMS[0]
        >>> score, status, alerts = score_subsystem(sub, {"PT_109A": 32.0}, {})
        >>> score > 0.0
        True

    """
    worst_score = PERFECT_SCORE
    alerts = 0

    for sensor in subsystem.scored_sensors:
        value = metrics.get(sensor.key)
        if value is None:
            continue
        limits = resolve_limits(sensor, device_thresholds)
        sensor_score = score_value(float(value), limits)
        worst_score = min(worst_score, sensor_score)
        if sensor_score <= WARNING_STATUS_THRESHOLD:
            alerts += 1

    score = round(max(ZERO_SCORE, min(PERFECT_SCORE, worst_score)), 1)
    return score, status_for_score(score), alerts

