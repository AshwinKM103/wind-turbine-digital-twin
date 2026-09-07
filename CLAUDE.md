# Wind Turbine Digital Twin - Project Context

## Overview
This project simulates a fleet of wind turbines, streams synthetic telemetry data via Kafka, persists it in Apache IoTDB, and visualizes per-customer metrics in Grafana. Multi-tenant by design: each customer has isolated data and a separate Grafana organization.

## Architecture

```
Turbine Generators (Kafka Producers)
    ↓ (synthetic telemetry data)
Kafka (message broker)
    ↓ (consume & batch)
Consumer (Kafka Consumer)
    ↓ (write time-series)
IoTDB (time-series database)
    ↓ (query)
Grafana (dashboards per customer)

Anomaly Detector (parallel consumer for alerts)
```

## Configuration

### Environment Variables: Usage & Scoping

**Parameterized in docker-compose.yml** (can override per deployment):
- `IOTDB_VERSION`: Docker image tag for IoTDB (e.g., `1.3.3-standalone`)
- `IOTDB_DATA_PATH`: Host path where time-series data persists (default: `./data/iotdb/data`)
- `IOTDB_LOGS_PATH`: Host path for IoTDB logs (default: `./data/iotdb/logs`)
- `IOTDB_SUBNET`: Docker bridge subnet for container networking (default: `172.20.0.0/16`)
- `IOTDB_GATEWAY`: Docker gateway IP (default: `172.20.0.1`)

**Used by application code** (app/src/config.py):
- Connection: `IOTDB_HOST`, `IOTDB_PORT`, `IOTDB_USER`, `IOTDB_PASSWORD`
- Kafka: `KAFKA_BOOTSTRAP_SERVERS_INTERNAL`, `KAFKA_TOPIC`, `KAFKA_GROUP_ID`, `DLQ_TOPIC`
- Device identity: `CUSTOMER_ID`, `SITE_ID`, `TURBINE_ID` (set per generator in docker-compose.yml via fleet.json)
- Producer tuning: `SAMPLE_INTERVAL_S`, `PRODUCE_LOG_EVERY_N`, `STATE_*_DURATION_S`
- Consumer tuning: `BATCH_SIZE`, `BATCH_MAX_WAIT_S`, `IOTDB_WRITE_MAX_RETRIES`, `IOTDB_WRITE_BACKOFF_BASE_S`
- Resilience: `CIRCUIT_BREAKER_FAILURE_THRESHOLD`, `CIRCUIT_BREAKER_RESET_TIMEOUT_S`

**Grafana provisioning** (scripts/setup_grafana_orgs.py):
- `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`: Dashboard admin credentials
- `CUSTOMER_USER_PASSWORD`: Shared password for all customer logins (demo only; change before production)

**Not used** (deleted from .env.example):
- `IOTDB_CONTAINER_NAME`, `IOTDB_RESTART_POLICY`: Already hardcoded in docker-compose.yml
- `CN_*`, `DN_*` (clustering config): Only for multi-node IoTDB; this is a single-node standalone deployment
- `IOTDB_IP_ADDRESS`: Not used; networking is automatic via Docker bridge

### Device Paths & Multi-Tenancy

Each turbine writes time-series data under a unique IoTDB device path, computed from fleet topology:

```
root.digitaltwin.<CUSTOMER_ID>.<SITE_ID>.<TURBINE_ID>
```

Example:
```
root.digitaltwin.customer1.site1.turbine01
root.digitaltwin.customer2.site1.turbine03
```

This enforces data isolation at the storage level—each customer's Grafana datasource queries only its subtree (`root.digitaltwin.customer2.*`).

**Critical:** Device identity (`CUSTOMER_ID`, `SITE_ID`, `TURBINE_ID`) is set **per generator container** in docker-compose.yml, not globally in .env. If set globally, all generators write to the same device path, causing data collisions.

### Fleet Topology

Fleet configuration is the single source of truth: `app/config/fleet.json`

Defines:
- Customers (ID, display name, Grafana org id, login email)
- Per-customer sites (site IDs)
- Per-site turbines (turbine IDs, health check ports)

When you add a turbine or customer:

```bash
# 1. Edit fleet.json
# 2. Regenerate docker-compose.yml generator services
python app/tools/generate_compose_generators.py

# 3. Regenerate IoTDB schema
python app/tools/generate_fleet_schema.py

# 4. Regenerate Grafana assets
python app/tools/generate_grafana_assets.py

# 5. Bring up new containers and sync Grafana
docker compose up -d --build
python scripts/setup_grafana_orgs.py
```

See `app/docs/SETUP.md` for full onboarding.

## Key Files & Responsibilities

| File | Responsibility |
|------|-----------------|
| `docker-compose.yml` | Service definitions (Zookeeper, Kafka, IoTDB, Grafana, Generators, Consumer, Anomaly Detector) |
| `.env.example` | All runtime configuration; copy to `.env` for local deployment |
| `app/config/fleet.json` | Single source of truth for customer/site/turbine topology |
| `app/src/config.py` | Centralized env var loading and type conversion |
| `app/src/fleet.py` | Typed dataclass loader for fleet.json |
| `app/tools/generate_*.py` | Auto-generation scripts (compose, schema, Grafana assets) |
| `scripts/setup_grafana_orgs.py` | Idempotent Grafana org/datasource/user provisioning |

## Deployment Modes

### Development (local)
```bash
# .env: ENVIRONMENT=development, IOTDB_HOST=localhost
docker compose up -d
```
Runs all services locally in containers; external access via localhost ports.

### Production (cloud/on-premise)
```bash
# .env: ENVIRONMENT=production, IOTDB_HOST=<cloud-iotdb-host>, strong credentials
docker compose up -d
```
Override IOTDB_HOST to point to a managed/remote IoTDB instance. Credentials must be secure (use `openssl rand -base64 16`).

## Testing

Run the end-to-end test suite to verify multi-customer/multi-turbine setup:
```bash
pytest app/tests/ -v
```

Key test files:
- `test_fleet.py`: Fleet topology loading and validation
- `test_multi_customer_e2e.py`: Data isolation across customers
- `test_multi_turbine_routing.py`: Turbine-to-device-path mapping

## Known Limitations & Future Work

1. **Anomaly detection**: Logs alerts as JSON only; emitting to alert topics is not yet implemented
2. **UI for fleet management**: Turbine/customer provisioning is CLI-only (fleet.json + scripts). A REST API + web form is planned but not implemented (see Agent findings in git history)
3. **Thingsboard migration**: Eventual goal is to migrate to Thingsboard for unified device management + visualization. This codebase serves as a learning/demo platform for IoTDB/Kafka architecture

## Troubleshooting

### Kafka offset lag
If the consumer falls behind (IoTDB slow or down):
- Check `BATCH_MAX_WAIT_S` and `BATCH_SIZE` tuning
- Verify IoTDB health: `curl http://localhost:18080/ping`
- Circuit breaker may be open; check logs

### Device path collisions
If multiple turbines report the same metrics:
- Verify docker-compose.yml: each generator has unique `CUSTOMER_ID`, `SITE_ID`, `TURBINE_ID`, `HEALTH_CHECK_PORT`
- Check `app/config/fleet.json` for duplicate turbine IDs
- Rerun: `python app/tools/generate_compose_generators.py`

### Grafana data not appearing
- Verify IoTDB datasource is reachable: check Grafana data source health
- Confirm `IOTDB_USER` and `IOTDB_PASSWORD` match container env vars
- Check consumer logs: `docker logs turbine-consumer`
