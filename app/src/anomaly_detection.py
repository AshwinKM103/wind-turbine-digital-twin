"""
Anomaly detection engine and alert generation service for wind turbine sensors.

Consumes incoming telemetry readings and applies statistical, state-aware,
temporal, and multi-sensor correlation rules to detect operational faults,
sensor drifts, and anomalous conditions before dispatching alerts.

The implementation supports:

    - Statistical out-of-range checks with operational state awareness
    - Temporal drift, rapid rise, and stuck-sensor fault detection
    - Cross-sensor correlation break and composite boolean condition evaluation
    - False-positive suppression using confirmation counts and grace periods

Key classes / functions:

    - AnomalyDetector: Main detection engine evaluating windowed telemetry readings.
    - Alert: Structured alert dataclass containing severity and threshold diagnostics.
    - SensorReading: Normalized telemetry event data structure.
    - AlertSeverity / DetectionType: Enumerated classifications for detected anomalies.

"""

import json
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from confluent_kafka import Consumer, Producer, KafkaError

from config import Config
from health_server import start_health_server
from logging_config import configure_logging

log = configure_logging("anomaly-detector")


class AlertSeverity(Enum):
    """
    Alert severity classification levels.

    Attributes:
        INFO (str): Informational alert requiring no immediate intervention.
        WARNING (str): Potential issue or early warning sign.
        CRITICAL (str): Urgent fault condition requiring prompt mitigation.

    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class DetectionType(Enum):
    """
    Types and categories of anomaly detection mechanisms.

    Attributes:
        OUT_OF_RANGE (str): Value exceeded state-specific min/max thresholds.
        DRIFT (str): Sensor calibration or gradual physical value drift over time.
        STUCK_VALUE (str): Sensor output unchanged across multiple evaluation windows.
        RAPID_RISE (str): Rapid absolute rate of rise over short intervals.
        RAPID_INCREASE (str): Rapid percentage jump above baseline average.
        CORRELATION_BREAK (str): Divergence between paired correlated sensors.
        MULTI_SENSOR (str): Simultaneous condition match across multiple distinct sensors.
        STATE_ANOMALY (str): Sensor telemetry conflicting with operational state machine.

    """

    OUT_OF_RANGE = "out_of_range"
    DRIFT = "drift"
    STUCK_VALUE = "stuck_value"
    RAPID_RISE = "rapid_rise"
    RAPID_INCREASE = "rapid_increase"
    CORRELATION_BREAK = "correlation_break"
    MULTI_SENSOR = "multi_sensor"
    STATE_ANOMALY = "state_anomaly"


@dataclass
class Alert:
    """
    Anomaly alert message payload and diagnostic metadata.

    Attributes:
        alert_id (str): Unique alert identifier UUID.
        timestamp_ms (int): Millisecond epoch timestamp when anomaly triggered.
        customer_id (str): Customer identifier.
        turbine_id (str): Turbine identifier.
        device_path (str): Fully qualified IoTDB device path.
        sensor (str): Name of primary anomalous sensor.
        value (float): Measured value triggering alert.
        detection_type (str): Classification type of detection.
        severity (str): Alert severity level string ('info', 'warning', 'critical').
        reason (str): Human-readable explanatory description.
        threshold_info (Optional[Dict]): Diagnostic threshold evaluation context.
        additional_context (Optional[Dict]): Additional metadata or correlation details.

    """

    alert_id: str
    timestamp_ms: int
    customer_id: str
    turbine_id: str
    device_path: str
    sensor: str
    value: float
    detection_type: str
    severity: str
    reason: str
    threshold_info: Optional[Dict] = None
    additional_context: Optional[Dict] = None

    def to_json(self) -> str:
        """
        Serialize alert dataclass to JSON string for Kafka transmission.

        Returns:
            str: JSON formatted string representation.

        """
        return json.dumps(asdict(self))


@dataclass
class SensorReading:
    """
    Single sensor reading with identity and sequence metadata.

    Attributes:
        timestamp_ms (int): Millisecond epoch timestamp.
        customer_id (str): Customer identifier.
        turbine_id (str): Turbine identifier.
        sensor_name (str): Measured metric or sensor name.
        value (float): Scalar measurement value.
        device_path (str): Fully qualified IoTDB device path.
        sequence_number (int): Message sequence number.

    """

    timestamp_ms: int
    customer_id: str
    turbine_id: str
    sensor_name: str
    value: float
    device_path: str
    sequence_number: int


class AnomalyDetector:
    """
    Main anomaly detection engine for turbine telemetry.

    Maintains rolling time-series windows of sensor data, evaluates rule sets
    across multiple detection algorithms, tracks confirmation counts to filter
    transient false positives, and publishes confirmed alerts to Kafka.

    """

    def __init__(self, config_path: str = "app/config/anomaly_thresholds.json") -> None:
        """
        Initialize anomaly detector with configuration file and state buffers.

        Args:
            config_path (str, optional): Path to JSON configuration file. Defaults to "app/config/anomaly_thresholds.json".

        """
        self.config = self._load_config(config_path)
        self.global_settings = self.config.get("global_settings", {})
        self.sensor_history: Dict[Tuple[str, str, str], deque] = defaultdict(
            lambda: deque(maxlen=3600)
        )
        self.alert_tracking: Dict = defaultdict(lambda: {
            "count": 0,
            "first_triggered": None,
            "last_triggered": None,
            "last_published": None,
        })
        self.grace_periods: Dict[Tuple[str, str, str], int] = {}
        self.producer = self._build_producer()

    def _load_config(self, config_path: str) -> Dict:
        """
        Load anomaly threshold configuration from JSON file.

        Args:
            config_path (str): File path to anomaly thresholds JSON.

        Returns:
            Dict: Parsed configuration dictionary.

        Raises:
            FileNotFoundError: If configuration file does not exist.
            json.JSONDecodeError: If file content is not valid JSON.

        """
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            log.error(f"Anomaly config not found: {config_path}", extra={"path": config_path})
            raise
        except json.JSONDecodeError as e:
            log.error(f"Anomaly config JSON invalid: {config_path}", extra={"error": str(e)})
            raise

    def _build_producer(self) -> Producer:
        """
        Build Kafka producer for publishing anomaly alerts.

        Returns:
            Producer: Configured idempotent confluent_kafka Producer instance.

        """
        return Producer({
            "bootstrap.servers": Config.KAFKA_BOOTSTRAP_SERVERS,
            "acks": "all",
            "enable.idempotence": True,
            "retries": 3,
            "delivery.timeout.ms": 120000,
            "linger.ms": 50,
        })

    def process_reading(self, reading: SensorReading) -> List[Alert]:
        """
        Process a single sensor reading and detect anomalies across algorithms.

        Args:
            reading (SensorReading): Normalized sensor telemetry reading.

        Returns:
            List[Alert]: List of triggered Alert objects (empty if nominal).

        """
        alerts = []
        key = (reading.customer_id, reading.turbine_id, reading.sensor_name)
        self.sensor_history[key].append(reading)

        if self._is_in_grace_period(key, reading.timestamp_ms):
            return alerts

        detection_methods = [
            self._detect_out_of_range,
            self._detect_stuck_value,
            self._detect_rapid_rise,
            self._detect_rapid_increase,
            self._detect_drift,
            self._detect_correlation_break,
            self._check_multi_sensor_conditions,
        ]

        for detect_fn in detection_methods:
            try:
                alert = detect_fn(reading, key)
                if alert:
                    alerts.append(alert)
            except Exception as e:
                log.error(
                    "Detection method failed",
                    extra={
                        "method": detect_fn.__name__,
                        "sensor": reading.sensor_name,
                        "error": str(e),
                    }
                )

        return alerts

    def _is_in_grace_period(self, key: Tuple[str, str, str], timestamp_ms: int) -> bool:
        """
        Check if sensor is within an active grace period suppressing duplicate alerts.

        Args:
            key (Tuple[str, str, str]): Composite key of (customer_id, turbine_id, sensor_name).
            timestamp_ms (int): Current reading timestamp in epoch milliseconds.

        Returns:
            bool: True if inside active grace period window, False otherwise.

        """
        grace_end = self.grace_periods.get(key)
        if grace_end is None:
            return False
        if timestamp_ms >= grace_end:
            del self.grace_periods[key]
            return False
        return True

    def _enter_grace_period(self, key: Tuple[str, str, str], timestamp_ms: int) -> None:
        """
        Enter a cooldown grace period for a sensor after an alert fires.

        Args:
            key (Tuple[str, str, str]): Composite sensor key tuple.
            timestamp_ms (int): Current reading timestamp in epoch milliseconds.

        """
        grace_minutes = self.global_settings.get("grace_period_minutes", 5)
        grace_period_ms = grace_minutes * 60 * 1000
        self.grace_periods[key] = timestamp_ms + grace_period_ms

    def _get_sensor_spec(self, sensor_name: str) -> Optional[Dict]:
        """
        Retrieve configuration specification for a given sensor name.

        Args:
            sensor_name (str): Sensor measurement identifier.

        Returns:
            Optional[Dict]: Sensor threshold and anomaly rule configuration dictionary.

        """
        return self.config.get("sensors", {}).get(sensor_name)

    def _infer_turbine_state(self, customer_id: str, turbine_id: str) -> str:
        """
        Infer operational state from recent rotor speed and torque telemetry.

        Args:
            customer_id (str): Customer identifier.
            turbine_id (str): Turbine identifier.

        Returns:
            str: Inferred state name ('IDLE', 'RAMP_UP', 'STEADY_STATE', or 'RAMP_DOWN').

        """
        # Try to find recent RPM and torque readings
        rpm_key = (customer_id, turbine_id, "TURBINE_SPEED_RPM")
        torque_key = (customer_id, turbine_id, "GB_TRQ")

        rpm = self.sensor_history[rpm_key][-1].value if rpm_key in self.sensor_history and self.sensor_history[rpm_key] else None
        torque = self.sensor_history[torque_key][-1].value if torque_key in self.sensor_history and self.sensor_history[torque_key] else None

        if rpm is None:
            return "STEADY_STATE"  # Default

        # Simple state machine inference
        if rpm < 500:
            return "IDLE"
        elif rpm > 12500:
            return "RAMP_DOWN"
        elif 11000 <= rpm <= 12500:
            return "STEADY_STATE"  # At rated speed
        elif 500 <= rpm < 2000:
            return "RAMP_UP"
        else:
            # Somewhere in middle (2000-11000), in transition
            return "RAMP_UP"

    def _detect_out_of_range(self, reading: SensorReading, key: Tuple) -> Optional[Alert]:
        """
        Detect sensor reading outside state-dependent configured thresholds.

        Args:
            reading (SensorReading): Incoming sensor reading.
            key (Tuple): Key tuple of (customer_id, turbine_id, sensor_name).

        Returns:
            Optional[Alert]: Out-of-range Alert if threshold violated, else None.

        """
        spec = self._get_sensor_spec(reading.sensor_name)
        if not spec:
            return None

        rules = spec.get("anomaly_rules", [])
        out_of_range_rule = next(
            (r for r in rules if r.get("type") == "out_of_range" and r.get("enabled")),
            None
        )
        if not out_of_range_rule:
            return None

        state = self._infer_turbine_state(reading.customer_id, reading.turbine_id)
        thresholds = spec.get("thresholds", {}).get(state, {})

        if not thresholds:
            return None

        critical_min = thresholds.get("critical_min")
        critical_max = thresholds.get("critical_max")
        warning_min = thresholds.get("warning_min")
        warning_max = thresholds.get("warning_max")

        if critical_min is not None and reading.value < critical_min:
            return self._create_alert(
                reading,
                DetectionType.OUT_OF_RANGE,
                AlertSeverity.CRITICAL,
                f"{reading.sensor_name} = {reading.value:.2f} {spec.get('unit', '')} "
                f"below critical min {critical_min} (state: {state})",
                {"critical_min": critical_min, "state": state},
            )

        if critical_max is not None and reading.value > critical_max:
            return self._create_alert(
                reading,
                DetectionType.OUT_OF_RANGE,
                AlertSeverity.CRITICAL,
                f"{reading.sensor_name} = {reading.value:.2f} {spec.get('unit', '')} "
                f"above critical max {critical_max} (state: {state})",
                {"critical_max": critical_max, "state": state},
            )

        if warning_min is not None and reading.value < warning_min:
            return self._create_alert(
                reading,
                DetectionType.OUT_OF_RANGE,
                AlertSeverity.WARNING,
                f"{reading.sensor_name} = {reading.value:.2f} {spec.get('unit', '')} "
                f"below warning min {warning_min} (state: {state})",
                {"warning_min": warning_min, "state": state},
            )

        if warning_max is not None and reading.value > warning_max:
            return self._create_alert(
                reading,
                DetectionType.OUT_OF_RANGE,
                AlertSeverity.WARNING,
                f"{reading.sensor_name} = {reading.value:.2f} {spec.get('unit', '')} "
                f"above warning max {warning_max} (state: {state})",
                {"warning_max": warning_max, "state": state},
            )

        return None

    def _detect_stuck_value(self, reading: SensorReading, key: Tuple) -> Optional[Alert]:
        """
        Detect sensor value not changing over an extended temporal window.

        Args:
            reading (SensorReading): Incoming sensor reading.
            key (Tuple): Key tuple of (customer_id, turbine_id, sensor_name).

        Returns:
            Optional[Alert]: Stuck-value Alert if frozen readings exceed threshold, else None.

        """
        spec = self._get_sensor_spec(reading.sensor_name)
        if not spec:
            return None

        rules = spec.get("anomaly_rules", [])
        stuck_rule = next(
            (r for r in rules if r.get("type") == "stuck_value" and r.get("enabled")),
            None
        )
        if not stuck_rule:
            return None

        stuck_duration_s = stuck_rule.get("stuck_duration_seconds", 600)
        history = self.sensor_history[key]

        if len(history) < 2:
            return None

        current_value = reading.value
        age_cutoff_ms = reading.timestamp_ms - (stuck_duration_s * 1000)

        stuck_readings = [
            r for r in history
            if r.timestamp_ms >= age_cutoff_ms and abs(r.value - current_value) < 0.001
        ]

        if len(stuck_readings) > stuck_duration_s * 0.8:
            return self._create_alert(
                reading,
                DetectionType.STUCK_VALUE,
                AlertSeverity.CRITICAL,
                f"{reading.sensor_name} stuck at {current_value:.2f} for {stuck_duration_s}s "
                "(possible sensor failure)",
                {"stuck_duration_s": stuck_duration_s, "stuck_value": current_value},
            )

        return None

    def _detect_rapid_rise(self, reading: SensorReading, key: Tuple) -> Optional[Alert]:
        """
        Detect temperature or pressure rising rapidly over a rolling window.

        Args:
            reading (SensorReading): Incoming sensor reading.
            key (Tuple): Key tuple of (customer_id, turbine_id, sensor_name).

        Returns:
            Optional[Alert]: Rapid rise Alert if rate of change exceeds limit, else None.

        """
        spec = self._get_sensor_spec(reading.sensor_name)
        if not spec:
            return None

        rules = spec.get("anomaly_rules", [])
        rapid_rule = next(
            (r for r in rules if r.get("type") == "rapid_rise" and r.get("enabled")),
            None
        )
        if not rapid_rule:
            return None

        rise_threshold_per_minute = rapid_rule.get("rise_threshold_per_minute", 2.0)
        duration_minutes = rapid_rule.get("duration_minutes", 5)
        history = self.sensor_history[key]

        if len(history) < 2:
            return None

        window_ms = duration_minutes * 60 * 1000
        old_cutoff_ms = reading.timestamp_ms - window_ms

        old_readings = [r for r in history if r.timestamp_ms >= old_cutoff_ms]

        if not old_readings:
            return None

        oldest_value = old_readings[0].value
        current_value = reading.value
        rise = current_value - oldest_value

        if rise > rise_threshold_per_minute * duration_minutes:
            return self._create_alert(
                reading,
                DetectionType.RAPID_RISE,
                AlertSeverity.CRITICAL,
                f"{reading.sensor_name} rose {rise:.2f} in {duration_minutes} min "
                f"(threshold: {rise_threshold_per_minute:.2f}/min)",
                {
                    "rise_total": rise,
                    "rise_per_minute": rise / duration_minutes,
                    "threshold_per_minute": rise_threshold_per_minute,
                    "old_value": oldest_value,
                    "current_value": current_value,
                },
            )

        return None

    def _detect_rapid_increase(self, reading: SensorReading, key: Tuple) -> Optional[Alert]:
        """
        Detect rapid percentage increase in sensor value relative to baseline average.

        Args:
            reading (SensorReading): Incoming sensor reading.
            key (Tuple): Key tuple of (customer_id, turbine_id, sensor_name).

        Returns:
            Optional[Alert]: Rapid increase Alert if percentage change exceeds threshold, else None.

        """
        spec = self._get_sensor_spec(reading.sensor_name)
        if not spec:
            return None

        rules = spec.get("anomaly_rules", [])
        increase_rule = next(
            (r for r in rules if r.get("type") == "rapid_increase" and r.get("enabled")),
            None
        )
        if not increase_rule:
            return None

        increase_threshold_percent = increase_rule.get("increase_threshold_percent", 50)
        baseline_window_minutes = increase_rule.get("baseline_window_minutes", 10)
        history = self.sensor_history[key]

        if len(history) < 2:
            return None

        window_ms = baseline_window_minutes * 60 * 1000
        old_cutoff_ms = reading.timestamp_ms - window_ms

        baseline_readings = [r for r in history if r.timestamp_ms >= old_cutoff_ms]

        if not baseline_readings:
            return None

        baseline_value = sum(r.value for r in baseline_readings) / len(baseline_readings)
        current_value = reading.value

        if baseline_value == 0:
            if current_value > 0.1:
                increase_percent = 100.0
            else:
                increase_percent = 0.0
        else:
            increase_percent = ((current_value - baseline_value) / baseline_value) * 100.0

        if increase_percent > increase_threshold_percent:
            return self._create_alert(
                reading,
                DetectionType.RAPID_INCREASE,
                AlertSeverity(increase_rule.get("severity", "critical")),
                f"{reading.sensor_name} increased {increase_percent:.1f}% "
                f"(baseline {baseline_window_minutes}min avg: {baseline_value:.2f}, "
                f"current: {current_value:.2f}, threshold: {increase_threshold_percent}%)",
                {
                    "increase_percent": increase_percent,
                    "baseline_value": baseline_value,
                    "current_value": current_value,
                    "threshold_percent": increase_threshold_percent,
                    "baseline_window_minutes": baseline_window_minutes,
                },
            )

        return None

    def _detect_drift(self, reading: SensorReading, key: Tuple) -> Optional[Alert]:
        """
        Detect slow monotonic or directional drift over time.

        Args:
            reading (SensorReading): Incoming sensor reading.
            key (Tuple): Key tuple of (customer_id, turbine_id, sensor_name).

        Returns:
            Optional[Alert]: Drift Alert if gradual change exceeds threshold per hour, else None.

        """
        spec = self._get_sensor_spec(reading.sensor_name)
        if not spec:
            return None

        rules = spec.get("anomaly_rules", [])
        drift_rule = next(
            (r for r in rules if r.get("type") == "drift" and r.get("enabled")),
            None
        )
        if not drift_rule:
            return None

        drift_threshold_per_hour = drift_rule.get("drift_threshold_per_hour", 0.5)
        history = self.sensor_history[key]

        if len(history) < 60:
            return None

        oldest = history[0]
        newest = history[-1]

        time_elapsed_ms = newest.timestamp_ms - oldest.timestamp_ms
        if time_elapsed_ms < 600_000:
            return None

        time_elapsed_hours = time_elapsed_ms / (3600 * 1000)
        drift = abs(newest.value - oldest.value)
        expected_drift = drift_threshold_per_hour * time_elapsed_hours

        if drift > expected_drift * 1.5:
            return self._create_alert(
                reading,
                DetectionType.DRIFT,
                AlertSeverity.WARNING,
                f"{reading.sensor_name} drifted {drift:.2f} over {time_elapsed_hours:.1f}h "
                f"(threshold: {drift_threshold_per_hour:.2f}/h)",
                {
                    "drift_total": drift,
                    "drift_per_hour": drift / time_elapsed_hours,
                    "threshold_per_hour": drift_threshold_per_hour,
                    "old_value": oldest.value,
                    "current_value": newest.value,
                },
            )

        return None

    def _detect_correlation_break(self, reading: SensorReading, key: Tuple) -> Optional[Alert]:
        """
        Detect divergence between paired sensors that should track together.

        Args:
            reading (SensorReading): Incoming sensor reading.
            key (Tuple): Key tuple of (customer_id, turbine_id, sensor_name).

        Returns:
            Optional[Alert]: Correlation break Alert if paired sensors diverge, else None.

        """
        correlation_rules = self.config.get("correlation_rules", [])

        matching_rules = [
            r for r in correlation_rules
            if reading.sensor_name in r.get("sensor_pairs", []) and r.get("enabled")
        ]

        if not matching_rules:
            return None

        for rule in matching_rules:
            if rule.get("correlation_type") == "should_track":
                alert = self._check_tracking_correlation(reading, rule)
                if alert:
                    return alert

        return None

    def _check_tracking_correlation(self, reading: SensorReading, rule: Dict) -> Optional[Alert]:
        """
        Check whether readings between paired sensors exceed maximum allowed divergence.

        Args:
            reading (SensorReading): Current sensor reading.
            rule (Dict): Paired correlation rule configuration.

        Returns:
            Optional[Alert]: Alert if divergence exceeds tolerance, else None.

        """
        sensor_pairs = rule.get("sensor_pairs", [])
        max_divergence = rule.get("max_divergence", 5.0)

        if reading.sensor_name not in sensor_pairs:
            return None

        # Get the other sensor in the pair
        other_sensor = next((s for s in sensor_pairs if s != reading.sensor_name), None)
        if not other_sensor:
            return None

        # Find recent reading of other sensor
        other_key = (reading.customer_id, reading.turbine_id, other_sensor)
        other_history = self.sensor_history.get(other_key, deque())

        if not other_history:
            return None

        other_value = other_history[-1].value
        divergence = abs(reading.value - other_value)

        if divergence > max_divergence:
            return self._create_alert(
                reading,
                DetectionType.CORRELATION_BREAK,
                AlertSeverity(rule.get("severity", "warning")),
                f"{reading.sensor_name} and {other_sensor} diverged by {divergence:.2f} "
                f"(max: {max_divergence}). Rule: {rule.get('name', '')}",
                {
                    "sensor1": reading.sensor_name,
                    "sensor1_value": reading.value,
                    "sensor2": other_sensor,
                    "sensor2_value": other_value,
                    "divergence": divergence,
                    "max_allowed": max_divergence,
                },
            )

        return None

    def _check_multi_sensor_conditions(self, reading: SensorReading, key: Tuple) -> Optional[Alert]:
        """
        Detect anomalies based on multiple sensor conditions evaluated with AND logic.

        Args:
            reading (SensorReading): Incoming sensor reading.
            key (Tuple): Key tuple of (customer_id, turbine_id, sensor_name).

        Returns:
            Optional[Alert]: Multi-sensor Alert if all conditions in rule are satisfied, else None.

        """
        correlation_rules = self.config.get("correlation_rules", [])

        multi_sensor_rules = [
            r for r in correlation_rules
            if r.get("sensor_conditions") and r.get("enabled")
        ]

        if not multi_sensor_rules:
            return None

        for rule in multi_sensor_rules:
            alert = self._evaluate_multi_sensor_rule(reading, rule)
            if alert:
                return alert

        return None

    def _evaluate_multi_sensor_rule(self, reading: SensorReading, rule: Dict) -> Optional[Alert]:
        """
        Evaluate if all condition expressions in a multi-sensor rule are simultaneously met.

        Args:
            reading (SensorReading): Current trigger sensor reading.
            rule (Dict): Rule dictionary containing list of sensor conditions.

        Returns:
            Optional[Alert]: Alert if all conditions pass, else None.

        """
        conditions = rule.get("sensor_conditions", [])
        if not conditions:
            return None

        all_conditions_met = True
        condition_details = []

        for condition in conditions:
            sensor_name = condition.get("sensor")
            operator = condition.get("operator")
            threshold = condition.get("threshold")

            if not all([sensor_name, operator, threshold is not None]):
                continue

            sensor_key = (reading.customer_id, reading.turbine_id, sensor_name)
            sensor_history = self.sensor_history.get(sensor_key, deque())

            if not sensor_history:
                all_conditions_met = False
                break

            sensor_value = sensor_history[-1].value

            condition_met = self._evaluate_condition(sensor_value, operator, threshold)
            condition_details.append({
                "sensor": sensor_name,
                "value": sensor_value,
                "operator": operator,
                "threshold": threshold,
                "met": condition_met,
            })

            if not condition_met:
                all_conditions_met = False
                break

        if all_conditions_met:
            condition_strs = [f"{c['sensor']} {c['operator']} {c['threshold']}" for c in condition_details]
            condition_expr = ' AND '.join(condition_strs)
            return self._create_alert(
                reading,
                DetectionType.MULTI_SENSOR,
                AlertSeverity(rule.get("severity", "warning")),
                f"Multi-sensor condition: {rule.get('name', '')} - {condition_expr}",
                {
                    "rule_name": rule.get("name"),
                    "rule_id": rule.get("id"),
                    "conditions": condition_details,
                },
            )

        return None

    def _evaluate_condition(self, value: float, operator: str, threshold: float) -> bool:
        """
        Evaluate a single scalar inequality or equality condition.

        Args:
            value (float): Left operand scalar sensor value.
            operator (str): Comparison operator symbol (e.g., '>', '<', '>=', '<=', '==', '!=').
            threshold (float): Right operand threshold constant.

        Returns:
            bool: True if condition holds, False otherwise.

        """
        if operator == ">":
            return value > threshold
        elif operator == "<":
            return value < threshold
        elif operator == ">=":
            return value >= threshold
        elif operator == "<=":
            return value <= threshold
        elif operator == "==":
            return abs(value - threshold) < 0.001
        elif operator == "!=":
            return abs(value - threshold) >= 0.001
        else:
            log.warning(f"Unknown operator: {operator}")
            return False

    def _create_alert(
        self,
        reading: SensorReading,
        detection_type: DetectionType,
        severity: AlertSeverity,
        reason: str,
        threshold_info: Dict = None,
    ) -> Optional[Alert]:
        """
        Create an alert after applying confirmation count threshold logic.

        Args:
            reading (SensorReading): Trigger reading causing detection.
            detection_type (DetectionType): Type of anomaly.
            severity (AlertSeverity): Severity classification.
            reason (str): Explanatory reason string.
            threshold_info (Dict, optional): Threshold context dictionary. Defaults to None.

        Returns:
            Optional[Alert]: Alert instance if confirmation count satisfied, else None.

        """
        import uuid

        key = (reading.customer_id, reading.turbine_id, reading.sensor_name, detection_type.value)
        tracking = self.alert_tracking[key]

        tracking["count"] += 1
        tracking["first_triggered"] = tracking.get("first_triggered") or reading.timestamp_ms
        tracking["last_triggered"] = reading.timestamp_ms

        confirmation_count = self.global_settings.get("confirmation_count", 3)
        if tracking["count"] < confirmation_count:
            log.debug(
                "Alert not yet confirmed",
                extra={
                    "sensor": reading.sensor_name,
                    "detection": detection_type.value,
                    "count": tracking["count"],
                    "required": confirmation_count,
                }
            )
            return None

        tracking["count"] = 0
        tracking["last_published"] = reading.timestamp_ms

        sensor_key = (reading.customer_id, reading.turbine_id, reading.sensor_name)
        self._enter_grace_period(sensor_key, reading.timestamp_ms)

        alert = Alert(
            alert_id=str(uuid.uuid4()),
            timestamp_ms=reading.timestamp_ms,
            customer_id=reading.customer_id,
            turbine_id=reading.turbine_id,
            device_path=reading.device_path,
            sensor=reading.sensor_name,
            value=reading.value,
            detection_type=detection_type.value,
            severity=severity.value,
            reason=reason,
            threshold_info=threshold_info,
        )

        log.warning(
            "Alert confirmed and created",
            extra={
                "alert_id": alert.alert_id,
                "sensor": reading.sensor_name,
                "severity": severity.value,
                "reason": reason[:100],
            }
        )

        return alert

    def publish_alert(self, alert: Alert) -> bool:
        """
        Publish an Alert instance to the Kafka anomaly alerts topic.

        Args:
            alert (Alert): Alert instance to serialize and publish.

        Returns:
            bool: True on successful produce dispatch, False on error.

        """
        try:
            self.producer.produce(
                topic="turbine.anomaly.alerts.v1",
                key=f"{alert.customer_id}:{alert.turbine_id}:{alert.sensor}".encode("utf-8"),
                value=alert.to_json().encode("utf-8"),
            )
            self.producer.poll(0)
            return True
        except Exception as e:
            log.error(
                "Failed to publish alert",
                extra={"alert_id": alert.alert_id, "error": str(e)}
            )
            return False


def build_consumer() -> Consumer:
    """
    Build and configure a Kafka consumer for streaming telemetry events.

    Returns:
        Consumer: Configured confluent_kafka Consumer instance.

    """
    return Consumer({
        "bootstrap.servers": Config.KAFKA_BOOTSTRAP_SERVERS,
        "group.id": "anomaly-detector-group",
        "enable.auto.commit": True,
        "auto.offset.reset": "latest",
        "isolation.level": "read_committed",
        "max.poll.interval.ms": 300000,
    })


def parse_telemetry_message(payload: dict) -> Optional[List[SensorReading]]:
    """
    Parse telemetry JSON payload into a list of normalized SensorReading instances.

    Args:
        payload (dict): Parsed JSON dictionary of incoming Kafka message.

    Returns:
        Optional[List[SensorReading]]: List of parsed SensorReading items, or None if invalid.

    """
    try:
        customer_id = payload.get("customer_id")
        turbine_id = payload.get("turbine_id")
        event_time_ms = payload.get("event_time_ms")
        seq_no = payload.get("seq_no")

        if not all([customer_id, turbine_id, event_time_ms, seq_no]):
            return None

        device_path = f"root.digitaltwin.{customer_id}.site1.{turbine_id}"
        metrics = payload.get("metrics", {})

        readings = []
        for sensor_name, value in metrics.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                readings.append(SensorReading(
                    timestamp_ms=int(event_time_ms),
                    customer_id=customer_id,
                    turbine_id=turbine_id,
                    sensor_name=sensor_name,
                    value=float(value),
                    device_path=device_path,
                    sequence_number=int(seq_no),
                ))

        return readings if readings else None
    except (KeyError, TypeError, ValueError) as e:
        return None


def run_detector() -> None:
    """
    Main anomaly detector process loop.

    Subscribes to telemetry Kafka topic, parses sensor readings, evaluates anomalies,
    and publishes alerts to Kafka while exposing health check metrics.

    """
    health = start_health_server(Config.HEALTH_CHECK_PORT + 1, "anomaly-detector")
    health.set_check("kafka_connected", False, "not yet attempted")

    consumer = build_consumer()
    detector = AnomalyDetector()

    consumer.subscribe([Config.KAFKA_TOPIC])
    health.set_check("kafka_connected", True, "subscribed")
    health.set_ready(True)

    log.info(
        "Anomaly detector started",
        extra={"topic": Config.KAFKA_TOPIC, "group": "anomaly-detector-group"}
    )

    try:
        while True:
            msg = consumer.poll(1.0)

            if msg is not None:
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        log.error("Kafka error", extra={"error": str(msg.error())})
                        health.set_check("kafka_connected", False, str(msg.error()))
                else:
                    health.set_check("kafka_connected", True, "consuming")

                    try:
                        payload = json.loads(msg.value())
                        readings = parse_telemetry_message(payload)

                        if readings:
                            for reading in readings:
                                alerts = detector.process_reading(reading)
                                for alert in alerts:
                                    detector.publish_alert(alert)

                    except json.JSONDecodeError:
                        log.debug("Could not parse message as JSON")
                    except Exception as e:
                        log.error("Error processing message", extra={"error": str(e)})

    except KeyboardInterrupt:
        log.info("Shutdown requested")
    finally:
        consumer.close()
        detector.producer.flush(10)
        log.info("Anomaly detector stopped")


if __name__ == "__main__":
    try:
        run_detector()
    except Exception:
        log.exception("Detector crashed")
        sys.exit(1)
