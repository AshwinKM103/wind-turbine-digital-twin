"""Physical profiles and dynamic tuning for 61 turbine sensor channels."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SensorCategory(StrEnum):
    """Broad physical category for sensor grouping and default dynamics."""

    PRESSURE = "pressure"
    FLOW = "flow"
    TEMPERATURE = "temperature"
    VIBRATION = "vibration"
    OPERATIONAL = "operational"


@dataclass(frozen=True, slots=True)
class SensorProfile:
    """Static description of one sensor channel."""

    measurement: str
    display_name: str
    unit: str
    grafana_unit: str
    category: SensorCategory
    idle_value: float
    load_value: float
    noise_std: float
    drift_per_hour: float
    min_value: float
    max_value: float
    # Time constants in seconds governing step response and noise correlation
    response_time_s: float
    noise_correlation_s: float

    def value_at(self, load_factor: float) -> float:
        """Noise-free expected value at the given load factor in [0, 1]."""
        return self.idle_value + (self.load_value - self.idle_value) * load_factor


# Calibration spread applied to full-load values across turbine units
TURBINE_BIAS_FRACTION = 0.02

# Multiplier to scale down noise amplitude during idle state
IDLE_NOISE_FRACTION = 0.3

# Standard deviations accommodated by absolute range before clamping
_NOISE_SIGMA_GUARD = 3.0

@dataclass(frozen=True, slots=True)
class CategoryTuning:
    """Dynamic response and noise characteristics for a sensor category."""

    noise_fraction: float
    drift_fraction: float
    allows_negative: bool
    # Time in seconds to reach 63% of step change in load
    response_time_s: float
    # Correlation time of measurement noise in seconds
    noise_correlation_s: float


_CATEGORY_TUNING: dict[SensorCategory, CategoryTuning] = {
    SensorCategory.PRESSURE: CategoryTuning(0.03, 0.01, False, 4.0, 8.0),
    SensorCategory.FLOW: CategoryTuning(0.04, 0.01, False, 6.0, 8.0),
    SensorCategory.TEMPERATURE: CategoryTuning(0.02, 0.02, False, 30.0, 30.0),
    SensorCategory.VIBRATION: CategoryTuning(0.10, 0.02, False, 15.0, 4.0),
    SensorCategory.OPERATIONAL: CategoryTuning(0.005, 0.005, True, 2.0, 6.0),
}


def _make_profile(
    measurement: str,
    display_name: str,
    category: SensorCategory,
    unit: str,
    grafana_unit: str,
    idle: float,
    load: float,
    noise_fraction: float | None = None,
) -> SensorProfile:
    """Derive full sensor profile with bounds, noise, and drift from idle and load endpoints."""
    tuning = _CATEGORY_TUNING[category]
    span = max(abs(load - idle), 0.01)
    noise_std = span * (noise_fraction if noise_fraction is not None else tuning.noise_fraction)
    drift_per_hour = span * tuning.drift_fraction

    # Bounds accommodate calibration bias, noise guards, and drift
    biased_low = min(idle, load * (1.0 - TURBINE_BIAS_FRACTION))
    biased_high = max(idle, load * (1.0 + TURBINE_BIAS_FRACTION))
    low_guard = _NOISE_SIGMA_GUARD * noise_std * IDLE_NOISE_FRACTION + drift_per_hour
    high_guard = _NOISE_SIGMA_GUARD * noise_std + drift_per_hour

    min_value = biased_low - low_guard
    if not tuning.allows_negative:
        min_value = max(0.0, min_value)

    return SensorProfile(
        measurement=measurement,
        display_name=display_name,
        unit=unit,
        grafana_unit=grafana_unit,
        category=category,
        idle_value=idle,
        load_value=load,
        noise_std=noise_std,
        drift_per_hour=drift_per_hour,
        min_value=min_value,
        max_value=biased_high + high_guard,
        response_time_s=tuning.response_time_s,
        noise_correlation_s=tuning.noise_correlation_s,
    )


def _pressure(
    measurement: str, display_name: str, idle: float, load: float, unit: str = "kg/cm2"
) -> SensorProfile:
    """Create a pressure SensorProfile."""
    return _make_profile(
        measurement,
        display_name,
        SensorCategory.PRESSURE,
        unit,
        "pressurebar" if unit == "bar" else "none",
        idle,
        load,
    )


def _flow(measurement: str, display_name: str, idle: float, load: float) -> SensorProfile:
    """Create a flow SensorProfile."""
    return _make_profile(
        measurement, display_name, SensorCategory.FLOW, "TPH", "none", idle, load
    )


def _temperature(measurement: str, display_name: str, idle: float, load: float) -> SensorProfile:
    """Create a temperature SensorProfile."""
    return _make_profile(
        measurement, display_name, SensorCategory.TEMPERATURE, "degC", "celsius", idle, load
    )


def _vibration(measurement: str, display_name: str, idle: float, load: float) -> SensorProfile:
    """Create a vibration SensorProfile."""
    return _make_profile(
        measurement, display_name, SensorCategory.VIBRATION, "mm/s", "accMS2", idle, load
    )


def _operational(
    measurement: str,
    display_name: str,
    unit: str,
    grafana_unit: str,
    idle: float,
    load: float,
    noise_fraction: float | None = None,
) -> SensorProfile:
    """Create an operational SensorProfile."""
    return _make_profile(
        measurement,
        display_name,
        SensorCategory.OPERATIONAL,
        unit,
        grafana_unit,
        idle,
        load,
        noise_fraction=noise_fraction,
    )


# Ordered to match kafka_consumer.MEASUREMENTS (excluding seq_no)
SENSOR_PROFILES: tuple[SensorProfile, ...] = (
    _pressure("PT_109A", "Inlet Pressure A", 31.0, 33.0, unit="bar"),
    _pressure("PT_110A", "Inlet Pressure B", 3.1, 3.4),
    _pressure("PT_110B", "Inlet Pressure C", 3.0, 3.3),
    _pressure("PT_111B", "Stage 1 Pressure B", 2.8, 3.2),
    _pressure("PT_111", "Stage 1 Pressure", 2.9, 3.3),
    _pressure("PT_112", "Stage 2 Pressure", 2.6, 3.0),
    _pressure("PT_162", "Lube Oil Pressure", 1.8, 2.4),
    _pressure("PT_161", "Lube Oil Supply Pressure", 1.9, 2.5),
    _pressure("PT_160", "Lube Oil Header Pressure", 2.0, 2.6),
    _pressure("PT_120", "Gearbox Oil Pressure", 2.2, 2.9),
    _pressure("PT_111C", "Stage 1 Pressure C", 2.7, 3.1),
    _pressure("PT_153", "Seal Gas Pressure", 1.4, 1.7),
    _pressure("PT_163", "Lube Oil Return Pressure", 0.9, 1.2),
    _pressure("PT_150A", "Hydraulic Pressure A", 120.0, 165.0),
    _pressure("PT_150B", "Hydraulic Pressure B", 118.0, 162.0),
    _pressure("PT_201", "Cooling Water Pressure", 2.4, 2.8),
    _pressure("PT_253", "Dyno Water Pressure", 2.1, 2.5),
    _flow("FT_110A", "Main Water Flow", 4.0, 26.0),
    _flow("FT_162", "Lube Oil Flow", 1.2, 6.5),
    _temperature("TT_109A", "Gearbox Bearing Temp A", 45.0, 82.0),
    _temperature("TT_110A", "Gearbox Bearing Temp B", 44.0, 80.0),
    _temperature("TT_110B", "Gearbox Bearing Temp C", 43.0, 78.0),
    _temperature("TT_111", "Stage 1 Inlet Temp", 38.0, 74.0),
    _temperature("TT_112", "Stage 2 Inlet Temp", 36.0, 71.0),
    _temperature("TT_162", "Lube Oil Temp", 34.0, 62.0),
    _temperature("TT_161", "Lube Oil Supply Temp", 33.0, 58.0),
    _temperature("TT_160", "Lube Oil Header Temp", 33.5, 60.0),
    _temperature("TT_120_R", "Gearbox Oil Return Temp", 35.0, 68.0),
    _temperature("TT_120", "Gearbox Oil Temp", 37.0, 72.0),
    _temperature("TT_111C", "Stage 1 Temp C", 36.5, 70.0),
    _temperature("TT_111C_R", "Stage 1 Return Temp C", 35.5, 66.0),
    _temperature("DYNO_WATER_O_L", "Dyno Water Outlet Temp", 28.0, 52.0),
    _temperature("TT_163", "Lube Oil Return Temp", 32.0, 61.0),
    _temperature("TT_150A", "Hydraulic Oil Temp A", 30.0, 55.0),
    _temperature("TT_150B", "Hydraulic Oil Temp B", 29.5, 54.0),
    _vibration("ZT_600", "Gearbox Vibration Z1", 0.6, 3.4),
    _vibration("ZT_601", "Gearbox Vibration Z2", 0.6, 3.2),
    _vibration("XT_600", "Gearbox Vibration X", 0.7, 3.6),
    _vibration("XT_601", "Gearbox Vibration Y", 0.7, 3.5),
    _vibration("XT_602", "Generator Vibration X", 0.5, 2.9),
    _vibration("XT_603", "Generator Vibration Y", 0.5, 2.8),
    _vibration("XT_604", "Rotor Vibration X", 0.4, 2.4),
    _vibration("XT_605", "Rotor Vibration Y", 0.4, 2.3),
    _vibration("XT_606", "Shaft Vibration X", 0.35, 2.1),
    _vibration("XT_607", "Shaft Vibration Y", 0.35, 2.0),
    _operational("HP_DEMAND", "Hydraulic Power Demand", "percent", "percent", 5.0, 78.0),
    _operational("ACT_POS_FB", "Actuator Position Feedback", "percent", "percent", 2.0, 86.0),
    _operational("GB_TRQ", "Gearbox Torque", "kN.m", "none", 0.02, 7.0, noise_fraction=0.02),
    _operational("PYRO_T", "Pyrometer Turbine Temp", "degC", "celsius", 40.0, 320.0),
    _operational("PYRO_GB", "Pyrometer Gearbox Temp", "degC", "celsius", 38.0, 190.0),
    _operational("TURBINE_SPEED_RPM", "Turbine Rotor Speed", "rpm", "rotrpm", 120.0, 11800.0),
    _temperature("RTD_219A", "Generator Winding Temp A", 30.0, 88.0),
    _temperature("RTD_219B", "Generator Winding Temp B", 30.0, 87.0),
    _temperature("RTD_220", "Generator Bearing Temp DE", 29.0, 74.0),
    _temperature("RTD_221", "Generator Bearing Temp NDE", 29.0, 72.0),
    _temperature("RTD_200", "Nacelle Ambient Temp", 22.0, 31.0),
    _temperature("RTD_202", "Cooling Water Inlet Temp", 24.0, 38.0),
    _temperature("RTD_203", "Cooling Water Outlet Temp", 25.0, 47.0),
    _temperature("RTD_204", "Main Bearing Temp DE", 28.0, 69.0),
    _temperature("RTD_205", "Main Bearing Temp NDE", 28.0, 67.0),
    _temperature("RTD_201", "Tower Base Temp", 21.0, 27.0),
)

PROFILES_BY_MEASUREMENT: dict[str, SensorProfile] = {
    profile.measurement: profile for profile in SENSOR_PROFILES
}

SENSOR_COUNT = 61
assert len(SENSOR_PROFILES) == SENSOR_COUNT, (
    f"expected {SENSOR_COUNT} sensor profiles, found {len(SENSOR_PROFILES)}"
)
assert len(PROFILES_BY_MEASUREMENT) == SENSOR_COUNT, "duplicate measurement name in SENSOR_PROFILES"
