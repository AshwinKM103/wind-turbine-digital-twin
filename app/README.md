# app/ — Turbine Telemetry Pipeline

The Python half of the Wind Turbine Digital Twin stack. Two long-running services
share one Docker image:

```
9x synthetic_producer.py ──► Kafka ──► kafka_consumer.py ──► IoTDB ──► Grafana
   (1 msg/sec each)     turbine.telemetry.raw.v1   (batched writes)
```

**Producer** (`synthetic_producer.py`) runs one container per turbine — 9 in total,
defined by `config/fleet.json`. Each tick emits one JSON message with 61 sensor
readings synthesised from the physical profiles in `sensor_profiles.py`, driven by an
IDLE → RAMP_UP → STEADY_STATE → RAMP_DOWN state machine. Per-turbine calibration bias
and state phase mean no two turbines emit identical data. One full state cycle is
about 14 minutes at the default interval.

**Consumer** (`kafka_consumer.py`) buffers messages until it has 50 of them (or 5
seconds pass), then writes the whole batch to IoTDB in one `insertTablet` call.
Kafka offsets are committed manually and only after the IoTDB write succeeds, so a
crash mid-batch replays those messages rather than dropping them. Replays are safe:
IoTDB inserts are upserts, so re-writing a row overwrites it with identical values.

Messages that can't be written — malformed JSON, failed validation, or IoTDB errors
that survive all retries — go to the DLQ topic (`turbine.telemetry.dlq`) and the
offset is committed past them. The consumer never blocks forever on one bad record.

Both services run a tiny HTTP server on a background thread exposing `/health` and
`/ready` for Docker healthchecks.

A third module, **`anomaly_detection.py`**, consumes the same telemetry topic under
its own consumer group and publishes alerts to `turbine.anomaly.alerts.v1`. Its
detection engine is complete and covered by 27 unit tests, but it is not yet a
Compose service and needs a Python 3.12 base image to build — see
[`anomaly_detection.py`](#anomaly_detectionpy) below.

---

## Directory Structure

```
app/
├── Dockerfile              # python:3.11-slim, non-root (uid 1000), shared by both services
├── src/
│   ├── synthetic_producer.py # per-turbine synthetic telemetry → Kafka
│   ├── sensor_profiles.py    # physical profiles for the 61 channels
│   ├── kafka_consumer.py     # Kafka → IoTDB batch writer
│   ├── anomaly_detection.py  # Kafka → anomaly alerts (parallel consumer)
│   ├── config.py             # All env-var config, one class
│   ├── health_server.py      # /health and /ready endpoints
│   ├── logging_config.py     # JSON logging to stdout + rotating file
│   ├── resilience.py         # Circuit breaker for IoTDB writes
│   └── requirements.txt
├── config/
│   ├── iotdb-schema.sql          # Database, device template (62 measurements), TTL
│   └── anomaly_thresholds.json   # 8 sensors, state-aware bands, correlation rules
├── tests/                  # unit tests, no network needed
│   ├── test_synthetic_producer.py
│   ├── test_kafka_consumer.py
│   ├── test_anomaly_detection.py
│   └── test_resilience.py
├── logs/                   # bind-mounted to /app/logs in both containers
└── docs/                   # SETUP, ARCHITECTURE, API, DEPLOYMENT, TROUBLESHOOTING
```

`logs/` is read-write and shared by all containers; they append to the same
`app.log`, distinguished by the `service` field in each JSON line.

---

## Source Code

### `synthetic_producer.py`

| Function | What it does |
|---|---|
| `OperatingStateMachine.state_at(elapsed_s)` | Returns `(state, load_factor)` for a point in the IDLE → RAMP_UP → STEADY_STATE → RAMP_DOWN cycle. Load factor drives all 61 channels. |
| `TurbineSimulator.sample(elapsed_s)` | Produces `(state, {measurement: float})` for one tick, applying per-turbine bias, first-order lag and noise. |
| `build_producer()` | Reliability-first Kafka config: `acks=all`, `enable.idempotence`, effectively-infinite retries within a 120s delivery timeout, lz4 compression. |
| `build_payload(...)` | Assembles one Kafka message body, including the additive `operating_state` field. |

Failure handling in the loop: a `BufferError` (local queue full, broker slow) polls
for a second and retries the *same* sample. Any other produce exception backs off
exponentially up to 30s, also retrying the same sample. Samples are never silently
skipped. SIGINT/SIGTERM sets a flag; the loop finishes its tick, flushes for up to
30s, and exits.

### `kafka_consumer.py`

`MEASUREMENTS` (62 entries: 61 sensors + `seq_no`) and `DATA_TYPES` are hardcoded
lists that **must stay in the same order as `config/iotdb-schema.sql`'s device
template**. An `assert` at import time catches length mismatch, not ordering — get
the order wrong and you'll silently write pressure values into a temperature series.

| Function | What it does |
|---|---|
| `validate_payload(payload)` | Trust boundary check. Raises `ValueError` if not a dict, missing any of `event_time_ms` / `customer_id` / `turbine_id` / `seq_no`, if `metrics` isn't an object, or if `event_time_ms` isn't numeric. |
| `payload_to_row(payload)` | Returns `(timestamp_ms, values)` aligned to `MEASUREMENTS` order. Missing or unparseable metrics become `None` (IoTDB tablets support null cells via a bitmap). |
| `build_iotdb_session(health)` | Loops forever with capped exponential backoff until IoTDB accepts a connection. This is why the consumer doesn't crash-loop when IoTDB is slow to start. |
| `flush_batch_to_iotdb(...)` | One `insertTablet` through the circuit breaker, retried `IOTDB_WRITE_MAX_RETRIES` times with exponential backoff. Returns `True`/`False`. |
| `send_to_dlq(...)` | Republishes raw message bytes to the DLQ topic with a `failure_reason` header. |

### `anomaly_detection.py`

A third service, complete and unit-tested but not yet in `docker-compose.yml`. It
consumes the same telemetry topic as `kafka_consumer.py` under its own group
(`anomaly-detector-group`), so it neither steals messages from the writer nor
delays IoTDB writes. Alerts are published to `turbine.anomaly.alerts.v1`.

| Function | What it does |
|---|---|
| `AnomalyDetector.process_reading(reading)` | Appends to the per-sensor rolling window (`deque(maxlen=3600)`), returns early if the sensor is in a grace period, then runs all seven detectors. Each runs inside its own `try`/`except` so one bad rule cannot silence the rest. Returns a list of `Alert`. |
| `_infer_turbine_state(customer, turbine)` | Latest `TURBINE_SPEED_RPM` → `IDLE` (<500), `RAMP_UP` (500–11000), `STEADY_STATE` (11000–12500), `RAMP_DOWN` (>12500). Defaults to `STEADY_STATE` — the tightest bands — when no RPM has been seen. |
| `_detect_out_of_range` | State-aware band check. The only detector that varies by turbine state. |
| `_detect_stuck_value` | Flags when >80% of the readings in `stuck_duration_seconds` are within 0.001 of the current value. |
| `_detect_rapid_rise` | Absolute rise over a window, one-directional. A rapid *fall* never fires. |
| `_detect_rapid_increase` | Percentage rise against the rolling window mean. Catches vibration climbing above its own norm while still inside its absolute band. Guards division by zero. |
| `_detect_drift` | Absolute movement past 1.5× the hourly budget. Needs 60 readings and 10 minutes. |
| `_detect_correlation_break` | Divergence between a `sensor_pairs` couple past `max_divergence`. Only `correlation_type: "should_track"` is dispatched; `should_correlate` loads and is ignored. |
| `_check_multi_sensor_conditions` | AND across a rule's `sensor_conditions`. Short-circuits on the first false condition and fails closed when a named sensor has no history. |
| `_create_alert(...)` | The gate between detection and publication. Increments a count keyed on `(customer, turbine, sensor, detection_type)` and returns `None` until `confirmation_count` is reached, then opens a grace period and returns the `Alert`. |

Two behaviours worth knowing before tuning. The confirmation counter is keyed per
detection type, but the grace period it opens is keyed on the **sensor alone** —
so the first confirmed alert on a sensor suppresses every other detection type on
that sensor for `grace_period_minutes`. And `severity` in config is honoured only
by `rapid_increase`, `correlation_break`, and `multi_sensor`; the other four
hardcode it.

**Not yet deployable as-is.** `docker-compose.yml` defines six services and does
not include the detector, and `app/Dockerfile` builds on `python:3.11-slim` while
the multi-sensor alert message at `anomaly_detection.py:695` nests same-quoted
subscripts inside an f-string — valid only on Python 3.12+ ([PEP 701](https://peps.python.org/pep-0701/)).
On 3.11 it raises `SyntaxError: f-string: unmatched '['` at import. Bump the base
image or hoist that expression into a variable before building a detector image.

Full behaviour, configuration reference, and scenarios:
[`docs/ANOMALY_DETECTION.md`](docs/ANOMALY_DETECTION.md).

### `config.py`

One `Config` class, all class attributes read from `os.environ` at import time.
Typed getters (`_get_int`, `_get_float`) raise a clear `ValueError` naming the
variable if you set something unparseable. Calls `load_dotenv()` if `python-dotenv`
is installed, which is how running outside Docker picks up the root `.env`.

### `health_server.py`

`start_health_server(port, service_name)` binds `0.0.0.0:port` on a daemon thread and
returns a `HealthState`. Call `state.set_check(name, ok, detail)` and
`state.set_ready(bool)` from the main loop.

- `GET /health` — always 200 once bound. Liveness only, no I/O.
- `GET /ready` — 200 if ready and every check is `ok`, else 503 with the failing checks.

Producer checks: `simulator_ready`, `kafka_reachable`. Consumer checks:
`kafka_connected`, `iotdb_connected`.

### `logging_config.py`

`configure_logging(service)` sets up JSON-per-line output to stdout (for `docker logs`)
and to `$LOG_DIR/app.log` with midnight rotation, 10 gzipped backups. Every record
carries `timestamp`, `level`, `service`, `request_id`, `message`. Anything you pass in
`extra={...}` is merged into the JSON object, so use that instead of f-strings:

```python
log.info("Flushed batch to IoTDB", extra={"records": len(batch)})
```

### `resilience.py`

Standard three-state circuit breaker (`CLOSED → OPEN → HALF_OPEN → CLOSED`), thread-safe.
Wrap a call with `breaker.call(fn, *args)`. After `failure_threshold` consecutive
failures it opens and raises `CircuitBreakerOpenError` immediately instead of waiting
out full timeouts on a database that's down. After `reset_timeout_s` it allows one
trial call.

---

## Configuration

Everything comes from environment variables. Nothing is hardcoded, so the same image
runs in dev and prod — only the `.env` changes.

**Precedence** (highest wins):

1. `environment:` block in `docker-compose.yml` for that service
2. `env_file: .env` at the repo root
3. Defaults in `src/config.py`

Compose deliberately overrides a few values per service: each generator gets its
`CUSTOMER_ID`/`TURBINE_ID` and its own `HEALTH_CHECK_PORT` (8101+), the consumer gets
`IOTDB_HOST=iotdb` and `HEALTH_CHECK_PORT=8001`. Both get `KAFKA_BOOTSTRAP_SERVERS_INTERNAL=kafka:29092`.

`KAFKA_BOOTSTRAP_SERVERS_INTERNAL` wins over `KAFKA_BOOTSTRAP_SERVERS` when set. That's
the container-network address (`kafka:29092`); the plain variable is the host-facing
one (`localhost:19092`) used when you run the scripts outside Docker.

### Kafka

| Variable | Default | Notes |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS_INTERNAL` | *(unset)* | Container-network broker. Takes precedence if set. |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:19092` | Host-facing broker (port 19092, not 9092, to avoid clashing with other local Kafkas). |
| `KAFKA_TOPIC` | `turbine.telemetry.raw.v1` | |
| `KAFKA_GROUP_ID` | `iotdb-writer-group` | Change this to replay the topic from the beginning. |
| `DLQ_TOPIC` | `turbine.telemetry.dlq` | |

### IoTDB

| Variable | Default | Notes |
|---|---|---|
| `IOTDB_HOST` | `iotdb` | Use `localhost` when running outside Docker. |
| `IOTDB_PORT` | `6667` | Native RPC (Session API), not the 18080 REST port. |
| `IOTDB_USER` / `IOTDB_PASSWORD` | `root` / `root` | Change before any non-local deployment. |

### Device topology

| Variable | Default |
|---|---|
| `CUSTOMER_ID` | `customer1` |
| `TURBINE_ID` | `turbine01` |
| `DEVICE_PATH` | `root.digitaltwin.{CUSTOMER_ID}.site1.{TURBINE_ID}` |

`DEVICE_PATH` is derived from the other two, so setting just `TURBINE_ID=turbine02`
is enough to write to a different device. Set `DEVICE_PATH` explicitly only if you
need a different site or hierarchy shape.

### Producer tuning

| Variable | Default | Notes |
|---|---|---|
| `SAMPLE_INTERVAL_S` | `1.0` | Seconds between messages. Also scales the synthetic timestamps. |

### Consumer tuning

| Variable | Default | Notes |
|---|---|---|
| `BATCH_SIZE` | `50` | Records per `insertTablet`. |
| `BATCH_MAX_WAIT_S` | `5.0` | Flush a partial batch after this long. |
| `IOTDB_WRITE_MAX_RETRIES` | `3` | Then the batch goes to the DLQ. |
| `IOTDB_WRITE_BACKOFF_BASE_S` | `0.2` | Doubles per attempt. |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `5` | Consecutive failures before opening. |
| `CIRCUIT_BREAKER_RESET_TIMEOUT_S` | `30.0` | Cooldown before the half-open trial. |

### Runtime

| Variable | Default | Notes |
|---|---|---|
| `HEALTH_CHECK_PORT` | `8000` | Compose sets 8000 (producer) / 8001 (consumer). |
| `LOG_DIR` | `./logs` | `/app/logs` in containers. |
| `LOG_LEVEL` | `INFO` | `DEBUG` in the checked-in dev `.env`. |

> **Note:** `.env.example` at the repo root does not currently list the producer and
> consumer tuning knobs above. They fall back to the `config.py` defaults unless you
> add them yourself.

---

## Running

### Full stack (normal case)

From the repo root, not from `app/`:

```bash
cd "/home/ashwinkm/Digital Twins/Apache_IOTDB"
cp .env.example .env          # first time only
docker compose up -d --build
```

Load the IoTDB schema once, after IoTDB reports healthy:

```bash
docker exec -i iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 -u root -pw root \
  -e "$(cat app/config/iotdb-schema.sql)"
```

Verify the pipeline is moving:

```bash
curl -s localhost:8000/ready | python3 -m json.tool   # producer
curl -s localhost:8001/ready | python3 -m json.tool   # consumer
docker compose logs -f producer consumer
```

Confirm rows are landing:

```bash
docker exec -i iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 -u root -pw root \
  -e "SELECT last GB_TRQ, TURBINE_SPEED_RPM FROM root.digitaltwin.customer1.site1.turbine01"
```

Rebuild after a code change (both services share one image):

```bash
docker compose up -d --build producer consumer
```

### One service at a time

```bash
docker compose up -d zookeeper kafka iotdb
docker compose up -d consumer      # start the writer first
docker compose up -d producer      # then the source
docker compose stop producer       # pause data generation, keep the DB up
```

### Locally, outside Docker

Useful when you want a debugger attached. Infrastructure still runs in Docker.

```bash
cd "/home/ashwinkm/Digital Twins/Apache_IOTDB"
docker compose up -d zookeeper kafka iotdb

python3 -m venv .venv && source .venv/bin/activate
pip install -r app/src/requirements.txt

export KAFKA_BOOTSTRAP_SERVERS=localhost:19092
unset KAFKA_BOOTSTRAP_SERVERS_INTERNAL     # otherwise kafka:29092 wins and won't resolve
export IOTDB_HOST=localhost
export LOG_DIR=/tmp/turbine-logs
export LOG_LEVEL=DEBUG

cd app/src
CUSTOMER_ID=customer1 TURBINE_ID=turbine01 HEALTH_CHECK_PORT=8000 python synthetic_producer.py &
HEALTH_CHECK_PORT=8001 python kafka_consumer.py
```

Stop the containerized producer/consumer first (`docker compose stop producer consumer`)
or you'll have two producers writing to the same topic and two consumers in the same
group.

To cycle the state machine fast for testing, drop the interval:

```bash
SAMPLE_INTERVAL_S=0.01 python synthetic_producer.py
```

---

## Testing

53 unit tests. No Kafka, IoTDB, or network required. They run in under a second.

**Run from the repository root, not from `app/`.** The anomaly fixture builds
`AnomalyDetector("app/config/anomaly_thresholds.json")` with a path relative to
the working directory, so the 27 anomaly tests fail collection with
`FileNotFoundError` from anywhere else.

```bash
cd "/home/ashwinkm/Digital Twins/Apache_IOTDB"
pip install pytest
LOG_DIR=/tmp/turbine-test-logs python3 -m pytest app/tests -q
```

```
.....................................................                    [100%]
53 passed in 0.70s
```

One file at a time:

```bash
LOG_DIR=/tmp/turbine-test-logs python3 -m pytest app/tests/test_anomaly_detection.py -q
# 27 passed in 0.09s
```

**The `LOG_DIR` override is not optional.** Importing any service module calls
`configure_logging()` at import time, which opens `$LOG_DIR/app.log` for append. That
file is created by the container as a different uid, so pytest without the override
dies at collection with `PermissionError: [Errno 13]`. Point `LOG_DIR` at a directory
you own.

`test_anomaly_detection.py` constructs a real Kafka `Producer` per fixture. It is never
flushed, but `librdkafka` still logs `Failed to resolve 'kafka:29092'` to stderr during
the run. Those lines are expected and do not affect the result.

With coverage:

```bash
pip install pytest-cov
LOG_DIR=/tmp/turbine-test-logs python3 -m pytest app/tests \
  --cov=app/src --cov-report=term-missing
```

### What's covered

| File | Tests | Covers |
|---|---|---|
| `test_synthetic_producer.py` | | State machine transitions and load factors, per-turbine bias and determinism under a fixed seed, payload shape and device-path derivation. |
| `test_kafka_consumer.py` | | `validate_payload` (all five rejection paths) and `payload_to_row` (measurement alignment, missing metrics → `None`, `seq_no` stays int, malformed value → `None` not exception). |
| `test_resilience.py` | | Full circuit breaker state machine including half-open recovery, half-open re-open, and failure-count reset on success. |
| `test_anomaly_detection.py` | 27 | All seven detection methods, state inference across all four states, confirmation counts, grace periods, telemetry parsing, and alert serialization. |

The three files above `test_anomaly_detection.py` total 26 tests.

Notable anomaly cases, both positive and negative — every detector is tested for
what it must *not* alert on as well as what it must catch:

| Test | Asserts |
|---|---|
| `test_infers_steady_from_high_rpm` | 12000 RPM → `STEADY_STATE`, not `RAMP_DOWN` |
| `test_rapid_increase_detection_vibration` | `XT_600` 2.30 → 3.50 mm/s (+52.2%) is detected while still inside its absolute band |
| `test_does_not_alert_on_small_increase` | 2.30 → 2.40 (+4.3%) stays quiet |
| `test_multi_sensor_condition_detection_gearbox` | `TT_109A > 85` AND `XT_600 > 4.0` both true → one `multi_sensor` alert |
| `test_multi_sensor_not_alerted_when_only_one_condition_met` | One condition true → no alert |
| `test_requires_confirmation_count` | Nothing published before the third detection |
| `test_grace_period_suppresses_duplicate_alerts` | Second alert within the window is dropped |

### What isn't covered

The I/O loops — `run_simulator()`, `run_consumer()`, `build_iotdb_session()`,
`send_to_dlq()`, `run_detector()`, `publish_alert()`, and the health server. Also
the `should_correlate` correlation type, which has no implementation to test.
Verify those by hand against the running stack (see Running above).

---

## Adding New Features

### A new sensor channel

The measurement list exists in three places and they must agree in **name, order, and
type**. Change all three in one commit.

1. **`src/sensor_profiles.py`** — add a `SensorProfile` for the channel, using the
   exact measurement identifier (e.g. `NEW_PT_300`) you want in IoTDB.
2. **`config/iotdb-schema.sql`** — add the measurement to `CREATE DEVICE TEMPLATE
   turbine_template`, at the same position, `FLOAT GORILLA SNAPPY` for continuous
   numeric series.
3. **`src/kafka_consumer.py`** — append the name to `MEASUREMENTS` and its type to
   `DATA_TYPES` at the matching index. Bump the count in the `assert` on line 72.
4. **Test** — add a case to `TestSanitizeMeasurementName` if the header format is new.
5. **Recreate the schema.** IoTDB device templates aren't editable in place. On a dev
   box: `DELETE TIMESERIES root.digitaltwin.**` and reload the SQL. On anything with
   data you care about, export first.
6. **Update** `/home/ashwinkm/Digital Twins/Apache_IOTDB/SENSOR_IDS.md`.

Sanity check after deploying — the count should match your new total:

```bash
docker exec -i iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 -u root -pw root \
  -e "SHOW TIMESERIES root.digitaltwin.customer1.site1.turbine01.**" | wc -l
```

### A new turbine

The template is set on the wildcard path `root.digitaltwin.customer1.site1`, so new
turbines inherit the schema on first write. Run a second producer with
`TURBINE_ID=turbine02` and a second consumer with a distinct `KAFKA_GROUP_ID`.

### A new config knob

Add it to `Config` in `config.py` using `_get_int` / `_get_float` (never bare
`os.environ` for typed values — you lose the validation error), document it in
`.env.example`, and add it to the Configuration table above.

### A new health check

```python
health.set_check("my_dependency", False, "not yet attempted")   # before the loop
health.set_check("my_dependency", True, "connected")            # once it succeeds
```

Any failing check flips `/ready` to 503, which flips the Docker healthcheck. Don't
register checks for things whose failure shouldn't stop traffic.

### A new metric or log field

Pass it through `extra=`, not string formatting, so it lands as a queryable JSON field:

```python
log.info("Batch flushed", extra={"records": n, "duration_ms": elapsed})
```

---

## Troubleshooting

### Consumer restarts in a loop

Check what its readiness probe says:

```bash
curl -s localhost:8001/ready | python3 -m json.tool
docker compose logs --tail=50 consumer
```

`iotdb_connected: fail` right after startup is normal for the first ~30 seconds —
`build_iotdb_session` backs off and retries. If it persists, IoTDB itself is the
problem: `docker compose logs iotdb`.

### Producer is healthy but nothing reaches IoTDB

Is the topic actually receiving messages?

```bash
docker exec turbine-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic turbine.telemetry.raw.v1 \
  --max-messages 1 --from-beginning
```

If yes, look at the DLQ — batches that failed to write end up there:

```bash
docker exec turbine-kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic turbine.telemetry.dlq \
  --max-messages 5 --from-beginning --property print.headers=true
```

The `failure_reason` header tells you which path it took: `validation_failed` means a
malformed message, `iotdb_write_failed_after_retries` means IoTDB rejected the batch —
almost always a schema mismatch between `MEASUREMENTS` and the device template.

### `PermissionError` on `logs/app.log` when running pytest

The container writes that file as a different uid. Set `LOG_DIR` to a directory you
own, as shown in Testing. Don't `chmod 777` the log directory — the file inside is the
problem, not the directory.

### `FileNotFoundError: 'app/config/anomaly_thresholds.json'` when running pytest

You ran pytest from `app/`. The anomaly fixture uses a path relative to the working
directory. Run from the repository root: `python3 -m pytest app/tests -q`.

### `SyntaxError: f-string: unmatched '['` importing `anomaly_detection`

The interpreter is older than 3.12. Line 695 nests same-quoted subscripts inside an
f-string, which requires PEP 701. Relevant when building the detector image, since
`Dockerfile` is on `python:3.11-slim`.

### `kafka:29092` won't resolve

You're running outside Docker with `KAFKA_BOOTSTRAP_SERVERS_INTERNAL` still set from
the `.env`. `unset KAFKA_BOOTSTRAP_SERVERS_INTERNAL` and use `localhost:19092`.

### Circuit breaker keeps opening

```bash
docker compose logs consumer | grep -i circuit
```

Five consecutive failed batches opens it for 30 seconds. If it's cycling
OPEN → HALF_OPEN → OPEN, the write itself is broken, not the connection — check the
`IoTDB insert_tablet failed` error text just above. A type or ordering mismatch
between `DATA_TYPES` and the device template shows up here.

### Duplicate or overwritten timestamps

Expected on restart. The producer anchors `base_wallclock_ms` at process start, so a
restart re-emits timestamps near the current wall clock. IoTDB upserts on
`(device, timestamp)`, so those rows are overwritten, not duplicated. To keep a clean
run, stop the producer before clearing data rather than after.

### `apache-iotdb` won't install

The PyPI package is `apache-iotdb`, imported as `iotdb`. A bare `pip install iotdb`
installs something else entirely. Use `pip install -r app/src/requirements.txt`.

### Reset everything

```bash
cd "/home/ashwinkm/Digital Twins/Apache_IOTDB"
docker compose down
sudo rm -rf data/kafka data/zookeeper data/iotdb
docker compose up -d --build
# then reload the schema
```

---

## Performance Tuning

Default throughput is ~1 message/sec — deliberately slow, matching the source data's
sampling rate. Nothing here is near a bottleneck at that rate.

### Throughput

`SAMPLE_INTERVAL_S` is the only producer lever. `0.1` gives 10 Hz, `0.01` gives 100 Hz.
Below roughly 0.005 the `time.sleep()` loop itself becomes the limit and you'll want a
different generation strategy.

Note that this variable also scales synthetic timestamps: at `SAMPLE_INTERVAL_S=0.1`,
one state cycle spans about 1.4 simulated minutes instead of 14.

### Batching

`BATCH_SIZE` and `BATCH_MAX_WAIT_S` trade write efficiency against freshness. Whichever
triggers first flushes the batch.

| Goal | `BATCH_SIZE` | `BATCH_MAX_WAIT_S` |
|---|---|---|
| Low latency (dashboards feel live) | 10 | 1.0 |
| Balanced (default) | 50 | 5.0 |
| High throughput (bulk backfill) | 500–1000 | 10.0 |

At 1 Hz with the defaults, `BATCH_MAX_WAIT_S` is what actually fires — you get a flush
every 5 seconds carrying 5 records, never a full batch of 50. Raising `BATCH_SIZE`
alone changes nothing until the ingest rate goes up. If you want fewer, larger writes
at 1 Hz, raise `BATCH_MAX_WAIT_S`.

Memory per batch is small: 62 floats plus overhead, roughly 1 KB per record. Even
`BATCH_SIZE=1000` is about a megabyte.

### Kafka producer

The settings in `build_producer()` favour durability. If you need raw throughput and
can tolerate loss:

- `linger.ms` 20 → 100 batches more aggressively at the cost of latency
- `batch.size` 65536 → 262144 for larger network writes
- `acks=all` → `acks=1` is the big win, and the big risk. Don't.

Leave `enable.idempotence=True`. It costs almost nothing and is what makes retries safe.

### Parallelism

The topic has 6 partitions but the producer keys every message on
`customer_id:turbine_id`, so all traffic for one turbine lands on one partition and
adding consumer instances won't help. Scaling out means more turbines (more keys),
not more consumers per turbine.

### Retry and breaker timing

Raise `IOTDB_WRITE_MAX_RETRIES` and `IOTDB_WRITE_BACKOFF_BASE_S` if IoTDB has slow GC
pauses under load — the default 3 retries at 0.2s base gives up after roughly 0.6
seconds of backoff, which is tight for a stop-the-world pause. Raise
`CIRCUIT_BREAKER_RESET_TIMEOUT_S` above 30s if IoTDB restarts take longer than that,
so the breaker isn't retrying into a database that's still coming up.

### Logging

`LOG_LEVEL=DEBUG` at high sample rates produces a lot of JSON. The checked-in dev
`.env` sets `DEBUG`; use `INFO` for anything sustained. Rotation is daily with 10
gzipped backups, so disk growth is bounded but the current day's file is not.

---

## See Also

- [`docs/SETUP.md`](docs/SETUP.md) — first-run walkthrough
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design decisions and data flow
- [`docs/API.md`](docs/API.md) — health endpoint reference
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — production checklist
- [`docs/ANOMALY_DETECTION.md`](docs/ANOMALY_DETECTION.md) — detection methods, thresholds, scenarios
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — stack-wide issues
- [`../SENSOR_IDS.md`](../SENSOR_IDS.md) — all 61 channels with descriptions
