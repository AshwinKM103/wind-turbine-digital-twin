# Anomaly Detection & Alerting System

**Status:** Detection engine complete — 27/27 unit tests passing  
**Version:** 1.1  
**Last Updated:** 2026-09-06  
**Implementation:** [`app/src/anomaly_detection.py`](../src/anomaly_detection.py) ·
**Configuration:** [`app/config/anomaly_thresholds.json`](../config/anomaly_thresholds.json) ·
**Tests:** [`app/tests/test_anomaly_detection.py`](../tests/test_anomaly_detection.py)

All seven detection methods registered in `process_reading()` are implemented and
covered by tests. Three previously incomplete areas — turbine state inference,
percentage-based `rapid_increase` detection, and multi-sensor AND-condition
evaluation — are now functional. See [Test Coverage](#test-coverage) for the
current suite result and [Deployment](#deployment) for what still stands between
the engine and a running container.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Detection Methods](#detection-methods)
3. [Alert Types](#alert-types)
4. [Configuration](#configuration)
5. [Integration Points](#integration-points)
6. [False Positive Mitigation](#false-positive-mitigation)
7. [Multi-Customer Isolation](#multi-customer-isolation)
8. [Grafana Visualization](#grafana-visualization)
9. [Alert Routing](#alert-routing)
10. [Real-World Scenarios](#real-world-scenarios)
11. [Operational Guide](#operational-guide)
12. [Test Coverage](#test-coverage)
13. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### System Design

The anomaly detection system runs as a parallel, independent Kafka consumer that:

1. Reads telemetry data from the same Kafka topic as the IoTDB writer
2. Applies multiple detection methods in real-time
3. Publishes confirmed anomalies to a separate Kafka topic
4. Maintains state for confirmation tracking and grace periods
5. Integrates with Grafana for visualization

```
┌─────────────────────────────────────────────────────────────────┐
│ Synthetic Generators (3 processes)                              │
│ - Customer1: turbine01, turbine02                               │
│ - Customer2: turbine03, turbine04, turbine05                    │
│ - Customer3: turbine06-09                                       │
└────────────┬────────────────────────────────────────────────────┘
             │ JSON messages
             ▼
    ┌────────────────────┐
    │ Kafka Topic:       │
    │ turbine.telemetry  │
    │ .raw.v1            │
    └────┬───────────────┘
         │
         ├──────────────────────────────┬──────────────────────────┐
         │                              │                          │
         ▼                              ▼                          ▼
    ┌─────────────┐        ┌──────────────────────┐      ┌──────────────┐
    │ IoTDB       │        │ Anomaly Detection    │      │ (Optional)   │
    │ Writer      │        │ Detector             │      │ Real-time    │
    │ Consumer    │        │ (separate process)   │      │ Dashboard    │
    │             │        │                      │      │              │
    │ Group:      │        │ Group:               │      │ Pub/Sub      │
    │ iotdb-writer├─►      │ anomaly-detector     │      │ Alerts       │
    │ -group      │        │ -group               │      │              │
    │             │        │                      │      │              │
    │ Writes to:  │        │ Publishes to:        │      │ Subscribes:  │
    │ Device tree │        │ turbine.anomaly      │      │ anomaly      │
    │ in IoTDB    │        │ .alerts.v1           │      │ .alerts.v1   │
    └─────────────┘        └──────┬───────────────┘      └──────────────┘
         │                        │
         ▼                        ▼
    ┌──────────────┐       ┌────────────────────┐
    │ IoTDB REST   │       │ Kafka Topic:       │
    │ Queries      │       │ turbine.anomaly    │
    │              │       │ .alerts.v1         │
    │ Device Tree: │       │                    │
    │ root.digital │       │ Retention: 24h     │
    │ twin         │       └────┬───────────────┘
    │ .customer*   │            │
    │ .site1       │            ├─────────────────────────┐
    │ .turbine*    │            │                         │
    └──────┬───────┘            ▼                         ▼
           │              ┌─────────────────┐      ┌────────────────┐
           │              │ Grafana         │      │ Alert Channel: │
           └─►            │ Annotations     │      │ - Webhook      │
                          │ + Alerts Panel  │      │ - Slack        │
                          │ + Status Panel  │      │ - Email        │
                          │                 │      │ - PagerDuty    │
                          │ Per-customer    │      │                │
                          │ organization    │      │ External       │
                          └─────────────────┘      │ Integration    │
                                                   └────────────────┘
```

### Detection pipeline

`AnomalyDetector.process_reading()` is the single entry point. For every sensor
reading it appends to a per-`(customer, turbine, sensor)` rolling window
(`deque(maxlen=3600)`, one hour at 1 Hz), returns early if that sensor is inside
a grace period, then runs all seven detectors in order:

| # | Method | Rule key in config | Scope |
|---|---|---|---|
| 1 | `_detect_out_of_range` | `out_of_range` | Per sensor, state-aware thresholds |
| 2 | `_detect_stuck_value` | `stuck_value` | Per sensor, rolling window |
| 3 | `_detect_rapid_rise` | `rapid_rise` | Per sensor, absolute rise per minute |
| 4 | `_detect_rapid_increase` | `rapid_increase` | Per sensor, percentage vs. baseline |
| 5 | `_detect_drift` | `drift` | Per sensor, absolute drift per hour |
| 6 | `_detect_correlation_break` | `correlation_rules[].sensor_pairs` | Sensor pair divergence |
| 7 | `_check_multi_sensor_conditions` | `correlation_rules[].sensor_conditions` | N-sensor AND logic |

Each detector is called inside its own `try`/`except`. A detector that raises
logs at ERROR with its method name and the offending sensor, and the remaining
detectors still run — one malformed rule cannot silence the whole engine.

Methods 1–5 are driven by `sensors.<NAME>.anomaly_rules[]` and only fire when a
rule of the matching `type` exists **and** has `"enabled": true`. Methods 6 and 7
read the top-level `correlation_rules[]` array; a rule containing `sensor_pairs`
is routed to correlation-break handling, a rule containing `sensor_conditions` to
multi-sensor handling.

A detector returning a candidate anomaly does not immediately produce a Kafka
message. `_create_alert()` applies the confirmation count and grace period first
— see [False Positive Mitigation](#false-positive-mitigation).

### Deployment

**Option 1: Single Container** (Phase 1)
- Same container as IoTDB writer
- `anomaly_detection.py` runs as separate background process/thread
- Simpler deployment, but both processes compete for resources

**Option 2: Separate Container** (Phase 2, Recommended)
- New `Dockerfile.anomaly-detector`
- Deployed alongside consumer container
- Independent health checks and scaling
- Each container has dedicated CPU/memory

```yaml
# docker-compose.yml
services:
  # Existing consumer
  kafka-consumer:
    image: turbine/kafka-consumer:latest
    # ... existing config

  # NEW: Anomaly detector (separate process)
  anomaly-detector:
    image: turbine/anomaly-detector:latest
    depends_on:
      kafka:
        condition: service_healthy
    environment:
      KAFKA_BOOTSTRAP_SERVERS_INTERNAL: kafka:29092
      HEALTH_CHECK_PORT: 8010
      ANOMALY_DETECTOR_ENABLED: "true"
      ANOMALY_GRACE_PERIOD_MINUTES: 5
      ANOMALY_CONFIRMATION_COUNT: 3
    ports:
      - "8010:8010"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8010/health"]
      interval: 15s
      timeout: 5s
      retries: 3
    networks:
      - turbine-net
```

### Before the first deploy

The detection engine is complete and tested, but the service is not yet wired
into the stack. Two prerequisites remain:

1. **`anomaly-detector` is absent from `docker-compose.yml`.** The Compose file
   defines six services (`zookeeper`, `kafka`, `iotdb`, `grafana`, `producer`,
   `consumer`). Add the block above, and give the detector a health port distinct
   from the producer (8000) and consumer (8001) — `run_detector()` binds
   `HEALTH_CHECK_PORT + 1`, so set `HEALTH_CHECK_PORT=8009` to serve on 8010.

2. **`anomaly_detection.py` requires Python 3.12 or newer.** The alert message
   built in `_evaluate_multi_sensor_rule()` nests same-quoted subscripts inside an
   f-string, which only parses under [PEP 701](https://peps.python.org/pep-0701/):

   ```python
   f"{' AND '.join(f'{c['sensor']} {c['operator']} {c['threshold']}' for c in condition_details)}"
   ```

   `app/Dockerfile` builds `FROM python:3.11-slim`, where this is a
   `SyntaxError: f-string: unmatched '['` at import time. Either bump the base
   image to `python:3.12-slim` or rewrite that expression with an intermediate
   variable before building a detector image.

Verify the interpreter constraint before building:

```bash
python3 -c "import sys; assert sys.version_info >= (3, 12), sys.version"
python3 -m py_compile app/src/anomaly_detection.py && echo "detector compiles"
```

---

## Detection Methods

### 0. Turbine State Inference

Out-of-range detection is state-aware, so every threshold lookup depends on the
state inferred by `_infer_turbine_state()`. It reads the most recent
`TURBINE_SPEED_RPM` value for the same `(customer, turbine)` and maps it:

| Inferred state | RPM condition | Meaning |
|---|---|---|
| `IDLE` | `rpm < 500` | At rest or freewheeling |
| `RAMP_UP` | `500 <= rpm < 11000` | Accelerating, including the 2000–11000 transition band |
| `STEADY_STATE` | `11000 <= rpm <= 12500` | At rated speed |
| `RAMP_DOWN` | `rpm > 12500` | Overspeed / decelerating from above rated |

If no `TURBINE_SPEED_RPM` reading has been seen yet for that turbine, the state
defaults to `STEADY_STATE`, which is the most conservative choice: its bands are
the tightest of the four, so an unknown-state turbine is judged strictly rather
than leniently.

The ordering matters and is easy to get wrong. `RAMP_DOWN` is tested before the
`STEADY_STATE` band so that an overspeed reading at 13000 RPM is never
misclassified as steady; the residual 2000–11000 range falls through to
`RAMP_UP` rather than to a default. `TURBINE_SPEED_RPM` itself is evaluated
against the thresholds of the state it just implied, which is intentional —
12800 RPM implies `RAMP_DOWN`, and `RAMP_DOWN` caps `critical_max` at 12500, so
the overspeed still alerts.

`GB_TRQ` (torque) is read alongside RPM for future use but does not currently
influence the result.

### 1. Out-of-Range Detection (Statistical)

Checks if sensor value exceeds configured thresholds.

**State-Aware:** Thresholds vary by turbine operational state. Bands for
`TT_109A` (Gearbox Bearing A Temperature) as configured today:

```
State          critical_min   warning_min   warning_max   critical_max
──────────────────────────────────────────────────────────────────────
IDLE               35.0          45.0          65.0          75.0
RAMP_UP            45.0          55.0          90.0         100.0
STEADY_STATE       65.0          75.0          85.0          95.0
RAMP_DOWN          45.0          55.0          75.0          85.0
```

**Algorithm:**
1. Infer current turbine state from RPM/torque readings
2. Look up state-specific thresholds for sensor
3. Check: `critical_min <= value <= critical_max`
4. If violated, create alert with severity=CRITICAL
5. If warning range violated, severity=WARNING

**Example Alert:**
```json
{
  "sensor": "TT_109A",
  "value": 96.5,
  "reason": "Gearbox Bearing A Temp = 96.5°C above critical max 95°C (state: STEADY_STATE)",
  "severity": "critical",
  "threshold_info": {
    "critical_max": 95.0,
    "state": "STEADY_STATE"
  }
}
```

**Configuration in `anomaly_thresholds.json`:**
```json
{
  "TT_109A": {
    "thresholds": {
      "STEADY_STATE": {
        "critical_min": 65.0,
        "critical_max": 95.0,
        "warning_min": 75.0,
        "warning_max": 85.0
      }
    },
    "anomaly_rules": [{
      "type": "out_of_range",
      "enabled": true,
      "severity": "critical"
    }]
  }
}
```

### 2. Stuck Value Detection (Temporal)

Detects when a sensor reading doesn't change for an extended period.

**Indicators:** Sensor failure, mechanical lock, connection loss

**Algorithm:**
1. Take every reading in the window `[now - stuck_duration_seconds, now]`
2. Count those within 0.001 of the current value
3. If that count exceeds `stuck_duration_seconds × 0.8`, flag as stuck

The 80% margin means the check tolerates a fifth of the expected samples being
missing — dropped Kafka messages or a brief producer stall will not by
themselves clear a genuine stuck-sensor condition. It also means the window must
actually be full: at 1 Hz, a 600-second rule needs more than 480 matching
samples, so the detector stays silent for the first eight minutes after startup.

**Example:** RPM stuck at 12000 RPM for 10 minutes (`stuck_duration_seconds: 600`)
during STEADY_STATE operation.

```json
{
  "sensor": "TURBINE_SPEED_RPM",
  "value": 12000.0,
  "reason": "RPM stuck at 12000.0 for 600s (possible sensor failure)",
  "severity": "critical",
  "threshold_info": {
    "stuck_duration_s": 600,
    "stuck_value": 12000.0
  }
}
```

### 3. Rapid Rise Detection (Temporal, Absolute)

Detects rapid **absolute** increases in temperature or pressure.

**Indicators:** Bearing overheating, pressure surge, system stress

**Algorithm:**
1. Take the oldest reading still inside the `duration_minutes` window
2. Compute `rise = current_value - oldest_value`
3. If `rise > rise_threshold_per_minute × duration_minutes`, flag as rapid rise

The comparison is a total over the window, not a per-sample slope, so a sensor
that jumps and then plateaus still trips the rule for as long as the jump stays
inside the window. The rule is one-directional: a rapid *fall* produces a
negative `rise` and never alerts. Use `out_of_range` `critical_min` to catch
collapses.

**Configuration** (`TT_109A`, as shipped):

```json
{
  "type": "rapid_rise",
  "enabled": true,
  "severity": "critical",
  "rise_threshold_per_minute": 2.0,
  "duration_minutes": 5,
  "description": "Temperature rising >2°C/min for 5 min (bearing distress)"
}
```

**Example:** Gearbox bearing temperature rises 22°C across the 5-minute window,
against a budget of `2.0 × 5 = 10°C`.

```json
{
  "sensor": "TT_109A",
  "value": 92.0,
  "reason": "TT_109A rose 22.00 in 5 min (threshold: 2.00/min)",
  "severity": "critical",
  "threshold_info": {
    "rise_total": 22.0,
    "rise_per_minute": 4.4,
    "threshold_per_minute": 2.0,
    "old_value": 70.0,
    "current_value": 92.0
  }
}
```

Severity is hardcoded to `CRITICAL` for this rule; the `severity` field in the
config block is documentation only and is not read by `_detect_rapid_rise()`.

### 4. Rapid Increase Detection (Temporal, Percentage)

Detects a sensor rising sharply **relative to its own recent baseline**, rather
than against a fixed limit.

**Indicators:** Early-stage bearing wear, rotor imbalance, loosening mounts —
faults that raise vibration well before it reaches an absolute alarm level.

This is the companion to `rapid_rise`, and the distinction is the point. A
gearbox that normally vibrates at 2.3 mm/s and climbs to 3.5 mm/s is still
inside its `STEADY_STATE` warning band (1.5–4.5 mm/s), so `out_of_range` stays
quiet. In absolute terms the change is 1.2 mm/s, far too small for a
temperature-tuned `rapid_rise` budget. In relative terms it is a 52% jump in ten
minutes, which for a rotating machine is the signal.

**Algorithm:**
1. Collect every reading in the window `[now - baseline_window_minutes, now]`
2. `baseline = mean(window)`
3. `increase_percent = (current - baseline) / baseline × 100`
4. If `increase_percent > increase_threshold_percent`, flag as rapid increase

`process_reading()` appends the reading to history *before* running detectors, so
the current value is one of the samples in its own baseline. With a full 10-minute
window at 1 Hz the effect is small — a 2.30 baseline reads as 2.31 once a 3.50
sample lands in it, pulling a nominal 52.2% down to the 51.7% actually reported —
but on a short or sparse window it is not negligible. Expect the reported
percentage to sit slightly below hand-calculated arithmetic.

The same property makes the metric self-damping over time: a sustained elevation
drags the baseline up and the percentage back down, so the rule fires on the
transition rather than repeating forever at a new plateau.

**Zero-baseline handling.** If the window average is exactly `0`, the percentage
is undefined. The detector reports a fixed 100% increase when the current value
exceeds `0.1`, and otherwise reports 0%. That guard keeps a sensor waking up
from a hard zero from producing either a division error or an alert storm from
float noise around zero.

**Configuration** (`XT_600`, Gearbox Vibration X, as shipped):

```json
{
  "type": "rapid_increase",
  "enabled": true,
  "severity": "critical",
  "increase_threshold_percent": 50,
  "baseline_window_minutes": 10,
  "description": "Vibration increased >50% vs 10-min baseline (bearing wear?)"
}
```

Unlike `rapid_rise`, this rule **does** honour the `severity` field: the value is
passed to `AlertSeverity(...)`, so it must be one of `info`, `warning`, or
`critical`. Any other string raises `ValueError`, which the per-detector
`try`/`except` catches and logs — the rule then silently never fires. Check the
detector log for `Detection method failed` after editing severity.

**Defaults** when a key is omitted: `increase_threshold_percent: 50`,
`baseline_window_minutes: 10`, `severity: "critical"`.

**Example Alert:**

```json
{
  "sensor": "XT_600",
  "value": 3.5,
  "detection_type": "rapid_increase",
  "severity": "critical",
  "reason": "XT_600 increased 51.7% (baseline 10min avg: 2.31, current: 3.50, threshold: 50%)",
  "threshold_info": {
    "increase_percent": 51.71,
    "baseline_value": 2.3071,
    "current_value": 3.5,
    "threshold_percent": 50,
    "baseline_window_minutes": 10
  }
}
```

**Enabling it on another sensor.** Add the rule block to that sensor's
`anomaly_rules` array. Percentage thresholds suit sensors whose normal value is
comfortably above zero and whose failure mode is multiplicative — vibration,
flow, current draw. They suit absolute-scale sensors poorly: a 50% rise on a
temperature reading in °C means something entirely different at 20°C than at
80°C, so prefer `rapid_rise` there.

### 5. Drift Detection (Temporal)

Detects slow sensor drift over time (calibration issue or gradual system change).

**Indicators:** Sensor degradation, bearing wear, system performance shift

**Algorithm:**
1. Require at least 60 readings and at least 10 minutes of elapsed history
2. Compare the oldest and newest readings held in the window (1 hour at 1 Hz)
3. `drift = abs(newest - oldest)`, compared against
   `drift_threshold_per_hour × elapsed_hours × 1.5`

The 1.5 multiplier is deliberate headroom — drift is the slowest-moving signal
here and the least urgent, so the rule only speaks when the trend is half again
past its budget. Note that `drift` uses `abs()`, so unlike `rapid_rise` it
catches movement in both directions.

**Example:** Pressure sensor drifts from 32.0 bar to 33.0 bar over 1 hour (threshold: 0.5 bar/h).

```json
{
  "sensor": "PT_109A",
  "value": 33.0,
  "reason": "Pressure drifted 1.0 bar over 1.0h (1.0 bar/h, threshold: 0.5 bar/h)",
  "severity": "warning",
  "threshold_info": {
    "drift_total": 1.0,
    "drift_per_hour": 1.0,
    "threshold_per_hour": 0.5,
    "old_value": 32.0,
    "current_value": 33.0
  }
}
```

### 6. Correlation-Based Detection (Multi-Sensor)

Detects when two sensors that normally correlate diverge.

Correlation rules live in the top-level `correlation_rules[]` array, not under an
individual sensor. Every rule needs `"enabled": true`; the shape of the rule
decides which detector claims it:

| Rule contains | Handled by | Logic |
|---|---|---|
| `sensor_pairs` + `correlation_type: "should_track"` | `_detect_correlation_break` | Absolute divergence between two sensors |
| `sensor_pairs` + `correlation_type: "should_correlate"` | *not implemented* | Rule is loaded and ignored |
| `sensor_conditions` | `_check_multi_sensor_conditions` | AND across N conditions |

**Rule Types:**

#### a) `should_track`
Two sensors should move together within tolerance.

**Example:** Gearbox bearing A and B temperatures should stay within 5°C.

```json
{
  "id": "gearbox_bearing_temp_corr",
  "correlation_type": "should_track",
  "sensor_pairs": ["TT_109A", "TT_110A"],
  "max_divergence": 5.0,
  "alert": {
    "sensor": "TT_109A",
    "value": 85.0,
    "reason": "TT_109A (85.0°C) and TT_110A (70.0°C) diverged by 15.0°C (max: 5.0°C)",
    "severity": "warning"
  }
}
```

**Interpretation:** If bearing B is much cooler than bearing A, bearing A might be failing.

The rule is symmetric and evaluated on whichever of the two sensors arrives:
`_check_tracking_correlation()` looks up the other sensor's most recent value and
compares absolute difference against `max_divergence`. If the other sensor has no
history yet, the rule is skipped rather than treated as divergent.

#### b) `should_correlate`
Reserved. `correlation_type: "should_correlate"` is defined in the shipped config
for the `pressure_temp_divergence` rule, but `_detect_correlation_break()` only
dispatches on `should_track`. The rule loads without error and never fires.
Statistical correlation over a window is Phase 3 work — do not rely on it for
coverage today.

#### c) Multi-Sensor Conditions

Fires only when **every** condition in the rule is true at the same instant. This
catches compound failure signatures that no single sensor can express: a hot
gearbox alone might be a warm day, and elevated vibration alone might be a gust,
but both together in a bearing is a fault.

**Evaluation.** `_check_multi_sensor_conditions()` collects all
`correlation_rules[]` entries that carry a `sensor_conditions` array and are
enabled, then hands each to `_evaluate_multi_sensor_rule()`, which:

1. Iterates the conditions in declared order
2. Reads the **latest** value for each named sensor from its rolling window
3. Evaluates `value <operator> threshold` via `_evaluate_condition()`
4. Short-circuits on the first condition that is false or has no history

Because evaluation short-circuits, `condition_details` in the alert payload
contains only the conditions checked up to and including the failure. On a firing
alert every condition is present. Put the cheapest or most selective condition
first — it is checked first and ends the evaluation soonest.

**Supported operators**, from `_evaluate_condition()`:

| Operator | Semantics |
|---|---|
| `>` `<` `>=` `<=` | Direct numeric comparison |
| `==` | True when `abs(value - threshold) < 0.001` |
| `!=` | True when `abs(value - threshold) >= 0.001` |

Equality uses a 0.001 tolerance because sensor values are floats and exact
equality would effectively never hold. An unrecognised operator logs a warning
and evaluates to false, which fails the rule closed rather than firing spuriously.

**Missing data fails closed.** If any named sensor has no reading in history, the
rule does not fire. A multi-sensor rule is therefore only as live as its least
frequently reported sensor.

**Example:** Gearbox Health Rule, as shipped in `anomaly_thresholds.json`:

```json
{
  "id": "gearbox_health_multi",
  "name": "Gearbox Health (Multi-Sensor)",
  "description": "If TT_109A > 85°C AND XT_600 > 4.0 mm/s, gearbox is stressed (potential bearing degradation)",
  "sensor_conditions": [
    {"sensor": "TT_109A", "operator": ">", "threshold": 85.0, "duration_seconds": 300},
    {"sensor": "XT_600", "operator": ">", "threshold": 4.0, "duration_seconds": 300}
  ],
  "enabled": true,
  "severity": "warning"
}
```

> `duration_seconds` is accepted in the config but not yet enforced —
> `_evaluate_multi_sensor_rule()` compares instantaneous latest values. Sustained
> duration is approximated today by the global `confirmation_count`, which
> requires the condition to hold across three consecutive readings. Treat
> `duration_seconds` as declared intent, not active behaviour.

**Alert.** The alert is attributed to the sensor whose reading triggered
evaluation — the one that arrived last, not the rule name — so the same rule can
surface under `TT_109A` or `XT_600` depending on message ordering. Correlate on
`threshold_info.rule_id` rather than on `sensor` when grouping these downstream.

```json
{
  "sensor": "XT_600",
  "value": 4.5,
  "detection_type": "multi_sensor",
  "severity": "warning",
  "reason": "Multi-sensor condition: Gearbox Health (Multi-Sensor) - TT_109A > 85.0 AND XT_600 > 4.0",
  "threshold_info": {
    "rule_name": "Gearbox Health (Multi-Sensor)",
    "rule_id": "gearbox_health_multi",
    "conditions": [
      {"sensor": "TT_109A", "value": 87.5, "operator": ">", "threshold": 85.0, "met": true},
      {"sensor": "XT_600", "value": 4.5, "operator": ">", "threshold": 4.0, "met": true}
    ]
  }
}
```

**Adding a rule.** Append to `correlation_rules[]` and restart the detector.
Conditions may name any number of sensors and mix operators — the logic is a
plain AND across the array. There is no OR; express alternatives as two rules
with distinct `id` values.

```json
{
  "id": "generator_overload_multi",
  "name": "Generator Overload (Multi-Sensor)",
  "description": "High torque at low speed indicates the generator is loading against a stalling rotor",
  "sensor_conditions": [
    {"sensor": "GB_TRQ", "operator": ">", "threshold": 7.5},
    {"sensor": "TURBINE_SPEED_RPM", "operator": "<", "threshold": 11000.0}
  ],
  "enabled": true,
  "severity": "critical"
}
```

---

## Alert Types

The `detection_type` field on every alert takes one of these values. It is the
stable key to route or filter on downstream — `reason` is human-readable prose
and its wording will change.

| `detection_type` | Severity | Typical Cause | Action |
|---|---|---|---|
| `out_of_range` | 🔴 CRITICAL / 🟡 WARNING | Sensor outside the band for its inferred state | Critical: investigate immediately, consider shutdown. Warning: monitor the trend |
| `stuck_value` | 🔴 CRITICAL | Value unchanged for `stuck_duration_seconds` (600 s for RPM) | Check wiring, then replace the sensor |
| `rapid_rise` | 🔴 CRITICAL | Absolute rise past `threshold × window` (2°C/min over 5 min for `TT_109A`) | Stop the turbine — bearing failure risk |
| `rapid_increase` | 🔴 CRITICAL | Percentage jump vs. rolling baseline (>50% over 10 min for `XT_600`) | Inspect for early bearing wear or imbalance before it reaches an absolute limit |
| `drift` | 🟡 WARNING | Slow one-directional movement past 1.5× the hourly budget | Schedule sensor recalibration |
| `correlation_break` | 🟡 WARNING (rule-configured) | Paired sensors that should track diverge past `max_divergence` | Determine which of the two is wrong |
| `multi_sensor` | 🟡 WARNING (rule-configured) | Every condition in a compound rule true at once | Investigate the compound root cause (bearing wear, overload) |
| `state_anomaly` | — | Reserved. Defined in `DetectionType` but not emitted by any detector | None |

Severity is fixed in code for `out_of_range`, `stuck_value`, `rapid_rise`, and
`drift`. Only `rapid_increase`, `correlation_break`, and `multi_sensor` read
`severity` from their config block.

---

## Configuration

### Threshold Configuration File

**Location:** `app/config/anomaly_thresholds.json`

**Structure:**

```json
{
  "metadata": {
    "version": "1.0",
    "description": "Anomaly detection thresholds",
    "last_updated": "2026-09-06"
  },
  "global_settings": {
    "enable_anomaly_detection": true,
    "grace_period_minutes": 5,
    "confirmation_count": 3,
    "drift_window_minutes": 60
  },
  "sensors": {
    "SENSOR_NAME": {
      "name": "Human-readable name",
      "unit": "°C",
      "category": "temperature",
      "thresholds": {
        "IDLE": {
          "critical_min": 35.0,
          "critical_max": 75.0,
          "warning_min": 40.0,
          "warning_max": 70.0
        },
        "RAMP_UP": { ... },
        "STEADY_STATE": { ... },
        "RAMP_DOWN": { ... }
      },
      "anomaly_rules": [
        {
          "type": "out_of_range",
          "enabled": true,
          "severity": "critical"
        }
      ]
    }
  },
  "correlation_rules": [ ... ],
  "state_definitions": { ... },
  "alert_routing": { ... }
}
```

The eight sensors configured today are `PT_109A`, `PT_110A`, `TT_109A`,
`TT_110A`, `TURBINE_SPEED_RPM`, `GB_TRQ`, `XT_600`, and `XT_601`. A sensor with
no entry under `sensors` is stored in history — so it remains available to
correlation and multi-sensor rules — but produces no per-sensor alerts of its own.

### Enabling each detection method

Every per-sensor method is off unless a rule of its `type` exists with
`"enabled": true`. Setting `"enabled": false` is the supported way to silence one
method without losing its tuned thresholds.

| Method | Where it goes | Required keys | Optional keys (default) |
|---|---|---|---|
| `out_of_range` | `sensors.<NAME>.anomaly_rules[]` | `type`, `enabled` | Reads limits from `thresholds.<STATE>` |
| `stuck_value` | `sensors.<NAME>.anomaly_rules[]` | `type`, `enabled` | `stuck_duration_seconds` (600) |
| `rapid_rise` | `sensors.<NAME>.anomaly_rules[]` | `type`, `enabled` | `rise_threshold_per_minute` (2.0), `duration_minutes` (5) |
| `rapid_increase` | `sensors.<NAME>.anomaly_rules[]` | `type`, `enabled` | `increase_threshold_percent` (50), `baseline_window_minutes` (10), `severity` (`critical`) |
| `drift` | `sensors.<NAME>.anomaly_rules[]` | `type`, `enabled` | `drift_threshold_per_hour` (0.5) |
| `correlation_break` | `correlation_rules[]` | `sensor_pairs`, `correlation_type: "should_track"`, `enabled` | `max_divergence` (5.0), `severity` (`warning`) |
| `multi_sensor` | `correlation_rules[]` | `sensor_conditions`, `enabled` | `severity` (`warning`), `id`, `name` |

A complete sensor entry with three methods enabled — absolute limits, a
percentage-based early warning, and a stuck-sensor check:

```json
{
  "XT_601": {
    "name": "Gearbox Vibration Y",
    "unit": "mm/s",
    "category": "vibration",
    "data_type": "float",
    "thresholds": {
      "STEADY_STATE": {
        "critical_min": 0.8,
        "warning_min": 1.5,
        "warning_max": 4.5,
        "critical_max": 6.0
      }
    },
    "anomaly_rules": [
      {
        "type": "out_of_range",
        "enabled": true,
        "severity": "warning"
      },
      {
        "type": "rapid_increase",
        "enabled": true,
        "severity": "critical",
        "increase_threshold_percent": 50,
        "baseline_window_minutes": 10
      },
      {
        "type": "stuck_value",
        "enabled": true,
        "stuck_duration_seconds": 600
      }
    ]
  }
}
```

Thresholds must be defined for each of `IDLE`, `RAMP_UP`, `STEADY_STATE`, and
`RAMP_DOWN`. A state with no threshold block causes `_detect_out_of_range()` to
return without checking — the sensor is unmonitored while the turbine is in that
state, silently. Validate after every edit:

```bash
python3 -c "
import json
c = json.load(open('app/config/anomaly_thresholds.json'))
states = {'IDLE', 'RAMP_UP', 'STEADY_STATE', 'RAMP_DOWN'}
for name, spec in c['sensors'].items():
    missing = states - set(spec.get('thresholds', {}))
    if missing:
        print(f'{name}: missing thresholds for {sorted(missing)}')
print('checked', len(c['sensors']), 'sensors')
"
```

### Per-Customer Overrides (Phase 2)

Future enhancement: Allow per-customer threshold adjustments.

```json
{
  "customer_overrides": {
    "customer1": {
      "sensors": {
        "PT_109A": {
          "thresholds": {
            "STEADY_STATE": {
              "critical_max": 35.0
            }
          }
        }
      }
    }
  }
}
```

---

## Integration Points

### 1. Kafka Topics

**Input Topic:** `turbine.telemetry.raw.v1`
- Same as IoTDB consumer
- Partition by customer:turbine key
- Retention: 24 hours

**Output Topic:** `turbine.anomaly.alerts.v1` (NEW)
- Anomaly alerts only
- Partition by customer:turbine:sensor
- Retention: 24 hours (keep for audit trail)
- Format: JSON (Alert payload)

**Example Alert Message:**
```json
{
  "alert_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp_ms": 1725523200000,
  "customer_id": "customer1",
  "turbine_id": "turbine01",
  "device_path": "root.digitaltwin.customer1.site1.turbine01",
  "sensor": "TT_109A",
  "value": 96.5,
  "detection_type": "out_of_range",
  "severity": "critical",
  "reason": "Gearbox Bearing A Temp = 96.5°C above critical max 95°C",
  "threshold_info": {
    "critical_max": 95.0,
    "state": "STEADY_STATE"
  },
  "additional_context": null
}
```

### 2. Consumer Enhancement

The existing `kafka_consumer.py` can optionally be enhanced to:
1. Parse alerts from `turbine.anomaly.alerts.v1`
2. Store anomaly flags in IoTDB (optional metadata field)
3. Track alert history

**Optional:** Create `anomaly_flags` field in IoTDB device.

```
root.digitaltwin.customer1.site1.turbine01.anomaly_flags = {
  "last_alert_time": 1725523200000,
  "last_alert_sensor": "TT_109A",
  "last_alert_severity": "critical",
  "active_alert_count": 2
}
```

### 3. IoTDB Integration

Two options:

#### Option A: Anomalies in Separate Devices (Recommended)
Store anomalies in a parallel device tree.

```
root.digitaltwin.customer1.site1.turbine01.anomalies
  └── TT_109A_alerts (timestamp, value=1 if alert, 0 if not)
  └── TT_109A_severity (timestamp, value=0|1|2 = INFO|WARNING|CRITICAL)
  └── TT_109A_reason (timestamp, string)
```

**Pros:**
- Clean separation from telemetry
- Easier to query "give me all alerts for turbine01"
- Better indexing

**Cons:**
- Requires schema creation
- Extra writes to IoTDB

#### Option B: Anomalies in Kafka Only
Keep anomalies in Kafka, don't persist to IoTDB.

**Pros:**
- Simpler deployment
- No schema changes
- Lower disk usage

**Cons:**
- Anomalies lost after 24-hour Kafka retention
- Harder to query historical alerts

### 4. Grafana Integration

#### Anomaly Annotations
Display alerts as vertical annotations on timeseries panels.

```javascript
// Panel configuration
{
  "datasource": "Prometheus",
  "targets": [
    {
      "expr": "last_value(turbine_temp_c)",
      "legendFormat": "Gearbox Temp"
    }
  ],
  "annotations": [
    {
      "datasource": "Grafana",
      "name": "Anomaly Alerts",
      "tags": ["customer1", "turbine01"],
      "tagsValues": ["critical", "warning"],
      "textFormat": "{{ sensor }}: {{ reason }}"
    }
  ]
}
```

#### Alert Panel
Display active alerts in tabular format.

```javascript
{
  "type": "table",
  "title": "Active Anomalies",
  "targets": [
    {
      "datasource": "Kafka",
      "topic": "turbine.anomaly.alerts.v1",
      "query": "customer_id = 'customer1' AND turbine_id IN ('turbine01', 'turbine02')",
      "columns": ["timestamp_ms", "sensor", "value", "severity", "reason"]
    }
  ]
}
```

#### Status Panel
Show summary of active alerts.

```
Customer1 Status:
  🔴 CRITICAL: 1 (TT_109A out of range)
  🟡 WARNING: 2 (PT_109A drift, XT_600 vibration)
  🟢 INFO: 0
  ✅ HEALTHY
```

---

## False Positive Mitigation

### Strategy 1: Grace Periods

After an alert fires, suppress duplicate alerts for N minutes.

```
Time  Event                           Alert?  Reason
───────────────────────────────────────────────────────────
 0s   Temp = 95°C (above max)        Queued  Confirmation count = 1
 1s   Temp = 96°C (still above)      Queued  Confirmation count = 2
 2s   Temp = 97°C (still above)      ✓ YES   Confirmation count = 3 → ALERT
 3s   Temp = 98°C (still above)      ✗ NO    In grace period (300s)
 4s   Temp = 96°C (still above)      ✗ NO    In grace period
...
305s  Temp = 95°C (still above)      ✓ YES   Grace period expired → ALERT
```

**Configuration:**
```json
{
  "global_settings": {
    "grace_period_minutes": 5,
    "confirmation_count": 3
  }
}
```

### Strategy 2: Confirmation Counts

Require N detections before publishing. `confirmation_count` is a single global
value (3 by default) applied to every severity — there is no per-severity
override in the current implementation.

The counter is keyed on `(customer, turbine, sensor, detection_type)`, so a
temperature sensor tripping both `rapid_rise` and `out_of_range` accumulates two
independent counts. The grace period that follows is keyed on
`(customer, turbine, sensor)` only, without the detection type. The consequence
is worth knowing: **the first confirmed alert on a sensor suppresses every other
detection type on that same sensor for the grace period.** A `rapid_rise` that
confirms at second 3 will mask an `out_of_range` on the same sensor until the
grace window expires.

Design accordingly. If two detection types on one sensor must both reach
operators, either give them separate grace handling downstream or accept that the
earlier-confirming type wins.

Counts reset to zero once an alert is published, so the next alert on that
`(sensor, detection_type)` pair starts confirming from scratch.

### Strategy 3: State-Aware Thresholds

Different thresholds for different turbine states.

**Normal:** Temp rises during RAMP_UP, stable during STEADY.
**Wrong:** Using STEADY thresholds during RAMP_UP → false positive.

**Solution:** Auto-adjust thresholds based on inferred state.

This applies to `out_of_range` only. `rapid_rise`, `rapid_increase`, `drift`, and
`stuck_value` use a single threshold regardless of turbine state, so a genuine
ramp can trip them. Where that produces noise, raise the rule's threshold rather
than expecting state awareness to absorb it.

### Strategy 4: Moving Average / Smoothing

(Future enhancement)

Apply exponential moving average (EMA) to noisy sensors before checking thresholds.

```python
ema_value = 0.7 * old_ema + 0.3 * current_value
if ema_value > threshold:
    alert()
```

### Strategy 5: Baseline Learning

(Future enhancement)

Learn normal operating ranges per turbine, customer, or time-of-day.

```
Normal range (learned from first week):
  TT_109A: 70-90°C (±5°C confidence)

Today: TT_109A = 92°C
  Deviation from baseline: +2°C
  Alert? Yes, if +5°C confidence exceeded
```

---

## Multi-Customer Isolation

### Principle: No Cross-Contamination

Anomalies for Customer1 turbines should NOT:
- Affect Customer2 thresholds
- Trigger Customer2 alerts
- Appear in Customer2 Grafana dashboard

### Implementation

#### 1. Alert Routing by Customer

Each alert includes `customer_id`.

```json
{
  "customer_id": "customer1",
  "turbine_id": "turbine01",
  ...
}
```

#### 2. Per-Customer Alert Channels

Route alerts to customer-specific endpoints.

```json
{
  "alert_routing": {
    "critical": {
      "channels": ["kafka", "webhook"],
      "webhook_url_env": "ANOMALY_WEBHOOK_URL_CRITICAL",
      "customer_urls": {
        "customer1": "https://customer1-monitoring.example.com/webhook",
        "customer2": "https://customer2-monitoring.example.com/webhook"
      }
    }
  }
}
```

#### 3. Grafana Organization Isolation

Each customer has separate Grafana organization with:
- Separate datasource (scoped to that customer)
- Separate dashboards
- Separate alert rules
- Separate users

```yaml
# provisioning/grafana/provisioning/datasources/iotdb.yml
datasources:
  - name: IoTDB - Customer1
    uid: iotdb-customer1
    orgId: 2  # Customer1 org
    url: http://iotdb:18080
    jsonData:
      customerFilter: "customer1"  # Custom plugin support

  - name: IoTDB - Customer2
    uid: iotdb-customer2
    orgId: 3  # Customer2 org
    url: http://iotdb:18080
    jsonData:
      customerFilter: "customer2"
```

#### 4. Kafka Partitioning

Alerts partitioned by customer:turbine:sensor.

```
Partition 0: customer1:turbine01:*
Partition 1: customer1:turbine02:*
Partition 2: customer2:turbine03:*
...
```

Each customer's alerting system reads only their partitions.

---

## Grafana Visualization

### Dashboard: Anomaly Summary (Admin Only)

**Path:** `Grafana > Dashboards > System > Anomaly Summary`

Shows:
- Total alerts per customer (CRITICAL, WARNING, INFO)
- Trend of alert frequency (last 24h)
- Top 10 most frequent sensors with anomalies
- Mean time between alerts (MTBA)

### Dashboard: Customer1 Anomalies

**Path:** `Grafana > Customer1 Org > Dashboards > Anomalies`

Shows:
- Timeline of recent alerts (last 24h)
- Active alerts table
- Affected sensors
- Severity distribution

### Panel: Anomaly Annotations on Timeseries

```
Temperature (°C)
┌────────────────────────────────────────────────────────────┐
│  100                    ▲ WARNING                           │
│  095          ▲ CRITICAL│                                   │
│  090  ┌──────╱│╲────────────────┐                          │
│  085  │     ╱  │ ╲             │                           │
│  080──┼────╱   │  ╲────────────┼──────                     │
│  075  │       │                │                           │
│  070  └───────────────────────┘                            │
│  065                                                        │
│  060                                                        │
└────────────────────────────────────────────────────────────┘
  Time: 2026-09-06 12:00 → 20:00
  
Alert Events:
  🔴 15:30 - Out of range (95°C > 95°C max)
  🟡 16:15 - Rapid rise (+10°C in 3 min)
```

### Panel: Alert Status Gauge

```
Customer1 Fleet Status

    🟢 HEALTHY (2 turbines)
  ┌────────────────────────────┐
  │ turbine01: ✓ OK            │
  │ turbine02: ✓ OK            │
  └────────────────────────────┘

    🟡 WARNING (1 turbine)
  ┌────────────────────────────┐
  │ turbine03: ⚠ Temp drift    │
  │           PT_109A drifting │
  └────────────────────────────┘

    🔴 CRITICAL (0 turbines)

  Overall: 86% healthy
```

---

## Alert Routing

### Kafka → External Systems

Alerts published to `turbine.anomaly.alerts.v1` can be consumed by:

#### 1. Webhook Integration

```json
{
  "alert_routing": {
    "critical": {
      "channels": ["webhook"],
      "webhook_url_env": "ANOMALY_WEBHOOK_URL_CRITICAL",
      "timeout_seconds": 10,
      "retry_count": 3
    }
  }
}
```

**Example Webhook Payload:**
```json
POST https://customer1-monitoring.example.com/turbine-alerts

{
  "alert_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp_ms": 1725523200000,
  "customer_id": "customer1",
  "turbine_id": "turbine01",
  "sensor": "TT_109A",
  "value": 96.5,
  "severity": "critical",
  "reason": "Gearbox Bearing A Temp = 96.5°C above critical max 95°C"
}
```

#### 2. Slack Integration

```python
# In alert publishing logic
if alert.severity == AlertSeverity.CRITICAL:
    slack_message = f"""
    🔴 CRITICAL ALERT
    
    **Turbine:** {alert.customer_id} / {alert.turbine_id}
    **Sensor:** {alert.sensor}
    **Value:** {alert.value}
    **Reason:** {alert.reason}
    **Time:** {datetime.fromtimestamp(alert.timestamp_ms / 1000)}
    """
    slack_client.send_message(alert.customer_id, slack_message)
```

#### 3. Email Integration

```python
if alert.severity == AlertSeverity.CRITICAL:
    email_client.send_email(
        to=[f"{alert.customer_id}-alerts@example.com"],
        subject=f"🔴 CRITICAL: {alert.sensor} anomaly on {alert.turbine_id}",
        body=f"... {alert.reason} ..."
    )
```

#### 4. PagerDuty Integration

```python
if alert.severity == AlertSeverity.CRITICAL:
    pagerduty_client.trigger_incident(
        service_id=CUSTOMER_PAGERDUTY_SERVICE_MAP[alert.customer_id],
        title=f"Turbine {alert.turbine_id} critical anomaly: {alert.sensor}",
        description=alert.reason,
        urgency="high"
    )
```

---

## Real-World Scenarios

### Scenario 1: Bearing Overheating (Early Warning)

**Symptoms:**
- TT_109A (Gearbox Bearing A) temperature starts rising gradually
- XT_600 (Gearbox vibration X) increases

**Alert Sequence:**

Turbine in `STEADY_STATE` (RPM ≈ 12000). `TT_109A` warning band 75–85°C,
critical max 95°C. `rapid_rise` budget: 2.0°C/min × 5 min = 10°C per window.

```
T=0min    TT_109A = 75°C (normal, mid-band)
T=5min    TT_109A = 78°C (rising slowly, 3°C per 5-min window — under budget)
T=10min   TT_109A = 81°C (3°C per window — still under budget)
T=15min   TT_109A = 84°C

T=20min   TT_109A = 87°C — above warning_max 85.0
          🟡 out_of_range candidate, confirmation count 1/3
          rapid_rise still quiet: 3°C over the window vs 10°C budget

T=20:01   TT_109A = 87.4°C   confirmation count 2/3
T=20:02   TT_109A = 87.9°C   confirmation count 3/3
          🟡 WARNING published to Kafka
          Reason: "TT_109A = 87.90 °C above warning max 85.0 (state: STEADY_STATE)"
          Grace period opens on TT_109A for 5 minutes

T=22min   TT_109A = 91°C + XT_600 = 4.2 mm/s
          Grace period active — no TT_109A alert of any detection type.
          The multi-sensor rule evaluates true but is attributed to whichever
          sensor arrives last; if that is XT_600 it publishes, since XT_600
          has its own grace state.

T=25min   Grace period on TT_109A expires
          TT_109A = 96°C — above critical_max 95.0
          Also 9°C over the last 5 minutes, near the rapid_rise budget
          🔴 CRITICAL, confirmation 1..3 → published
          Routed per alert_routing.critical: kafka + webhook + slack + email
```

**Operator Action:**
1. Check the dashboard: `TT_109A` 96°C, `XT_600` 4.2 mm/s
2. Inspect the bearing visually if accessible
3. Reduce load on the turbine
4. If the trend continues, schedule maintenance and plan bearing replacement

**Why the warning came first.** Absolute limits caught this before the rate rule
did, because the rise was steady rather than sudden. The next scenario covers the
inverse case, where the absolute limits never trip at all.

### Scenario 1b: Bearing Wear Early Warning (Rapid Increase)

The case `out_of_range` cannot catch. A gearbox bearing begins to spall. Vibration
rises well above its own norm but stays comfortably inside the configured band,
so no absolute threshold is ever crossed.

**Sensor:** `XT_600` (Gearbox Vibration X), `STEADY_STATE`
**Bands:** warning 1.5–4.5 mm/s, critical 0.8–6.0 mm/s
**Rule:** `rapid_increase`, >50% over a 10-minute rolling baseline

```
T=0-40min   XT_600 oscillating 2.2-2.4 mm/s
            10-min rolling baseline ≈ 2.30 mm/s
            out_of_range: quiet (2.3 sits mid-band)
            rapid_rise:   not configured for XT_600

T=41min     XT_600 = 2.9 mm/s
            baseline 2.31 → +25.5%   under the 50% threshold, no candidate

T=44min     XT_600 = 3.5 mm/s
            baseline 2.31 → +51.7%   candidate, confirmation 1/3
            out_of_range STILL quiet: 3.5 < warning_max 4.5

T=44:01     XT_600 = 3.5 mm/s   confirmation 2/3
T=44:02     XT_600 = 3.5 mm/s   confirmation 3/3
            🔴 CRITICAL published
            Reason: "XT_600 increased 51.7% (baseline 10min avg: 2.31,
                     current: 3.50, threshold: 50%)"
            Grace period opens on XT_600 for 5 minutes

T=49min+    Vibration holds near 3.5 mm/s.
            The rolling baseline climbs toward 3.5 as the elevated readings
            enter the window, so increase_percent decays below 50% and the
            rule stops re-firing. The sensor is now quietly at a new normal —
            elevated, but no longer changing.
```

**What this bought.** The alert landed roughly a full maintenance cycle before
`XT_600` would have reached `warning_max` at 4.5 mm/s, and two steps before
`critical_max` at 6.0. Nothing in the absolute thresholds had moved.

**Operator Action:**
1. Compare `XT_600` against `XT_601` — a rise on one axis only points at a
   specific bearing; both axes together suggest rotor imbalance
2. Check `TT_109A` for a matching temperature trend. If both are climbing, the
   `gearbox_health_multi` rule in Scenario 5 is about to fire
3. Schedule a vibration spectrum analysis at the next planned stop
4. Record the new baseline. Once vibration settles at 3.5 mm/s, that value
   becomes the reference for the *next* 50% step — the rule measures change,
   not condition, so a degraded machine will need its absolute
   `warning_max` reviewed as well

**Tuning note.** If normal operation includes routine load steps that move
vibration by half, this rule will report them. Raise
`increase_threshold_percent` toward 75, or lengthen `baseline_window_minutes` so
short excursions are averaged into the baseline rather than measured against it.

### Scenario 2: Sensor Failure (Stuck Value)

**Symptoms:**
- TURBINE_SPEED_RPM stuck at 12000 RPM
- In STEADY_STATE, no changes for 10+ minutes

**Alert Sequence:**

```
T=0min    RPM = 12000 (normal)
T=1min    RPM = 12000 (same)
T=2min    RPM = 12000 (same)
...
T=10min   RPM = 12000 (still same)
          Confirmation count: 1,2,3 → Alert
          
T=11min   RPM = 12000 (still same)
          Grace period prevents duplicate alert
          
T=12min   RPM = 12000 (still stuck)
          Possible sensor failure or mechanical lock
          
T=13min   RPM suddenly changes to 11500
          Grace period expired, sensor came unstuck
          No more alerts (value changed)
```

**Operator Action:**
1. If RPM changes: May have been temporary glitch
2. If RPM stays stuck: Probable sensor failure
   - Check sensor wiring
   - Restart turbine controller
   - If persistent: Replace RPM sensor

### Scenario 3: Suppressed False Positive (RAMP_UP Temperature Rise)

**Symptoms:**
- During RAMP_UP the gearbox warms as load comes on
- At `STEADY_STATE` limits, 68°C would be below `critical_min` (65°C) and 70°C
  below `warning_min` (75°C) — two spurious alerts on a perfectly normal ramp

**What Happens:**

```
T=0min    RPM = 100     → inferred state IDLE
          TT_109A = 65°C
          IDLE band: warning 45-65, critical 35-75. In range, quiet.

T=1min    Operator ramps up. RPM = 5000 → inferred state RAMP_UP
          TT_109A = 68°C
          RAMP_UP band: warning 55-90, critical 45-100. In range, quiet.
          Under STEADY_STATE limits this would have read as below warning_min.

T=2min    RPM = 8000 (still RAMP_UP — the 2000-11000 band falls through
          to RAMP_UP by design)
          TT_109A = 70°C. Still inside the wide RAMP_UP band. Quiet.

T=3min    RPM = 11500 → inferred state STEADY_STATE
          TT_109A = 75°C — exactly at STEADY_STATE warning_min. Quiet.

T=4min    RPM = 12000, TT_109A = 80°C
          Mid-band for STEADY_STATE. Normal operation.
```

**What did the suppressing.** State-aware bands, and only those. Every reading
above was checked by `_detect_out_of_range` against the band for the state that
the live RPM implied. Had state inference returned `STEADY_STATE` throughout —
which is what happens when no `TURBINE_SPEED_RPM` reading has arrived yet — the
T=1min and T=2min readings would both have produced alerts.

**What did not do the suppressing.** `rapid_rise` has no state awareness. Its
budget for `TT_109A` is a flat 10°C per 5-minute window in every state. The ramp
above moves 15°C in 4 minutes, and had it been 2°C faster it would have tripped
`rapid_rise` legitimately — a ramp is genuinely a rapid rise. If planned ramps
are producing `rapid_rise` noise in your deployment, the fix is to raise
`rise_threshold_per_minute`, or to suppress alerts during commanded ramps at the
routing layer. Do not expect state inference to handle it.

**Operator Action:**
- None. The system correctly read the ramp as normal for its state.

### Scenario 4: Pressure-Temperature Divergence

**Symptoms:**
- PT_109A (Pressure) and TT_109A (Temperature) normally correlated
- Today: PT_109A rising but TT_109A flat

**Alert Sequence:**

```
Normal:  PT_109A ↑ → TT_109A ↑ (correlation = 0.9)
         Pressure and temperature track together

Today:   PT_109A = 33.5 (normal)
         TT_109A = 75.0 (normal)
         
         PT_109A = 34.2 ↑ (rising)
         TT_109A = 75.1 (not rising, stuck)
         
         Correlation over last 10 min = 0.2 (broke!)
         ⚠️ WARNING: Pressure-Temperature divergence
         Reason: "Normally correlated sensors diverged"
         
         Possible cause:
         - PT sensor reading pressure surge (false)
         - TT sensor stuck (true)
         - Actual system state change (rare)
```

**Operator Action:**
1. Check both sensors
2. Likely cause: TT_109A sensor failure (stuck)
3. Replace temperature sensor

> **Not yet detected automatically.** The `pressure_temp_divergence` rule uses
> `correlation_type: "should_correlate"`, which `_detect_correlation_break()`
> does not dispatch on. Today this pattern surfaces through `stuck_value` on
> `TT_109A` instead — the flat temperature trace trips it after 600 seconds. The
> statistical correlation described above is Phase 3 work.

### Scenario 5: Gearbox Health Compound Alert (Multi-Sensor)

The case that no single sensor can call. Bearing degradation raises both
temperature and vibration, but each one alone has an innocent explanation — a hot
ambient day, a gusty afternoon. Together, in a gearbox, they are a fault
signature.

**Rule:** `gearbox_health_multi` — `TT_109A > 85°C` **AND** `XT_600 > 4.0 mm/s`
**Severity:** `warning` (from the rule's `severity` field)

Note where both thresholds sit relative to the per-sensor bands. `TT_109A` at
85°C is exactly `warning_max` for `STEADY_STATE`; `XT_600` at 4.0 mm/s is *below*
its `warning_max` of 4.5. The compound rule therefore fires on a combination in
which the vibration sensor, judged alone, is still nominal.

```
T=0min      TT_109A = 82°C   XT_600 = 3.9 mm/s
            Both inside band. gearbox_health_multi: TT_109A 82 > 85 is FALSE.
            Evaluation short-circuits on the first condition; XT_600 is never
            read, and condition_details would hold one entry.

T=15min     TT_109A = 86.5°C   XT_600 = 3.9 mm/s
            🟡 out_of_range on TT_109A begins confirming (above warning_max 85)
            gearbox_health_multi: TT_109A TRUE, XT_600 3.9 > 4.0 FALSE → no fire.
            This is the discipline the rule buys. A hot bearing on a still day
            does not raise a compound alert.

T=15:02     out_of_range on TT_109A reaches 3/3 → 🟡 WARNING published
            Grace period opens on TT_109A for 5 minutes

T=28min     TT_109A = 87.5°C   XT_600 = 4.5 mm/s
            Both conditions now TRUE.
            The rule is evaluated once per reading, so within a single telemetry
            message it is evaluated twice — once as TT_109A is processed, once
            as XT_600 is. Each maintains its own multi_sensor confirmation
            count. Whichever reaches 3 first publishes; a sensor already inside
            a grace period is skipped entirely and stops accumulating.
            Here TT_109A is in grace from its own out_of_range alert, so
            XT_600 confirms first.   confirmation 1/3

T=28:01     Both still true.   confirmation 2/3
T=28:02     Both still true.   confirmation 3/3
            🟡 WARNING published, detection_type = multi_sensor, sensor = XT_600
            Reason: "Multi-sensor condition: Gearbox Health (Multi-Sensor) -
                     TT_109A > 85.0 AND XT_600 > 4.0"
            threshold_info.conditions carries both measured values:
              TT_109A 87.5 (met), XT_600 4.5 (met)
            Grace period opens on XT_600 for 5 minutes

T=33min     Grace expires. If both conditions still hold, the rule re-confirms
            and re-publishes. A persisting compound fault repeats roughly every
            5 minutes rather than once — size downstream deduplication on
            threshold_info.rule_id accordingly.
```

**Reading the alert.** The `sensor` field says `XT_600`, but the finding is about
neither sensor individually. Group and deduplicate on
`threshold_info.rule_id == "gearbox_health_multi"`; treat `sensor` as
incidental — it records which reading happened to drive evaluation, and it can
differ between two firings of the same rule depending on grace-period state and
message ordering.

**Operator Action:**
1. Treat as a bearing finding, not a temperature finding. Temperature and
   vibration rising together in a gearbox is degradation until proven otherwise
2. Pull the `XT_600` history — if Scenario 1b's `rapid_increase` alert fired
   earlier on the same turbine, the wear has been developing and you have a start
   date for it
3. Check `TT_110A` against `TT_109A`. If `gearbox_bearing_temp_corr` also fired
   on divergence, the problem localises to bearing A
4. Derate the turbine and schedule inspection. This rule is deliberately set at
   `warning` rather than `critical` because it is an early signature, not an
   emergency — the absolute `critical_max` limits remain the stop condition

**Verifying a rule before trusting it.** Multi-sensor rules fail closed, so a
misconfigured one is silent rather than noisy. Confirm every named sensor is
actually reporting:

```bash
docker exec iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 -u root -pw root \
  -e "SELECT last TT_109A, XT_600 FROM root.digitaltwin.customer1.site1.turbine01"
```

If either column is absent or stale, the rule cannot fire regardless of
conditions.

---

## Operational Guide

### Starting the Detector

**Option 1: In Same Container as Consumer**
```bash
# In docker-compose.yml: start detector as background service
docker-compose up -d
# Detector runs in same container, logs mixed with consumer
docker-compose logs anomaly-detector
```

**Option 2: Separate Container (Recommended for Production)**
```bash
# Build detector image
docker build -f Dockerfile.anomaly-detector -t turbine/anomaly-detector:latest .

# Add to docker-compose.yml and start
docker-compose up -d anomaly-detector

# Check health
curl http://localhost:8010/health
```

### Monitoring Detector Health

**Health Endpoint:**
```bash
curl http://localhost:8010/health

# Response
{
  "status": "healthy",
  "checks": {
    "kafka_connected": {
      "status": true,
      "message": "consuming"
    }
  },
  "ready": true
}
```

**Logs:**
```bash
docker-compose logs -f anomaly-detector

# Examples:
# 2026-09-06T15:30:45Z INFO: Anomaly detector started
# 2026-09-06T15:31:00Z WARNING: Alert confirmed and created
# 2026-09-06T15:31:00Z DEBUG: Alert not yet confirmed
```

Every line is a JSON object. The useful fields when tracing an alert:

| Log message | Level | Fields |
|---|---|---|
| `Alert not yet confirmed` | DEBUG | `sensor`, `detection`, `count`, `required` |
| `Alert confirmed and created` | WARNING | `alert_id`, `sensor`, `severity`, `reason` |
| `Detection method failed` | ERROR | `method`, `sensor`, `error` |

`Alert not yet confirmed` is at DEBUG, so set `LOG_LEVEL=DEBUG` when tuning
thresholds — it is the only way to see detections that are firing but not yet
reaching `confirmation_count`. Watch a single sensor:

```bash
docker compose logs anomaly-detector \
  | jq -c 'select(.sensor == "XT_600") | {message, detection, count, reason}'
```

The `reason` field **in the log line is truncated to 100 characters**. Multi-sensor
reasons routinely exceed that, so a log line can read
`... TURBINE_SPEED_RPM < 110` where the real threshold is `11000.0`. The alert
published to Kafka carries the untruncated string — read the topic, not the log,
when the exact text matters.

### Adjusting Thresholds

1. **Edit config:** `app/config/anomaly_thresholds.json`
2. **Reload:** Restart detector container
   ```bash
   docker-compose restart anomaly-detector
   ```
3. **Verify:** Check logs that new config loaded

### Debugging False Positives

1. **Identify sensor:** Which sensor is over-alerting?
2. **Check thresholds:**
   ```json
   {
     "sensors": {
       "PROBLEM_SENSOR": {
         "anomaly_rules": [{
           "type": "out_of_range",
           "enabled": false
         }]
       }
     }
   }
   ```
3. **Increase grace period:**
   ```json
   {
     "global_settings": {
       "grace_period_minutes": 10
     }
   }
   ```
4. **Increase confirmation count:**
   ```json
   {
     "global_settings": {
       "confirmation_count": 5
     }
   }
   ```

### Tuning Detection Sensitivity

**Goal:** Catch real anomalies, suppress false positives.

**Tuning Process:**

1. **Week 1:** Run with aggressive thresholds
   - Low thresholds catch more anomalies
   - Accept higher false positive rate
   - Goal: Understand normal operating range

2. **Week 2-3:** Analyze false positives
   - Which sensors over-alert?
   - When do they over-alert? (time of day, turbine state)
   - Adjust thresholds based on data

3. **Week 4+:** Stabilize
   - Fine-tune remaining issues
   - Document sensor-specific adjustments
   - Prepare for production

---

## Test Coverage

27 unit tests in
[`app/tests/test_anomaly_detection.py`](../tests/test_anomaly_detection.py). No
Kafka, IoTDB, or network required — the detector's Kafka producer is constructed
but never flushed, so `librdkafka` logs broker resolution failures to stderr
during the run. Those lines are expected and do not affect the result.

**Run from the repository root**, not from `app/`. The test fixture builds
`AnomalyDetector("app/config/anomaly_thresholds.json")` with a path relative to
the working directory; running from `app/` fails collection with
`FileNotFoundError`.

```bash
cd "/home/ashwinkm/Digital Twins/Apache_IOTDB"
LOG_DIR=/tmp/turbine-test-logs python3 -m pytest app/tests/test_anomaly_detection.py -q
```

```
...........................                                              [100%]
27 passed in 0.09s
```

`LOG_DIR` must point at a directory you own. `anomaly_detection.py` calls
`configure_logging()` at import time, which opens `$LOG_DIR/app.log` for append;
the checked-out `app/logs/app.log` is owned by the container uid, so omitting the
override dies at collection with `PermissionError: [Errno 13]`.

| Test class | Tests | Covers |
|---|---|---|
| `TestConfigLoading` | 4 | Config parses; required sensors present; all four states have thresholds; `anomaly_rules` populated |
| `TestOutOfRangeDetection` | 3 | Critical min and max violations; thresholds differ by inferred state |
| `TestStuckValueDetection` | 2 | Unchanged value flagged; gradually changing value not flagged |
| `TestRapidRiseDetection` | 1 | Absolute temperature rise past the window budget |
| `TestRapidIncreaseDetection` | 2 | 2.30 → 3.50 mm/s (+52.2%) detected; 2.30 → 2.40 (+4.3%) not detected |
| `TestDriftDetection` | 2 | 1 bar/hour drift detected; normal variation ignored |
| `TestCorrelationBreakDetection` | 2 | Bearing temp divergence past `max_divergence`; small divergence ignored |
| `TestMultiSensorConditionDetection` | 2 | Both gearbox conditions true → `multi_sensor` alert; only one true → no alert |
| `TestAlertConfirmation` | 2 | Alert withheld until `confirmation_count` reached; grace period suppresses duplicates |
| `TestTelemetryParsing` | 3 | Valid payload parsed; missing required fields rejected; non-numeric metrics skipped |
| `TestStateInference` | 3 | Low RPM → `IDLE`; high RPM → `STEADY_STATE`; mid RPM → `RAMP_UP` |
| `TestAlertSerialization` | 1 | `Alert.to_json()` round-trips |

**Whole application suite**, also from the repository root:

```bash
LOG_DIR=/tmp/turbine-test-logs python3 -m pytest app/tests -q
```

```
53 passed
```

53 = 27 anomaly detection + 26 producer, consumer, and resilience tests.

### What is not covered

`run_detector()`, `build_consumer()`, and `publish_alert()` are I/O loops and are
not unit-tested. The `should_correlate` correlation type has no tests because it
has no implementation. Verify the Kafka path by hand against a running stack:

```bash
docker exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic turbine.anomaly.alerts.v1 \
  --max-messages 3
```

---

## Troubleshooting

### Issue: Detector Not Starting

**Symptom: `FileNotFoundError: 'app/config/anomaly_thresholds.json'`**

`AnomalyDetector.__init__` defaults to that path *relative to the working
directory*. It resolves when the process starts from the repository root and
fails from anywhere else.

```bash
ls -la app/config/anomaly_thresholds.json     # exists?
jq . app/config/anomaly_thresholds.json       # valid JSON?
```

In a container, set the working directory to the mount root or pass an absolute
path: `AnomalyDetector("/app/config/anomaly_thresholds.json")`.

**Symptom: `SyntaxError: f-string: unmatched '['` at import**

The interpreter is older than 3.12. See
[Before the first deploy](#before-the-first-deploy) — `app/Dockerfile` currently
builds on `python:3.11-slim`, which cannot parse the multi-sensor alert message.

**Symptom: `json.decoder.JSONDecodeError`**

A malformed edit to `anomaly_thresholds.json`. The error is logged with the
parser message before the exception propagates; `jq .` on the file will point at
the same line.

### Issue: No Alerts Generated

**Symptoms:**
- Detector running (health check OK)
- Kafka receiving telemetry
- No alerts in `turbine.anomaly.alerts.v1` topic

**Debug:**
```bash
# Check detector is consuming from telemetry topic
docker-compose logs anomaly-detector | grep "consuming"

# Check if anomaly detection enabled
docker-compose logs anomaly-detector | grep "enable_anomaly_detection"

# Manually verify Kafka topic
docker exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic turbine.telemetry.raw.v1 \
  --max-messages 3

# Check anomaly alerts topic
docker exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic turbine.anomaly.alerts.v1 \
  --max-messages 3
  # Should see messages if detector working
```

### Issue: Too Many False Positive Alerts

**Symptoms:**
- Alert rate: 100+ per day
- Most are warnings on normal operation

**Solutions:**

1. **Increase confirmation_count** (requires 3→5 detections before alerting):
   ```json
   {"global_settings": {"confirmation_count": 5}}
   ```

2. **Increase grace_period** (suppress duplicates for 5→10 minutes):
   ```json
   {"global_settings": {"grace_period_minutes": 10}}
   ```

3. **Relax out-of-range thresholds:**
   ```json
   {
     "sensors": {
       "TT_109A": {
         "thresholds": {
           "STEADY_STATE": {
             "warning_max": 88.0
           }
         }
       }
     }
   }
   ```

4. **Disable problematic rules:**
   ```json
   {
     "anomaly_rules": [{
       "type": "drift",
       "enabled": false
     }]
   }
   ```

### Issue: Missing Alerts (Real Anomalies Not Caught)

**Symptoms:**
- Operator manually notices bearing overheating
- No alert was generated

**Solutions:**

1. **Lower confirmation_count:**
   ```json
   {"global_settings": {"confirmation_count": 2}}
   ```

2. **Lower grace_period:**
   ```json
   {"global_settings": {"grace_period_minutes": 2}}
   ```

3. **Tighten thresholds:**
   ```json
   {
     "sensors": {
       "TT_109A": {
         "thresholds": {
           "STEADY_STATE": {
             "warning_max": 82.0
           }
         }
       }
     }
   }
   ```

4. **Enable more detection methods.** Absolute thresholds miss faults that are
   large relative to a sensor's own norm but small on its configured scale. Add
   the percentage rule alongside the absolute one:

   ```json
   {
     "anomaly_rules": [
       {
         "type": "rapid_rise",
         "enabled": true,
         "rise_threshold_per_minute": 2.0,
         "duration_minutes": 5
       },
       {
         "type": "rapid_increase",
         "enabled": true,
         "severity": "critical",
         "increase_threshold_percent": 50,
         "baseline_window_minutes": 10
       }
     ]
   }
   ```

5. **Add a compound rule** for a failure mode whose individual signals are each
   unremarkable. See [Scenario 5](#scenario-5-gearbox-health-compound-alert-multi-sensor).

### Issue: A Rule Is Configured but Never Fires

Rules fail closed, so a broken rule is silent rather than noisy.

| Cause | Check |
|---|---|
| `"enabled"` missing or false | Every rule needs `"enabled": true` explicitly; there is no default-on |
| Sensor absent from `sensors` | Per-sensor rules are looked up by sensor name; unlisted sensors are skipped |
| Named sensor has no history | Multi-sensor and correlation rules skip when any named sensor is unreported |
| Invalid `severity` string | `AlertSeverity(...)` raises on anything but `info`/`warning`/`critical`; grep the log for `Detection method failed` |
| Unknown operator | `_evaluate_condition()` logs `Unknown operator` and returns false |
| Threshold block missing for the current state | `out_of_range` returns silently when `thresholds.<STATE>` is absent |
| Grace period from another detection type | Grace is per sensor, not per detection type — an earlier alert masks all others on that sensor for 5 minutes |
| Window not yet full | `drift` needs 60 readings and 10 minutes; `stuck_value` needs 80% of its duration |

```bash
docker compose logs anomaly-detector | grep -E "Detection method failed|Unknown operator"
```

---

## Next Steps

### Completed
- [x] State inference across all four operational states
- [x] Percentage-based `rapid_increase` detection for vibration sensors
- [x] Multi-sensor AND-condition evaluation (`sensor_conditions`)
- [x] Unit coverage for all seven detection methods (27 tests)

### Phase 2 Enhancements
- [ ] Add `anomaly-detector` to `docker-compose.yml` and bump the image to Python 3.12
- [ ] Enforce `duration_seconds` on multi-sensor conditions
- [ ] Implement `should_correlate` statistical correlation
- [ ] Per-customer threshold overrides
- [ ] Baseline learning (1 week calibration)
- [ ] Per-detection-type grace periods
- [ ] Moving average smoothing for noisy sensors

### Phase 3 Enhancements
- [ ] ML-based anomaly detection (Isolation Forest, ARIMA)
- [ ] Anomaly history in IoTDB with search
- [ ] Predictive alerts (bearing failure prediction)
- [ ] Root cause analysis (automated diagnosis)
- [ ] Custom alert rules per customer

### Phase 4 Enhancements
- [ ] Real-time anomaly dashboard with drill-down
- [ ] Alert suppression policies (e.g., maintenance window)
- [ ] SLA tracking (alert response time, resolution time)
- [ ] Integration with external monitoring (Datadog, New Relic)

---

## References

- **SCALING_PLAN.md:** Multi-turbine architecture and scaling strategy
- **SENSOR_IDS.md:** Sensor semantic identifiers and naming conventions
- **API.md:** Kafka topic schemas and message formats
- **ARCHITECTURE.md:** System design and data flow

---

## Support

For questions or issues with anomaly detection:
1. Check this documentation first
2. Review logs: `docker-compose logs -f anomaly-detector`
3. Check Kafka topics: Verify messages in input/output topics
4. Consult TROUBLESHOOTING section above
5. Open issue with logs and reproduction steps
