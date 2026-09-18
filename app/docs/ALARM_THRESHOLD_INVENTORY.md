# Alarm & Threshold Inventory — Existing Systems and DAQ Rig Proposal

**Status:** Documentation + design proposal (no code changed by this document)
**Scope:** (1) exhaustive inventory of every threshold/alarm/warning definition currently in
the codebase, across all subsystems and sensors; (2) newly designed alarms for
`data/daq_test_log_normalized_1hz.csv`, grounded in that file's actual statistics.
**Related:** [`ANOMALY_DETECTION.md`](ANOMALY_DETECTION.md) (engine mechanics for system #1 below)

---

## 0. Read this first

Two things fell out of this survey that change how the rest of the document should be read.

**This CSV is not synthetic wind-turbine telemetry.** `data/daq_test_log_normalized_1hz.csv`
is a real National Instruments DAQ log from a **steam turbine test rig**: Inlet Steam Admission →
Emergency Stop Valve → Throttle Valves 1/2 → Wheel Case → Turbine Core/Rotor → Intermediate GBC →
Gearbox → Generator/Dynamometer, plus lube-oil leakage lines, hydraulics, and cooling water. It
is replayed into the pipeline by `app/test_helpers/replay_daq_to_kafka.py` under the "turbine"
naming used elsewhere in this repo, but the physical asset it describes is a steam-turbine drive
train, not a wind-turbine nacelle. The full sensor legend (source: `data/turbine-schema-extracted.json`,
extracted from `data/UI_r6_DigitalTwin.pdf`) is in §2.

**There are six independent threshold definitions in this codebase, and they disagree.**
The same sensor (e.g. `XT_600`, `PT_109A`, `TT_109A`) has a different warning/critical number
depending on which file answers the question. Only two of the six systems actually *do*
anything (publish a Kafka alert or raise a real ThingsBoard platform alarm) — the other four are
either UI-only displays or unread metadata. §1 documents each system and marks which is
enforced. This is evidence gathered by reading the code paths, not inference — see file:line
citations throughout.

---

## 1. Existing threshold/alarm systems — full inventory

### 1.1 Python Kafka anomaly detector — **ENFORCED** (publishes real alerts)

Source of truth: `app/config/anomaly_thresholds.json`, evaluated by
`app/src/anomaly_detection.py` (`AnomalyDetector`). This is the only system confirmed to run
continuously against live telemetry, debounce with a confirmation count, and publish to Kafka
topic `turbine.anomaly.alerts.v1`, from where `app/src/postgres_store.py` persists confirmed
alerts (`alerts` table) and pre-confirmation breaches (`alert_breaches` table).

It covers **8 of the CSV's 61 channels**: `PT_109A`, `PT_110A`, `TT_109A`, `TT_110A`,
`TURBINE_SPEED_RPM`, `GB_TRQ`, `XT_600`, `XT_601`.

Global settings (`anomaly_thresholds.json:8-16`): `grace_period_minutes=5`,
`confirmation_count=3`, `drift_window_minutes=60`. Note: `enable_anomaly_detection`,
`enable_correlation_checks`, `enable_drift_detection` are declared but **never read** by
`anomaly_detection.py` — all detectors always run regardless of these flags.

State-aware bands (four states: `IDLE` / `RAMP_UP` / `STEADY_STATE` / `RAMP_DOWN`, inferred
from `TURBINE_SPEED_RPM` in `_infer_turbine_state()`, `anomaly_detection.py:320-353`):

| Sensor | Unit | STEADY_STATE warning | STEADY_STATE critical | Extra rules |
|---|---|---|---|---|
| `PT_109A` | bar | 32.3–33.7 | 32.0–34.0 | `drift` warn (>0.5/h), `stuck_value` warn (300s) |
| `PT_110A` | kg/cm² | 3.25–3.55 | 3.2–3.6 | `drift` warn (>0.1/h) |
| `TT_109A` | °C | 75–85 | 65–95 | `rapid_rise` **critical** (>2.0°C/min sustained 5 min), `drift` warn (>5.0/h) |
| `TT_110A` | °C | 75–85 | 65–95 | `rapid_rise` critical (>2.0°C/min / 5 min) |
| `TURBINE_SPEED_RPM` | RPM | 11500–12000 | 10500–12800 | `stuck_value` **critical** (600s) |
| `GB_TRQ` | kN·m | 6.5–7.5 | 5.5–8.5 | `out_of_range` severity is **warning**, not critical |
| `XT_600` | mm/s | 1.5–4.5 | 0.8–6.0 | `out_of_range` **warning** only; `rapid_increase` critical (>50% vs 10-min baseline) |
| `XT_601` | mm/s | 1.5–4.5 | 0.8–6.0 | `out_of_range` warning only |

Correlation rules (`anomaly_thresholds.json:456-498`):
- `gearbox_bearing_temp_corr` — `TT_109A`/`TT_110A` should track within **5.0°C**, warning. **Implemented.**
- `gearbox_health_multi` — `TT_109A > 85°C` AND `XT_600 > 4.0 mm/s` (both instantaneous, the
  configured `duration_seconds: 300` is **declared but not enforced** —
  `_evaluate_multi_sensor_rule()` only checks the latest reading) → warning.
- `pressure_temp_divergence` — `correlation_type: "should_correlate"` — **not implemented at
  all**; `_detect_correlation_break()` only dispatches `"should_track"`. Loads without error,
  never fires.

Alert routing (`anomaly_thresholds.json:521-541`) declares webhook/Slack/email for critical
alerts, but **only the Kafka publish path exists in code** (`anomaly_detection.py:953-977`) —
no webhook/Slack/email dispatch is implemented anywhere in the repo.

**Known bug:** `app/src/anomaly_consumer.py` defines a second, apparently dead consumer class
whose `process_message()` treats `detector.process_reading()`'s return value (always a `list`)
as a single `Alert` object — calling `.detection_type` on a list would raise `AttributeError`.
Unclear from static analysis whether this file or `anomaly_detection.py:run_detector()` is what's
actually deployed; check the relevant `docker-compose.yml` entrypoint.

Per `ANOMALY_DETECTION.md`, this service is **implemented and tested (27/27) but not yet wired
into `docker-compose.yml`**, and additionally requires Python 3.12+ (the app Dockerfile currently
targets 3.11-slim) — so as of this writing it is not confirmed running in the deployed stack.

**Important mismatch:** the numeric bands above (e.g. `TT_109A` 75–95°C, `GB_TRQ` 6.5–8.5 kN·m,
`TURBINE_SPEED_RPM` 11500–12800) do **not** match this CSV's actual data. In the real DAQ log,
`TT_109A` runs 238.9–284.6°C (an inlet-steam temperature, not a gearbox bearing temperature —
see §2's legend), `GB_TRQ` runs 0.09–0.23 kN·m during steady state, and `TURBINE_SPEED_RPM` does
reach the configured band (max observed 12049 RPM). These thresholds read as calibrated for a
different, likely synthetic, wind-turbine-style data source, reusing tag names that collide with
this rig's real channels. Applying them unmodified to this CSV would immediately and permanently
alarm on `TT_109A`/`TT_110A` (every real reading is ~150–200°C above the configured critical
max) while `GB_TRQ` would sit permanently in critical-low.

### 1.2 ThingsBoard server-side rule chain — **ENFORCED** (creates real platform alarms)

Source: `app/tools/commands/rulechain_command.py`, deployed via
`thingsboard_admin.py rulechain deploy` as rule chain "Turbine Dynamic Threshold Alarms",
default chain on the turbine device profile. This is the **only** system that creates actual
ThingsBoard alarms (`TbCreateAlarmNode`/`TbClearAlarmNode`), independent of the Kafka/Postgres
pipeline above.

| Sensor | Threshold (overridable) | Severity | Alarm type | File:line |
|---|---|---|---|---|
| `XT_600` | 6.0 mm/s via `shared_threshold_XT_600_alarm` | CRITICAL | "Turbine Vibration Alarm" | `rulechain_command.py:18-28, 90-93` |
| `PYRO_T` | 350.0°C via `shared_threshold_PYRO_T_alarm` | CRITICAL | "Turbine Overheat Alarm" | `rulechain_command.py:52-61, 94-97` |

Only these **2 sensors** have a real create/clear alarm path. Alarms are fixed CRITICAL only —
no separate warning-tier alarm is raised by this rule chain. Alarm detail text embeds fixed
strings ("ISO 10816-3 Class III Zone D Trip", "API 612 Core Thermal Trip") — these are
descriptive labels baked into the rule, not references to a live standards lookup.

### 1.3 "Turbine Threshold Configurator" widget — **UI input, mostly not enforced**

`app/thingsboard/widgets/turbine-threshold-config.config.json`. Operator-facing form; on Save
writes values to the device's `SHARED_SCOPE` attributes. Exposes 8 sensors with 4 presets
(ISO Class II / ISO Class III / Commissioning / Full Load Baseline):

| Sensor | Default warn | Default alarm | Unit | Actually consumed downstream? |
|---|---|---|---|---|
| `XT_600` | 4.5 | 6.0 | mm/s | **Yes** — feeds rule chain §1.2 |
| `PYRO_T` | 330 | 350 | °C | **Yes** — feeds rule chain §1.2 |
| `XT_604` | 4.0 | 5.5 | mm/s | No consumer found |
| `ZT_600` | 3.0 | 4.5 | mils | No consumer found |
| `PYRO_GB` | 200 | 220 | °C | No consumer found |
| `TT_109A` | 280 | 310 | °C | No consumer found |
| `PT_109A` | 35.0 | 38.0 | bar | No consumer found |
| `SPEED` (`TURBINE_SPEED_RPM`) | 12000 | 13500 | RPM | No consumer found |

Only the two sensors already wired to the rule chain actually change enforcement behavior when
edited here; the other six are UI-only despite looking editable.

### 1.4 "Turbine Headroom & Limits Monitor" widget — **display only**

`app/thingsboard/widgets/turbine-headroom-monitor.config.json`. Client-side "% headroom to trip"
table, same 8 sensors and same default numbers as §1.3. Listens for the configurator's
`tb_thresholds_updated` browser event to stay visually in sync. No alarm creation, no
persistence — colors its own rows only.

### 1.5 "Turbine Mimic" 2D SCADA widget — **display only, own state-aware table**

`app/thingsboard/widgets/turbine-mimic.js:958-1039` (`DEFAULT_THRESHOLDS`). Independently
maintains the same 4-state model as §1.1 but with different numbers for overlapping sensors
(e.g. `TURBINE_SPEED_RPM` STEADY_STATE warn/crit is 10000/12100 & 9000/12800 here, vs.
11500–12000 / 10500–12800 in §1.1). Covers 12 sensors; **7 are explicitly self-flagged in code
comments as "provisional band derived from sensor profile"** (`PROVISIONAL_THRESHOLD_KEYS`,
line 1042: `PYRO_T, PYRO_GB, FT_110A, PT_150A, XT_604, XT_605, ZT_600`) — the widget's own
authors mark these as placeholders, not engineering-reviewed limits. Purely visual: colors
hotspots, freezes the rotor animation if telemetry is stale beyond `staleThresholdSeconds`
(120s default, line 784) — no alarm creation or persistence.

### 1.6 "3D Babylon" turbine twin widget — **display only, widest per-sensor coverage**

`app/thingsboard/widgets/turbine-3d-babylon.js:361-428`. A flat (non-state-aware)
warning/alarm/critical 3-tier table covering **~48 of the 61 channels** — the broadest coverage
of any file in the repo, including all 10 RTD channels (generator windings/bearings, main
bearings, cooling water, tower base — none of which appear in §1.1–1.5):

| Sensor(s) | Warn | Alarm | Critical |
|---|---|---|---|
| `RTD_219A`/`RTD_219B`/`RTD_220`/`RTD_221` (generator windings/bearings) | 85.0 | 95.0 | 105.0 |
| `RTD_200`/`RTD_201`/`RTD_202`/`RTD_203`/`RTD_204`/`RTD_205` (main bearings/cooling/tower) | 90.0 | 105.0 | 120.0 |
| `XT_604`–`XT_607` (gearbox radial vib) | 4.0 | 5.5 | 7.0 |
| `PYRO_GB` | 40.0 | 50.0 | 60.0 |
| `GB_TRQ` | 8.0 | 10.0 | 12.0 |

Full detail is in the fork transcript; the pattern throughout is warn/alarm pairs that sit far
above this CSV's observed operating range (e.g. RTD warn=85–90°C vs. observed max 61°C — see §3),
which is defensible as design headroom for a rig that hadn't reached thermal equilibrium in this
1-hour sample (see §4), but is unverified against a real thermal-soak test.

**Likely bug worth flagging for engineering review:** `PT_153` (Lube Oil Supply Pressure,
warn=2.5/alarm=1.8/critical=1.2 — a *descending* limit, correct for a supply-pressure-loss
alarm) and `PT_201` (Seal Gas Supply Pressure, warn=5.0/alarm=4.0/critical=3.0, same descending
pattern) are configured with alarm values *below* warning, reflecting the physically correct
intent (alarm on a pressure *drop*). But the classification logic at
`turbine-3d-babylon.js:1032-1034` is a flat ascending check (`value >= alarmLimit → alarm`,
`value >= warningLimit → warning`). For these two descending-limit sensors that comparison is
inverted: a *high* reading would incorrectly classify as alarm/warning, while a genuinely low,
dangerous supply pressure would not. This is a pattern-match observation from reading the
comparison code once, not confirmed by running the widget — worth a maintainer's five-minute
look before trusting these two rows.

### 1.7 Sensor Mappings Catalog — **metadata, not enforced anywhere**

`app/config/sensor_mappings.json` (auto-generated, "do not edit by hand") derives a
single-sided `warning`/`critical` (max only, no min) pair per sensor from
`app/src/sensor_profiles.py`'s synthetic-generator clamp bounds:
`warning = normal_range.max`, `critical = profile.max_value`. No code outside its own generator
and an incidental test reads these threshold fields — it exists but nothing consumes it.

### 1.8 Sensor profile clamp bounds — not alarms

`app/src/sensor_profiles.py` `min_value`/`max_value` per sensor bound only the *synthetic*
telemetry generator's output range. Listed here for completeness; these are generator clamps,
not operational alarms, and don't apply to the real DAQ CSV at all.

### 1.9 Turbine state staleness/"down" detection — operational, not a sensor-value alarm

`app/src/turbine_state.py` (`StateTracker`): `STATE_STALE_SECONDS=120.0` marks a turbine DOWN if
no telemetry arrives within that window; `STATE_STABILITY_SECONDS=30.0` is the minimum dwell
before a state transition is confirmed in the Postgres timeline
(`Config.validate_postgres()` enforces `STALE > STABILITY` at startup). This is a liveness check,
not a sensor threshold — listed for completeness since the user asked for "everything."

### 1.10 Infrastructure-level thresholds — separate from sensor alarms

| Threshold | Default | Location | Purpose |
|---|---|---|---|
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | 5 | `config.py:129`, `resilience.py:46` | Trip breaker after N consecutive IoTDB write failures |
| `CIRCUIT_BREAKER_RESET_TIMEOUT_S` | 30.0s | `config.py:130` | Cooldown before retrying |
| `IOTDB_WRITE_MAX_RETRIES` | 3 | `config.py:125` | Retry attempts per IoTDB write |
| `IOTDB_WRITE_BACKOFF_BASE_S` | 0.2s | `config.py:126` | Exponential backoff base |
| `BATCH_SIZE` / `BATCH_MAX_WAIT_S` | 50 / 5.0s | `config.py:123-124` | Kafka→IoTDB batch flush policy |
| MQTT bridge stall threshold | 120.0s | `kafka_mqtt_bridge.py:204-231` | Marks MQTT delivery unhealthy |
| Postgres `queue_size` | 10000 | `postgres_store.py:138` | Bounded alert/breach queue |
| `POSTGRES_RETENTION_DAYS` | 30 | `config.py:96` | Alert history retention |

These govern pipeline reliability, not sensor conditions — kept separate per your instructions.

### 1.11 Cross-system conflict example

`XT_600` (rotor bearing radial vibration), STEADY_STATE, illustrates the disagreement:

| System | Warning | Alarm/Critical | Enforced? |
|---|---|---|---|
| §1.1 Kafka detector | 1.5–4.5 mm/s | 0.8–6.0 mm/s | Yes (warning only; critical via separate rapid-increase rule) |
| §1.2 ThingsBoard rule chain | — | 6.0 mm/s | Yes (real alarm) |
| §1.3/1.4 widgets | 4.5 | 6.0 | No |
| §1.5 Mimic widget | 0–4.5 | 0–6.0 | No |
| §1.6 3D Babylon widget | 4.5 | 6.0 (alarm) / 7.5 (critical — third tier no one else has) | No |

The widget-layer numbers mostly agree with each other and with the rule chain (4.5/6.0); the
Kafka detector's band is structurally different (it alone has a *minimum* bound).

---

## 2. Full sensor legend for this CSV (61 channels)

Source: `data/turbine-schema-extracted.json` (extracted from the rig's schematic PDF) +
`data/daq_sensor_metadata.json` (per-channel observed range from this exact file).

| Tag | Display name | Subsystem | Unit |
|---|---|---|---|
| PT_109A | Inlet Pressure A | Inlet Steam | bar |
| PT_110A/PT_110B | Inlet Pressure B/C | Inlet Steam (Secondary) | kg/cm² |
| PT_111B | Stage 1 Pressure B | Emergency Stop Valve (ESV) | kg/cm² |
| PT_111 / TT_111 | Stage 1 Pressure/Temp | Throttle Valve 1 (TV1) | kg/cm² / °C |
| PT_112 / TT_112 | Stage 2 Pressure/Temp | Throttle Valve 2 (TV2) | kg/cm² / °C |
| PT_120 / TT_120 / TT_120_R | Gearbox Oil Pressure/Temp/Return Temp | Wheel Case | kg/cm² / °C |
| PT_111C / TT_111C / TT_111C_R | Stage 1 Pressure/Temp C | Inter GBC / Turbine Casing | kg/cm² / °C |
| TT_109A / TT_110A / TT_110B | Gearbox Bearing Temp A/B/C | Gearbox Bearing | °C |
| PYRO_T | Pyrometer Turbine Temp | Turbine Core | °C |
| PYRO_GB | Pyrometer Gearbox Temp | Gearbox | °C |
| GB_TRQ | Gearbox Torque | Gearbox | kN·m |
| TURBINE_SPEED_RPM | Turbine Rotor Speed | Turbine Core | RPM |
| ZT_600 / ZT_601 | Axial Vibration (Top/Bottom Casing) | Turbovisory Vibration | mills |
| XT_600 / XT_601 | Radial Vib (Turbine Front X/Y) | Turbovisory Vibration | mills |
| XT_602 / XT_603 | Radial Vib (Generator Mid/Rear X/Y) | Turbovisory Vibration | mills |
| XT_604 / XT_605 | Radial Vib (Gearbox Front X/Y) | Turbovisory Vibration | mills |
| XT_606 / XT_607 | Radial Vib (Gearbox Rear/Shaft X/Y) | Turbovisory Vibration | mills |
| HP_DEMAND / ACT_POS_FB | Hydraulic Power Demand / Actuator Position Feedback | Actuator & Hydraulic Control | % |
| PT_150A/B / TT_150A/B | Hydraulic Oil Pressure/Temp A/B | Hydraulic System | kg/cm² / °C |
| PT_160/161/162/163 / TT_160/161/162/163 | Lube Oil Header/Supply/Return Pressure & Temp | Leakage Lines 1–3 | kg/cm² / °C |
| FT_110A / FT_162 | Inlet / Lube Oil Flow | Inlet Steam / Leakage Line 1 | TPH |
| PT_153 | Seal Gas Pressure | Auxiliary Seal Gas | kg/cm² |
| PT_201 | Cooling Water Pressure | Cooling Water System | kg/cm² |
| PT_253 / DYNO_WATER_O_L | Dyno Water Pressure / Outlet Temp* | Dynamometer | kg/cm² |
| RTD_219A / RTD_219B | Generator Winding Temp A/B | Generator Winding | °C |
| RTD_220 / RTD_221 | Generator Bearing Temp DE/NDE | Generator Bearings | °C |
| RTD_200 | Nacelle Ambient Temp | Nacelle Ambient | °C |
| RTD_201 | Tower Base Temp | Tower Base Ambient | °C |
| RTD_202 / RTD_203 | Cooling Water Inlet/Outlet Temp | Cooling Water | °C |
| RTD_204 / RTD_205 | Main Bearing Temp DE/NDE | Main Bearings | °C |

\* **Data-quality note:** `DYNO_WATER_O_L`'s display name says "Outlet Temp" but both
`daq_sensor_metadata.json` and this CSV's header give it pressure units (kg/cm²) and a value
range (3.47–3.98) consistent with a pressure, not a temperature. Flagging as a likely metadata
labeling error — not something this document resolves, since it affects the source schema, not
the alarm design.

---

## 3. What's actually covered vs. actually enforced, for this CSV's channels

Cross-referencing §1's six systems against the 61-channel legend:

- **2 sensors** (`XT_600`, `PYRO_T`) have a real, enforced ThingsBoard platform alarm (§1.2).
- **8 sensors** (§1.1's list) get a real Kafka alert pipeline, if/when that service is deployed.
- **~48 sensors** have a number somewhere in the 3D Babylon widget (§1.6), but that widget only
  paints pixels — no alert, no persistence, no notification of any kind reaches an operator who
  isn't looking at that exact 3D view at that exact moment.
- **All 10 RTD channels** (generator windings, generator bearings DE/NDE, main bearings DE/NDE,
  cooling water in/out, nacelle/tower ambient) have display-only numbers and **zero enforced
  alarm coverage** — no Kafka alert, no ThingsBoard platform alarm, nothing that pages anyone.
- `ZT_601`, `XT_602`, `XT_603`, `XT_606`, `XT_607` (5 of 10 vibration channels) are similarly
  display-only, never enforced.
- `HP_DEMAND`, `ACT_POS_FB`, `FT_110A`, `FT_162`, `PT_153`, `PT_201`, and most of the leakage/
  hydraulic pressure & temperature pairs have no threshold in *any* of the six systems.

The rest of this document (§4–§5) designs alarms for the highest-value gaps in the **enforced**
category — sensors that would matter for a real fault but currently generate zero actionable
signal — grounded in this CSV's actual observed behavior.

---

## 4. CSV analysis backing the new alarms

Computed directly from `data/daq_test_log_normalized_1hz.csv` (3589 rows, 1 Hz, 2026-08-12
20:59:11 → 21:58:59). The file's own replay tooling (`replay_daq_to_kafka.py:604-616`) marks
rows 2520–3588 as the sustained `STEADY_STATE` window (RPM > 10000); the statistics below use
that window unless noted.

**1. The rig had not reached thermal equilibrium by the end of this recording.** Comparing the
first 60s and last 60s of the steady-state window (≈16 minutes apart):

| Sensor | First-60s mean | Last-60s mean | Rate (°C/min) |
|---|---|---|---|
| RTD_219A (Generator Winding A) | 37.0 | 51.5 | 0.86 |
| RTD_220 (Generator Bearing DE) | 46.5 | 59.2 | 0.76 |
| RTD_203 (Cooling Water Outlet) | 68.4 | 82.0 | 0.81 |
| RTD_204 (Main Bearing DE) | 41.5 | 53.6 | 0.72 |

All bearing/winding RTDs are still climbing at 0.5–0.9°C/min at the point the log ends — this is
routine rig warm-up, not a fault, but it means (a) any rate-of-rise alarm needs headroom well
above this "normal warm-up" rate or it will alarm constantly on a perfectly healthy run, and (b)
this hour of data almost certainly doesn't capture true steady-state temperatures — real
long-run values will be higher than anything observed here.

**2. Generator bearing DE/NDE track closely; main bearing DE/NDE has a built-in offset.**

| Pair | Divergence min | max | mean | p95 |
|---|---|---|---|---|
| RTD_220 − RTD_221 (Generator DE/NDE) | 0.03°C | 4.31°C | 3.03°C | 4.27°C |
| RTD_204 − RTD_205 (Main bearing DE/NDE) | 4.54°C | 8.29°C | 7.32°C | 8.27°C |

The generator pair is a clean candidate for a should-track correlation alarm (near-zero baseline
divergence). The main-bearing pair has a structural ~7°C DE-hotter-than-NDE offset throughout —
almost certainly the drive-end thrust bearing running warmer than the non-drive-end guide
bearing by design — so a correlation alarm there would need to key off deviation *from that
baseline band*, not absolute divergence; simpler to alarm on DE's absolute temperature instead
(below).

**3. Cooling water shows a stable, large negative ΔT (outlet colder than inlet by design).**
`RTD_203 (outlet) − RTD_202 (inlet)`: min −19.73°C, max −7.68°C, mean −14.85°C — i.e. the water
being cooled loses 8–20°C crossing the heat exchanger. A collapse toward 0°C would mean the
cooler has stopped removing heat.

**4. `PT_201` (cooling water pressure) sits in a tight, low-variance band:** 1.748–2.118 kg/cm²
across the entire file (mean 1.841). A drop well below this band indicates loss of cooling flow.

**5. Five vibration channels never get evaluated by any enforced system.** Their observed
baselines in this file:

| Channel | Location | min | max | mean | std |
|---|---|---|---|---|---|
| ZT_601 | Bottom Casing Axial Vib | −38.16 | −1.26 | −1.76 | 1.28 |
| XT_602 | Generator Mid/Rear X | 0.51 | 1.62 | 1.09 | 0.14 |
| XT_603 | Generator Mid/Rear Y | 0.60 | 1.45 | 1.07 | 0.10 |
| XT_606 | Gearbox Rear/Shaft X | 0.18 | 0.67 | 0.33 | 0.06 |
| XT_607 | Gearbox Rear/Shaft Y | 0.17 | 0.41 | 0.30 | 0.06 |

All five sit in a tight, low band with no excursions in this run, consistent with a healthy
rig — good baselines for a threshold set with real headroom rather than one backed into from a
single noisy sample.

---

## 5. Proposed new alarms

Six new rules, written in the same schema as the enforced §1.1 system
(`anomaly_thresholds.json`), so they can be dropped in as additional `sensors.<NAME>` entries
and a `correlation_rules[]` addition without inventing a seventh format. Two CRITICAL, four
WARNING — the user asked for at least one and three respectively.

Thresholds below are set with deliberate headroom above the observed range precisely *because*
of finding #1 in §4 (the rig wasn't thermally settled) — setting a static max at, say, 55°C for
`RTD_204` when this one-hour sample already reaches 53.85°C would false-alarm on routine warm-up
the next time the rig runs a few minutes longer. Numbers are chosen so a real fault (a bearing
genuinely overheating, not just the rig warming up) is what trips them.

### CRITICAL 1 — Main bearing overtemperature (`RTD_204`, `RTD_205`)

```json
"RTD_204": {
  "name": "Main Bearing Temp DE",
  "unit": "degC",
  "category": "temperature",
  "thresholds": {
    "STEADY_STATE": { "critical_min": 20.0, "warning_min": 25.0, "warning_max": 85.0, "critical_max": 100.0 }
  },
  "anomaly_rules": [
    { "type": "out_of_range", "enabled": true, "severity": "critical",
      "description": "Main bearing DE metal temperature exceeds babbitt-bearing thermal design limit" },
    { "type": "rapid_rise", "enabled": true, "severity": "critical",
      "rise_threshold_per_minute": 1.8, "duration_minutes": 5,
      "description": "Sustained rise >1.8C/min for 5 min, well above the 0.5-0.9C/min normal warm-up rate observed in the reference CSV -- flags an abnormal excursion, not routine warm-up" }
  ]
}
```

Same structure for `RTD_205` (NDE). **Rationale:** babbitt/white-metal journal bearings
conventionally carry a warning around 90°C and a trip around 100–105°C in steam-turbine practice
— the observed range here (41–54°C, still climbing) is far below that, consistent with a
partially-warmed rig, so 85/100 gives genuine headroom over both the CSV's observed max and its
extrapolated full-soak value, while still catching a real bearing-distress excursion. The
rapid-rise budget (1.8°C/min) is set just under the fastest sustained rate actually observed
(RTD_219A at 0.86°C/min) with roughly 2× margin — high enough that normal warm-up never trips it,
low enough to catch a genuine thermal runaway before it reaches the absolute limit.

### CRITICAL 2 — Generator winding overtemperature (`RTD_219A`, `RTD_219B`)

```json
"RTD_219A": {
  "name": "Generator Winding Temp A",
  "unit": "degC",
  "category": "temperature",
  "thresholds": {
    "STEADY_STATE": { "critical_min": 15.0, "warning_min": 20.0, "warning_max": 110.0, "critical_max": 130.0 }
  },
  "anomaly_rules": [
    { "type": "out_of_range", "enabled": true, "severity": "critical",
      "description": "Generator winding temperature approaching Class B insulation thermal limit (~130C)" }
  ]
}
```

Same structure for `RTD_219B`. **Rationale:** Class B insulation systems (a common rating for
this class of test/skid generator) carry a total temperature limit around 130°C; observed data
tops out at 51.8°C mid-warm-up. Setting warning at 110°C / critical at 130°C gives real headroom
for this short test window while still representing a genuine, industry-grounded insulation
limit rather than an arbitrary number over the observed range.

### WARNING 1 — Generator bearing DE/NDE divergence (`RTD_220` vs `RTD_221`)

```json
{
  "id": "generator_bearing_temp_corr",
  "name": "Generator Bearing DE/NDE Correlation",
  "description": "Drive-end and non-drive-end generator bearing temps should track; baseline divergence in reference data is 0.03-4.31C (p95 4.27C)",
  "sensor_pairs": ["RTD_220", "RTD_221"],
  "correlation_type": "should_track",
  "max_divergence": 6.0,
  "enabled": true,
  "severity": "warning"
}
```

**Rationale:** unlike the main bearing pair, generator DE/NDE has near-zero structural offset
(mean divergence 3.03°C, p95 4.27°C in the reference CSV) — a `should_track` rule fits directly.
6.0°C sits comfortably above the observed p95 so normal operation stays quiet, while a real
misalignment or single-bearing wear fault (which pushes one side hot and not the other) would
trip it.

### WARNING 2 — Cooling water ΔT collapse (computed, `RTD_202`/`RTD_203`)

```json
{
  "id": "cooling_water_delta_t_collapse",
  "name": "Cooling Water Heat Rejection Loss",
  "description": "Outlet (RTD_203) should run 8-20C colder than inlet (RTD_202) under normal heat rejection; if the gap collapses, the cooler isn't removing heat",
  "sensor_conditions": [
    { "sensor": "RTD_203", "operator": ">", "threshold": -5.0 }
  ],
  "enabled": true,
  "severity": "warning"
}
```

Note: the multi-sensor rule engine (§1.1) evaluates instantaneous latest values per sensor, not
arithmetic between two sensors, so implementing a true `RTD_203 - RTD_202` delta requires a small
extension to `_evaluate_condition()` (or precomputing the delta into a synthetic sensor key at
ingest). Documented here as a design intent; flag to whoever implements it that the current
engine can't express a two-sensor subtraction directly. **Rationale:** observed ΔT never comes
closer than −7.68°C to zero in this file; a warning threshold of −5.0°C (i.e., less than 5°C of
cooling) gives margin below the observed minimum gap while catching a real loss of coolant flow
or a fouled heat exchanger.

### WARNING 3 — Cooling water low pressure (`PT_201`)

```json
"PT_201": {
  "name": "Cooling Water Pressure",
  "unit": "kg/cm2",
  "category": "pressure",
  "thresholds": {
    "STEADY_STATE": { "critical_min": 1.0, "warning_min": 1.5, "warning_max": 2.5, "critical_max": 3.0 }
  },
  "anomaly_rules": [
    { "type": "out_of_range", "enabled": true, "severity": "warning",
      "description": "Cooling water supply pressure dropping toward pump/flow-loss territory" },
    { "type": "stuck_value", "enabled": true, "severity": "warning", "stuck_duration_seconds": 300 }
  ]
}
```

**Rationale:** the full file holds a tight 1.748–2.118 kg/cm² band. Warning at 1.5 sits just
below the observed minimum (a ~15% margin) so ordinary noise doesn't trip it, but a real pump
degradation or line blockage — which would show as a slow, sustained pressure decay — gets
caught before it becomes a cooling-loss event. The `stuck_value` rule doubles as a sensor-fault
check, since this channel's low natural variance means a genuinely frozen sensor would otherwise
be hard to distinguish from normal operation by eye.

### WARNING 4 — Vibration excursion on unmonitored radial probes (`XT_602`, `XT_603`, `XT_606`, `XT_607`, `ZT_601`)

```json
"XT_606": {
  "name": "Shaft Vibration X (Gearbox Rear)",
  "unit": "mills",
  "category": "vibration",
  "thresholds": {
    "STEADY_STATE": { "critical_min": 0.0, "warning_min": 0.05, "warning_max": 1.3, "critical_max": 2.0 }
  },
  "anomaly_rules": [
    { "type": "out_of_range", "enabled": true, "severity": "warning" },
    { "type": "rapid_increase", "enabled": true, "severity": "warning",
      "increase_threshold_percent": 75, "baseline_window_minutes": 10,
      "description": "75% jump vs 10-min baseline on a probe whose observed range in the reference CSV is only 0.18-0.67 mills -- catches incipient wear before an absolute limit would" }
  ]
}
```

Same pattern for `XT_607`, `XT_602`, `XT_603` (observed max 1.45–1.62, so scale warning_max to
~2× observed max, critical_max to ~3×) and `ZT_601` (observed range is negative, −38.16 to
−1.26 — use `abs(value)` semantics or mirror the bound: warning at magnitude 45, critical at
magnitude 60, following the same ~1.2–1.5× headroom-over-observed-max pattern used for `ZT_600`
elsewhere in this codebase). **Rationale:** these five channels currently have zero enforced
coverage anywhere (§3). Each sits in a tight, low-noise band in the reference CSV (std ≤0.14 for
the XT_60x pair, ≤1.28 for ZT_601) with no excursions — good conditions for a relative
`rapid_increase` rule, which (per the existing engine's own design intent, see
`ANOMALY_DETECTION.md` §4) catches proportional wear signatures long before an absolute limit
would, exactly the same logic already applied to `XT_600` in the enforced system.

---

## 6. Recommendations (not actioned by this document)

1. **Reconcile the six threshold systems**, or at minimum document which one is authoritative
   per sensor. Right now an operator reading the 3D widget's `XT_600` alarm-at-6.0 and the Kafka
   detector's `warning`-only-at-4.5 band could reasonably form two different mental models of
   the same channel.
2. **Fix or replace `anomaly_thresholds.json`'s `TT_109A`/`TT_110A`/`GB_TRQ` bands** before
   pointing the Kafka detector at this CSV — as shipped they would either permanently critical-
   alarm (`TT_109A`/`TT_110A`, off by ~150–200°C) or permanently warn (`GB_TRQ`, off by ~30×).
3. **Verify the `PT_153`/`PT_201` comparison logic** in `turbine-3d-babylon.js:1032-1034`
   (§1.6) — the descending-limit configuration for these two sensors looks inverted against an
   ascending-only comparison.
4. **Confirm which anomaly-detection entrypoint is deployed** — `anomaly_detection.py:run_detector()`
   vs. the apparently broken `anomaly_consumer.py` (§1.1) — before relying on either in
   production.
