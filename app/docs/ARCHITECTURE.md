# Architecture

## Overview

This is a wind turbine digital twin pipeline: synthetic per-turbine sensor
data is generated in real time for a 9-turbine fleet, streamed through
Kafka, and written into Apache IoTDB for time-series storage and Grafana
visualization.

```
                                                     +--------------------+
                                                     |   Grafana :13000   |
                                                     |  (apache-iotdb-    |
                                                     |   datasource       |
                                                     |   plugin, REST)    |
                                                     +----------+---------+
                                                                | REST :18080
                                                                v
+----------------+      +-------------------+          +--------------+
| 9x synthetic_  |      |  Kafka :19092     |          |    IoTDB     |
|    producer    | ---> |  turbine.telemetry| <------- |  :6667 (RPC) |
|  (1 container  |      |  .raw.v1          |  consume |  :18080(REST)|
|   per turbine, |      |                   |  batches | single-node  |
|   ~1 Hz)       |      |                   |          |              |
|  /health :810x |      |                   |          |              |
+----------------+      |  turbine.telemetry|  ------> +--------------+
                         |  .dlq             |     ^         insertTablet
                         +-------------------+     |
                                  ^                | kafka_consumer
                                  |                | /health :8001
                                  +----------------+
                          (Zookeeper :2181 coordinates Kafka)
```

## Components

### synthetic_producer (`app/src/synthetic_producer.py`)
One container per turbine (9 in total, see `app/config/fleet.json`).
Synthesises all 61 channels from the physical profiles in
`sensor_profiles.py`, driven by an operating-state machine, and emits one
JSON message per tick at `SAMPLE_INTERVAL_S` (default 1s) on
`turbine.telemetry.raw.v1`, keyed by `customer_id:turbine_id`. Each
turbine carries its own calibration bias and state phase, so no two
turbines emit identical data.

### Kafka + Zookeeper
Single-broker Kafka (`turbine.telemetry.raw.v1`, `turbine.telemetry.dlq`)
coordinated by a single Zookeeper instance. 24-hour log retention acts as
a buffer if IoTDB is temporarily unavailable -- the consumer can fall
behind and catch up rather than losing data, up to that window.

### kafka_consumer (`app/src/kafka_consumer.py`)
Consumes in batches (default 50 messages or 5s, whichever first),
validates each message's shape, and writes the batch to IoTDB with one
`insertTablet` call. Kafka offsets commit only after a successful IoTDB
write (manual commit), so a mid-batch crash replays those messages --
safe because IoTDB writes are upserts keyed on `(device, timestamp)`.
Writes to IoTDB go through a circuit breaker (`app/src/resilience.py`) so
an IoTDB outage fails fast instead of retrying every batch at full
timeout. Messages that fail validation or repeatedly fail to write go to
the `turbine.telemetry.dlq` topic instead of being silently dropped or
blocking the consumer forever.

### Apache IoTDB
Single-node (standalone) time-series database. Stores all 61 sensor
channels + `seq_no` under
`root.digitaltwin.<customer_id>.site1.<turbine_id>`. REST service
(port 18080) is what Grafana queries.

### Grafana
One org per customer, each with its own fleet dashboard, created over the
Grafana HTTP API by `scripts/setup_grafana_orgs.py` from the generated
definitions in `provisioning/dashboards/json/<customer_id>/`. No
dashboards are provisioned from disk. Dashboards query IoTDB through the
`apache-iotdb-datasource` plugin (auto-provisioned, see
`provisioning/datasources/iotdb.yml`).

## Data flow / schema

Measurement names like `PT_120` are emitted directly by the generator,
which builds them from the channel definitions in `sensor_profiles.py`.
The same fixed names (by construction, not by shared
code -- see the comment at the top of `MEASUREMENTS` in
`kafka_consumer.py`) form the measurement list the consumer
uses to build each `insertTablet` call, and the device template in
`app/config/iotdb-schema.sql`. All three must stay in lockstep; changing
one without the others silently breaks the pipeline.

## Why these design choices

- **Kafka in the middle** (rather than producer -> IoTDB directly):
  decouples ingestion rate from IoTDB write throughput, and gives a
  replay buffer if IoTDB is down.
- **Manual offset commit after IoTDB write succeeds**: the delivery
  guarantee is "at-least-once, safe under replay" rather than
  "at-most-once" -- correct here because IoTDB writes are idempotent
  upserts.
- **Circuit breaker on IoTDB writes**: without it, an extended IoTDB
  outage means every batch retries 3 times with exponential backoff
  before failing -- multiplying consumer lag. The breaker fails fast
  after 5 consecutive failures and only probes again every 30s.
- **DLQ instead of blocking**: a single malformed message or a
  permanently broken schema must not stall the whole topic.
