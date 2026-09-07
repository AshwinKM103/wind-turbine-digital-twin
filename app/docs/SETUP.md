# Setup

## Prerequisites
- Docker Engine 24+ and Docker Compose v2 (`docker compose version`)
- Ports free on the host: 6667, 8000, 8001, 13000, 18080, 19092
- ~2GB free RAM for the stack (IoTDB + Kafka + Zookeeper + Grafana + 2 Python services)

## 1. Clone / copy the project
```bash
cd "Apache_IOTDB"
```

## 2. Configure environment
```bash
cp .env.example .env          # or .env.development for local dev
# edit .env: at minimum change GRAFANA_ADMIN_PASSWORD and IOTDB_PASSWORD
# before any non-local deployment -- see SECURITY note in DEPLOYMENT.md
```

## 3. Review the fleet topology
```bash
cat app/config/fleet.json
```
This declares which turbines belong to which customer and is the single
source of truth for the IoTDB schema, the docker-compose generator
services, the Grafana tenants and the tests. After editing it, regenerate
the artifacts derived from it:
```bash
python app/tools/generate_fleet_schema.py
python app/tools/generate_compose_generators.py
python app/tools/generate_grafana_assets.py
```

Telemetry is synthesised per turbine by `synthetic_producer.py`; no CSV
file or recorded log is needed.

## 4. Bring the stack up
```bash
docker compose up -d --build
```
First run builds the producer/consumer image (installs Python deps) and
pulls Kafka/Zookeeper/IoTDB/Grafana images -- a few minutes on a cold
Docker cache.

## 5. Wait for all services to become healthy
```bash
docker compose ps
```
All services (zookeeper, kafka, iotdb, grafana, consumer,
anomaly-detector and one `generator-cN-tNN` per turbine) should show
`(healthy)`. This can take up to ~60s on first boot
(zookeeper -> kafka -> iotdb -> grafana/producer/consumer, in that
dependency order).

## 6. Load the IoTDB schema (first boot only)
IoTDB auto-creates timeseries on first write, but the device template
gives every channel the intended GORILLA/SNAPPY encoding and lets a new
turbine inherit the schema without a migration. Apply it once:

```bash
# The CLI's -e flag takes one statement and does not accept SQL comments,
# so strip comments and feed statements one at a time.
for f in app/config/iotdb-schema.sql app/config/iotdb-schema-fleet.sql; do
  python3 - "$f" <<'EOF' | while IFS= read -r stmt; do
import pathlib, re, sys
text = re.sub(r"--[^\n]*", "", pathlib.Path(sys.argv[1]).read_text())
for s in text.split(";"):
    s = " ".join(s.split())
    if s:
        print(s)
EOF
    docker exec iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 \
      -u root -pw root -e "$stmt" </dev/null | grep -i "^Msg"
  done
done
```

`CREATE DATABASE` reports "already been created" on re-runs; that is
expected and harmless. If `SET DEVICE TEMPLATE` hangs, restart IoTDB
(`docker compose restart iotdb`) and retry -- an interrupted CLI session
can leave a schema lock held.

## 7. Create the per-customer Grafana tenants (first boot only)
Grafana cannot create organisations from provisioning files, and refuses
to *start* if a provisioning file names an org that does not exist. So
orgs, customer logins, per-org datasources and per-customer dashboards
are created through the API instead, by one idempotent script:

```bash
GRAFANA_ADMIN_PASSWORD=admin CUSTOMER_USER_PASSWORD=customer123 \
  python3 scripts/setup_grafana_orgs.py
```

Re-running it reconciles rather than duplicating, so it is safe in a
deploy step.

## 8. Open Grafana
http://localhost:13000.

* As admin (`GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` from `.env`):
  the "Wind Turbine Digital Twin - turbine01" dashboard under the "Wind
  Turbine Digital Twin" folder, in the default org.
* As a customer (`customer1@company.com` / `CUSTOMER_USER_PASSWORD`):
  the "Customer1 Fleet" dashboard, showing only that customer's turbines.
  Each customer login is a Viewer in exactly one org and cannot see any
  other tenant's org, datasource or dashboard.

## 9. Verify data is flowing
```bash
curl -s http://localhost:8101/ready    # generator customer1/turbine01
curl -s http://localhost:8001/ready    # consumer readiness
docker logs turbine-generator-c1-t01 --tail 5 | grep "Produced telemetry"
docker logs turbine-consumer --tail 5  | grep "Processed batch"
```

`Processed batch` reports `records` (consumed), `written` (rows written to
IoTDB) and `devices` (distinct turbines in that batch). A persistent
`written: 0` means writes are failing -- check for a type mismatch between
`kafka_consumer.DATA_TYPES` and the device template.

## Running the Python scripts outside Docker (optional, for development)
```bash
cd app/src
pip install -r requirements.txt
cp ../../.env.development ../../.env   # config.py auto-loads .env via python-dotenv
KAFKA_BOOTSTRAP_SERVERS=localhost:19092 CUSTOMER_ID=customer1 TURBINE_ID=turbine01 python synthetic_producer.py
KAFKA_BOOTSTRAP_SERVERS=localhost:19092 IOTDB_HOST=localhost python kafka_consumer.py
```

## Stopping / resetting
```bash
docker compose down          # stop, keep all data (./data/ volumes)
docker compose down -v       # stop and DELETE all data -- fresh start
```
