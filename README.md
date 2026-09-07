# Wind Turbine Digital Twin

A multi-tenant wind turbine fleet simulator. It generates realistic turbine telemetry, streams it through Kafka, persists it as time-series data in Apache IoTDB, and serves per-customer dashboards in Grafana. Each customer's data is isolated at the storage level and rendered in its own Grafana organization, so this doubles as a reference architecture for multi-tenant IoT/time-series pipelines.

## Architecture

```
Turbine Generators (Python, one process per turbine)
        │  synthetic telemetry (JSON)
        ▼
      Kafka
        │  consumed & batched
        ▼
  Kafka Consumer ──────────────► IoTDB (time-series storage)
        │                              │
        ▼                              ▼
Anomaly Detector                  Grafana (per-customer orgs & dashboards)
  (parallel consumer,
   logs alerts)
```

Each turbine writes to a unique IoTDB device path derived from fleet topology:

```
root.digitaltwin.<customer_id>.<site_id>.<turbine_id>
```

A customer's Grafana datasource is scoped to `root.digitaltwin.<customer_id>.*`, so one customer can never see another's data.

## Quick start

Requires Docker and Docker Compose.

```bash
# 1. Clone and configure
git clone <repo-url> wind-turbine-digital-twin
cd wind-turbine-digital-twin
cp .env.example .env

# 2. Start the stack (Zookeeper, Kafka, IoTDB, Grafana, generators, consumer, anomaly detector)
docker compose up -d --build

# 3. Wait for services to report healthy
docker compose ps

# 4. Provision Grafana organizations, datasources, dashboards, and per-customer logins
python scripts/setup_grafana_orgs.py
```

Open Grafana at [http://localhost:13000](http://localhost:13000):

- Admin login: `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` from `.env` (defaults to `admin` / `admin`)
- Customer logins: `<customer_id>@company.com` / `CUSTOMER_USER_PASSWORD` from `.env`, scoped to that customer's org

Other useful endpoints:

| Service | URL |
|---|---|
| Grafana | http://localhost:13000 |
| IoTDB REST API (health check) | http://localhost:18080/ping |
| IoTDB session RPC | localhost:6667 |
| Kafka (external) | localhost:19092 |

To stop everything:

```bash
docker compose down
```

## How it works

| Component | File(s) | Responsibility |
|---|---|---|
| Turbine generator | `app/src/synthetic_producer.py` | Simulates one turbine's operating state machine (idle → ramp-up → steady → ramp-down) and publishes telemetry to Kafka at a configurable sample rate |
| Sensor profiles | `app/src/sensor_profiles.py` | Defines the physical sensor model (wind speed, RPM, power output, temperature, vibration) used to generate realistic values per state |
| Kafka consumer | `app/src/kafka_consumer.py` | Consumes telemetry, batches records, writes them to IoTDB with retry and circuit-breaker protection; routes unprocessable messages to a dead-letter topic |
| Resilience | `app/src/resilience.py` | Exponential backoff and circuit breaker used by the consumer's IoTDB writes |
| Anomaly detector | `app/src/anomaly_consumer.py`, `app/src/anomaly_detection.py` | Parallel Kafka consumer that flags out-of-range telemetry and logs structured alerts |
| Fleet loader | `app/src/fleet.py` | Typed loader/validator for `app/config/fleet.json`; the single source of truth every generation script and test reads from |
| Config loader | `app/src/config.py` | Centralized environment variable loading and type conversion for all Python services |
| Health server | `app/src/health_server.py` | Exposes `/ready` per generator container for Docker health checks |
| Grafana provisioning | `scripts/setup_grafana_orgs.py` | Idempotent script that creates/reconciles one Grafana org, datasource, dashboard, and login per customer via the Grafana API |

## Customizing the fleet

Fleet topology — customers, sites, turbines, and their Grafana tenancy — lives entirely in `app/config/fleet.json`. Nothing else needs to be hand-edited; docker-compose services, the IoTDB schema, and Grafana assets are all generated from it.

### Add a turbine to an existing customer

Edit `app/config/fleet.json`:

```jsonc
{
  "customer_id": "customer1",
  "display_name": "Customer1",
  "grafana_org_id": 2,
  "grafana_login": "customer1@company.com",
  "datasource_uid": "iotdb-customer1",
  "dashboard_uid": "customer1-fleet",
  "sites": [
    {
      "site_id": "site1",
      "turbines": [
        { "turbine_id": "turbine01", "health_port": 8101 },
        { "turbine_id": "turbine02", "health_port": 8102 },
        { "turbine_id": "turbine10", "health_port": 8110 }  // new
      ]
    }
  ]
}
```

### Add a new customer

Append a new entry to the `customers` array with a unique `customer_id`, `grafana_org_id`, and at least one site/turbine:

```jsonc
{
  "customer_id": "customer4",
  "display_name": "Customer4",
  "grafana_org_id": 5,
  "grafana_login": "customer4@company.com",
  "datasource_uid": "iotdb-customer4",
  "dashboard_uid": "customer4-fleet",
  "sites": [
    {
      "site_id": "site1",
      "turbines": [
        { "turbine_id": "turbine11", "health_port": 8111 }
      ]
    }
  ]
}
```

`health_port` and `grafana_org_id` must be unique across the entire fleet file.

### Regenerate and deploy

```bash
# 1. Regenerate the docker-compose generator services block
python app/tools/generate_compose_generators.py

# 2. Regenerate the IoTDB schema (timeseries/templates for new device paths)
python app/tools/generate_fleet_schema.py

# 3. Regenerate Grafana dashboards/datasources for the fleet
python app/tools/generate_grafana_assets.py

# 4. Bring up the new/changed containers
docker compose up -d --build

# 5. Provision the new Grafana org(s), datasource(s), and login(s)
python scripts/setup_grafana_orgs.py
```

### Tune generator behavior

State durations and sample rate are set in `.env` and apply to every generator:

```bash
SAMPLE_INTERVAL_S=1.0            # seconds between telemetry samples
STATE_IDLE_DURATION_S=60
STATE_RAMP_UP_DURATION_S=120
STATE_STEADY_DURATION_S=600
STATE_RAMP_DOWN_DURATION_S=90
```

## Configuration reference

All configuration lives in `.env` (copy from `.env.example`). Values are consumed either by `docker-compose.yml` directly or by `app/src/config.py` at process start.

### IoTDB

| Variable | Default | Description |
|---|---|---|
| `IOTDB_VERSION` | `1.3.3-standalone` | Docker image tag for the IoTDB container |
| `IOTDB_DATA_PATH` | `./data/iotdb/data` | Host path for time-series data persistence |
| `IOTDB_LOGS_PATH` | `./data/iotdb/logs` | Host path for IoTDB logs |
| `IOTDB_HOST` | `localhost` | Hostname the consumer and Grafana connect to |
| `IOTDB_PORT` | `6667` | IoTDB session RPC port |
| `IOTDB_USER` / `IOTDB_PASSWORD` | `root` / `root` | IoTDB credentials |

### Kafka

| Variable | Default | Description |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:19092` | Broker address for clients running outside Docker |
| `KAFKA_BOOTSTRAP_SERVERS_INTERNAL` | `kafka:29092` | Broker address for clients running inside the Docker network |
| `KAFKA_TOPIC` | `turbine.telemetry.raw.v1` | Topic generators publish to |
| `DLQ_TOPIC` | `turbine.telemetry.dlq` | Dead-letter topic for unprocessable messages |
| `KAFKA_GROUP_ID` | `iotdb-writer-group` | Consumer group ID for the IoTDB writer |

### Generator tuning

| Variable | Default | Description |
|---|---|---|
| `SAMPLE_INTERVAL_S` | `1.0` | Seconds between telemetry samples per turbine |
| `PRODUCE_LOG_EVERY_N` | `30` | Log one "produced" line every N samples |
| `STATE_IDLE_DURATION_S` | `60` | Seconds spent idle before ramping up |
| `STATE_RAMP_UP_DURATION_S` | `120` | Seconds spent ramping up to steady state |
| `STATE_STEADY_DURATION_S` | `600` | Seconds spent at steady-state output |
| `STATE_RAMP_DOWN_DURATION_S` | `90` | Seconds spent ramping down before idling |

`CUSTOMER_ID`, `SITE_ID`, and `TURBINE_ID` are turbine identity and must **not** be set globally in `.env` — they're injected per generator container by `app/tools/generate_compose_generators.py` based on `app/config/fleet.json`. Setting them globally causes every generator to write to the same device path.

### Consumer tuning and resilience

| Variable | Default | Description |
|---|---|---|
| `BATCH_SIZE` | `50` | Rows buffered before flushing to IoTDB |
| `BATCH_MAX_WAIT_S` | `5.0` | Max seconds to wait before flushing a partial batch |
| `IOTDB_WRITE_MAX_RETRIES` | `3` | Retry attempts on a failed IoTDB write |
| `IOTDB_WRITE_BACKOFF_BASE_S` | `0.2` | Base delay for exponential backoff between retries |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `5` | Consecutive failures before the circuit opens |
| `CIRCUIT_BREAKER_RESET_TIMEOUT_S` | `30.0` | Seconds before a half-open retry after the circuit opens |

### Grafana

| Variable | Default | Description |
|---|---|---|
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | `admin` / `admin` | Admin credentials for Grafana and `setup_grafana_orgs.py` |
| `CUSTOMER_USER_PASSWORD` | `customer123` | Shared login password assigned to every customer user by `setup_grafana_orgs.py` |

### Docker networking

| Variable | Default | Description |
|---|---|---|
| `IOTDB_SUBNET` | `172.20.0.0/16` | Docker bridge subnet; override only if it conflicts with an existing network |
| `IOTDB_GATEWAY` | `172.20.0.1` | Gateway IP for the Docker bridge |

## Testing

```bash
pip install -r app/src/requirements.txt
pytest app/tests/ -v
```

Key test files:

| File | Covers |
|---|---|
| `test_fleet.py` | Fleet topology loading and schema validation |
| `test_multi_customer_e2e.py` | Data isolation across customers, end to end |
| `test_multi_turbine_routing.py` | Turbine-to-device-path routing |
| `test_synthetic_producer.py` | Generator state machine and telemetry output |
| `test_kafka_consumer.py` | Batching, retry, and dead-letter behavior |
| `test_anomaly_detection.py` | Anomaly detection thresholds and alert output |
| `test_resilience.py` | Backoff and circuit breaker logic |

## Project structure

```
.
├── docker-compose.yml              # Service definitions for the full stack
├── .env.example                    # All runtime configuration
├── app/
│   ├── config/fleet.json           # Customer/site/turbine topology (source of truth)
│   ├── src/                        # Producer, consumer, anomaly detector, shared config/fleet loaders
│   ├── tools/generate_*.py         # Compose, IoTDB schema, and Grafana asset generators
│   └── tests/                      # Test suite
├── scripts/setup_grafana_orgs.py   # Grafana org/datasource/dashboard/user provisioning
└── provisioning/                   # Grafana file-based provisioning (Dockerfile, base config)
```

## License

See `LICENSE` for details.
