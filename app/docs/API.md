# API Reference

This project has no application-level REST API of its own for business
logic -- the "API surface" is the health endpoints on the two Python
services, plus IoTDB's and Grafana's own REST APIs, which this pipeline
consumes.

## Producer / Consumer health endpoints

Both `synthetic_producer.py` and `kafka_consumer.py` expose the same two
endpoints (see `app/src/health_server.py`), on `HEALTH_CHECK_PORT`
(default 8000 for the producer, 8001 for the consumer -- see
`docker-compose.yml`).

### `GET /health` -- liveness
Always returns 200 once the process is up; never performs I/O.
```json
{"status": "healthy", "service": "synthetic-producer"}
```

### `GET /ready` -- readiness
Returns 200 only if all dependency checks pass, 503 otherwise.

Producer checks: `simulator_ready`, `kafka_reachable`.
Consumer checks: `kafka_connected`, `iotdb_connected`.

```json
{
  "status": "healthy",
  "checks": {
    "kafka_connected": {"status": "ok", "detail": "consuming"},
    "iotdb_connected": {"status": "ok", "detail": "circuit=CLOSED"}
  }
}
```
`iotdb_connected.detail` surfaces the circuit breaker state
(`CLOSED`/`OPEN`/`HALF_OPEN`) -- see `app/src/resilience.py`.

## Apache IoTDB REST API (consumed by Grafana, useful for debugging)

Base URL: `http://localhost:18080` (basic auth: `IOTDB_USER`/`IOTDB_PASSWORD`, default `root`/`root`).

```bash
curl -s -X POST http://root:root@localhost:18080/rest/v2/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "select last_value(TURBINE_SPEED_RPM) from root.digitaltwin.customer1.site1.turbine01"}'
```
Full reference: https://iotdb.apache.org/UserGuide/latest/API/RestServiceV2.html

## Grafana HTTP API (used for provisioning verification / automation)

Base URL: `http://localhost:13000` (basic auth: Grafana admin credentials).

```bash
# Confirm the IoTDB datasource is healthy
curl -s -u admin:admin http://localhost:13000/api/datasources/uid/iotdb-rest/health

# Run one of the dashboard's panel queries directly (bypasses the UI)
curl -s -u admin:admin -X POST http://localhost:13000/api/ds/query \
  -H "Content-Type: application/json" \
  -d '{
    "from": "now-15m", "to": "now",
    "queries": [{
      "refId": "A",
      "datasource": {"type": "apache-iotdb-datasource", "uid": "iotdb-rest"},
      "sqlType": "SQL: Full Customized",
      "expression": ["last_value(TURBINE_SPEED_RPM)"],
      "prefixPath": ["root.digitaltwin.customer1.site1.turbine01"],
      "condition": ""
    }]
  }'
```
Full reference: https://grafana.com/docs/grafana/latest/developers/http_api/

### apache-iotdb-datasource query target shape

Not documented upstream (reverse-engineered from the plugin's
`module.js` -- see `TROUBLESHOOTING.md` item 5). Each Grafana panel
target for this plugin, in "Full Customized SQL" mode, is:

| Field        | Type            | Meaning                                          |
|--------------|-----------------|---------------------------------------------------|
| `sqlType`    | string          | Always `"SQL: Full Customized"` for this project   |
| `expression` | array of string | Select-list items, no `select`/`from` keywords (e.g. `"last_value(GB_TRQ)"`) |
| `prefixPath` | array of string | Device path(s), e.g. `"root.digitaltwin.customer1.site1.turbine01"` |
| `condition`  | string          | Optional `where`-clause fragment, no `where` keyword |

## Kafka topics

| Topic                        | Purpose                                    | Producer(s)   | Consumer(s) |
|-------------------------------|---------------------------------------------|---------------|-------------|
| `turbine.telemetry.raw.v1`   | Live telemetry, one message per sample tick | synthetic_producer | kafka_consumer |
| `turbine.telemetry.dlq`      | Messages that failed validation or repeatedly failed to write to IoTDB | kafka_consumer | (manual inspection / replay) |

### Message schema (`turbine.telemetry.raw.v1`)
```json
{
  "message_id": "uuid",
  "customer_id": "customer1",
  "turbine_id": "turbine01",
  "seq_no": 12345,
  "event_time_ms": 1725600000000,
  "metrics": { "PT_109A": 32.632, "GB_TRQ": 0.024, "...": "..." }
}
```
