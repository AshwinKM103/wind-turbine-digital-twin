# Troubleshooting

Every entry below is a real issue hit and fixed while building this
stack, not a hypothetical -- current as of the 2026-09-06 fix pass.

## Grafana dashboard shows "Dashboard not found"

**Root causes found (there were four, stacked):**

1. **The dashboard was never imported.** The dashboard JSON existed as a
   standalone file but nothing loaded it into Grafana. Dashboards are no
   longer file-provisioned: run `python scripts/setup_grafana_orgs.py`,
   which creates each customer's org, datasource and fleet dashboard over
   the Grafana HTTP API from
   `provisioning/dashboards/json/<customer_id>/`. If that JSON is
   missing, run `python app/tools/generate_grafana_assets.py` first.

2. **Wrong Grafana plugin ID.** `GF_INSTALL_PLUGINS=iotdb-datasource`
   fails with `404: Plugin not found` -- the actual grafana.com plugin
   slug is **`apache-iotdb-datasource`**. Check with:
   ```bash
   docker logs turbine-grafana | grep -i plugin
   ```

3. **IoTDB's REST service never started**, so even a correctly
   configured datasource got connection-refused on port 18080. The
   `apache/iotdb:1.3.3-standalone` image's `replace-conf-from-env.sh`
   only overwrites a config key if that key **already exists** in
   `/iotdb/conf/iotdb-system.properties` -- and the image's baked-in
   copy of that file has no `enable_rest_service` line at all, so
   setting it as a docker-compose environment variable is silently
   ignored. Fix: bind-mount a properties file that already contains
   `enable_rest_service=true` / `rest_service_port=18080` (see
   `provisioning/iotdb/iotdb-system.properties`). Verify:
   ```bash
   docker exec iotdb curl -sf http://localhost:18080/ping
   ```

4. **Plugin panics on health check / all queries return empty.** The
   `apache-iotdb-datasource` plugin (v1.0.1) reads the IoTDB REST URL
   from `jsonData.url` in the datasource config, **not** Grafana's
   standard top-level `url` field. Leaving `jsonData.url` unset causes
   a Go panic (`slice bounds out of range [-1:]`) inside the plugin's
   URL parser on every query and on `Save & Test`. Fix: set `url` under
   `jsonData:` in `provisioning/datasources/iotdb.yml`, not just at the
   datasource top level.

5. **Panel queries return `frames: []` / no error but no data.** This
   plugin's query editor does not take a plain SQL string in a `query`
   field -- it takes `sqlType: "SQL: Full Customized"` plus separate
   `expression` (array of select-list items, no `select`/`from`
   keywords), `prefixPath` (array of device paths), and `condition`
   (a `where`-clause fragment, no `where` keyword). Reverse-engineered
   from the plugin's own `module.js` bundle
   (`docker exec turbine-grafana grep -o ... module.js`) since this
   isn't documented. See the generated per-customer dashboards in
   `provisioning/dashboards/json/<customer_id>/` for working examples of
   all four panel types (gauge/stat/timeseries/heatmap).

**How to verify the fix from scratch:**
```bash
curl -s -u admin:admin http://localhost:13000/api/datasources/uid/iotdb-rest/health
# expect: {"message":"Data source is working","status":"OK"}
```

## Zookeeper stuck in a restart loop

**Symptom:** `docker logs turbine-zookeeper` repeats `Check if
/var/lib/zookeeper/data is writable ... FAILED`.

**Root cause:** `./data/zookeeper/{data,log}` on the host are
root-owned (left over from an earlier root-owned container run), but
the `cp-zookeeper` image's preflight check requires them writable by
its container user (`appuser`, uid 1000).

**Fix:** either `sudo chown -R 1000:1000 ./data/zookeeper` on the host,
or run the container as root (`user: "0"` in docker-compose.yml, which
is what this project does, matching kafka/grafana which hit the same
issue). If you don't have sudo on the host and can't add `user: "0"`,
delete and let Docker recreate `./data/zookeeper` fresh (loses no
telemetry data -- Zookeeper here only coordinates Kafka, it doesn't
store telemetry).

## Zookeeper healthcheck always fails even though the server is up

**Root cause:** the `ruok` four-letter-word command is disabled by
default in this ZK build; only `srvr` is enabled
(`docker logs turbine-zookeeper | grep "enabled four letter"`
confirms). A healthcheck using `echo ruok | nc ... | grep imok` will
never pass. Fix: use `echo srvr | nc ... | grep 'Zookeeper version'`
instead (already in docker-compose.yml).

## Producer/consumer crash with `PermissionError: [Errno 13] Permission denied: '/app/logs/app.log'`

**Root cause:** `./app/logs` on the host was created with mode 775,
owned by a uid that isn't the container's `appuser` (uid 1000) and
isn't in its group -- so the "other" permission bits (r-x, no write)
apply inside the container.

**Fix:** `chmod 777 ./app/logs` on the host (safe -- it only holds
non-sensitive application logs), or `chown -R 1000:1000 ./app/logs` if
you have the privilege to do so.

## Grafana login fails with "Invalid username or password" even with the right `.env` password

**Root cause:** `./data/grafana` (the Grafana sqlite DB) persisted an
admin password from a previous run/manual change. `GF_SECURITY_ADMIN_*`
env vars only seed the admin account on a *fresh* database -- they
don't reset an existing one.

**Fix:**
```bash
docker exec turbine-grafana grafana-cli admin reset-admin-password <new-password>
```

## `docker compose down` reports "network ... Resource is still in use"

**Root cause:** a container attached to the compose network was started
outside `docker compose` (e.g. a manual `docker run --network ...`) and
isn't tracked by compose, so `down` can stop/remove the compose-managed
containers but can't remove the network while that container still
holds a reference.

**Fix:** find and remove it: `docker network inspect <network> --format
'{{range .Containers}}{{.Name}} {{end}}'`, then `docker rm -f <name>`.

## Benign Grafana log line: "plugin xychart is already registered"

Appears in `docker logs turbine-grafana` on every startup. This is the
`grafana/grafana:11.1.0` base image bundling the `xychart` core panel
plugin twice internally -- unrelated to this project's configuration or
the IoTDB plugin, does not affect the dashboard, and is safe to ignore.

## Health check reference

| Service  | Command                                              | Healthy response                    |
|----------|-------------------------------------------------------|--------------------------------------|
| Zookeeper| `docker exec turbine-zookeeper bash -c "echo srvr \| nc -w2 localhost 2181"` | `Zookeeper version: ...` |
| Kafka    | `docker exec turbine-kafka kafka-broker-api-versions --bootstrap-server localhost:9092` | broker list, no error |
| IoTDB    | `curl -sf http://localhost:18080/ping`               | HTTP 200                            |
| Grafana  | `curl -sf http://localhost:13000/api/health`         | `{"database":"ok",...}`             |
| producer | `curl -s http://localhost:8000/ready`                | `{"status":"healthy",...}`          |
| consumer | `curl -s http://localhost:8001/ready`                | `{"status":"healthy",...}`          |

## Data not appearing in IoTDB at all

1. Check a generator is actually producing:
   `docker logs generator-c1-t01 | grep -i produced`
2. Check the topic has messages:
   `docker exec turbine-kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic turbine.telemetry.raw.v1 --max-messages 1`
3. Check the consumer isn't stuck on the circuit breaker:
   `curl -s http://localhost:8001/ready` -- look for `circuit=OPEN` in
   the `iotdb_connected` check detail. If open, IoTDB is unreachable;
   fix IoTDB first, the breaker auto-recovers after
   `CIRCUIT_BREAKER_RESET_TIMEOUT_S` (default 30s).
4. Check the DLQ isn't silently absorbing everything:
   `docker exec turbine-kafka kafka-topics --bootstrap-server localhost:9092 --describe --topic turbine.telemetry.dlq`
