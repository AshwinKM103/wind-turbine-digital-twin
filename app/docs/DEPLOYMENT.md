# Deployment (Customer On-Prem)

## Pre-deployment checklist

- [ ] `.env.production` filled in with real, unique credentials (never
      reuse the `admin`/`root` defaults from `.env.example`)
- [ ] `.env.production` is **not** committed to version control (verify
      with `git check-ignore .env.production` -- exit 0 means ignored)
- [ ] Host has ports 6667, 8000, 8001, 13000, 18080, 19092 free (or
      remap them in `docker-compose.yml` if they conflict with other
      services on the customer's host)
- [ ] Sufficient disk for `./data/` (Kafka + IoTDB persist here; size to
      the customer's expected retention -- see `KAFKA_LOG_RETENTION_MS`
      in `docker-compose.yml`)
- [ ] Firewall: only 13000 (Grafana) needs to be reachable from outside
      the host; 6667/18080/19092/8000/8001 are for the stack's own
      inter-container and operator use

## Deploy

```bash
cp .env.production .env
docker compose up -d --build
docker compose ps   # confirm all 6 services report (healthy)
```

## Post-deploy verification

Run through `TROUBLESHOOTING.md`'s "Health check reference" section --
every `/health` and `/ready` endpoint should return 200, and the Grafana
dashboard should show data within 15 seconds (its `refresh: "5s"`
setting).

## Updating

```bash
git pull                              # or copy the new release
docker compose build producer consumer
docker compose up -d                  # recreates only changed services
```
IoTDB and Kafka data in `./data/` survives (bind-mounted, not
container-local).

## Backup

- **IoTDB**: stop the stack (`docker compose stop iotdb`) and copy
  `./data/iotdb/data`, or use IoTDB's own export tools
  (`export-data.sh`) for a live backup without downtime.
- **Kafka**: generally not backed up -- it's a transient buffer, not a
  system of record. If DLQ replay history matters, back up
  `./data/kafka`.
- **Grafana**: `./data/grafana` (dashboards/users/alerts not covered by
  the file-based provisioning in `./provisioning/`).

## Rollback

```bash
docker compose down
git checkout <previous-tag>
docker compose up -d --build
```
Data in `./data/` is untouched by `docker compose down` (only removed by
`down -v`), so a rollback does not lose telemetry history.

## Resource sizing (starting point, single turbine)

| Service   | CPU   | Memory |
|-----------|-------|--------|
| Zookeeper | 0.25  | 256MB  |
| Kafka     | 0.5   | 512MB  |
| IoTDB     | 1.0   | 1GB    |
| Grafana   | 0.25  | 256MB  |
| producer  | 0.1   | 128MB  |
| consumer  | 0.25  | 256MB  |

Scale IoTDB CPU/memory first if adding more turbines to the same stack
(each turbine is one device path, sharing the same JVM).
