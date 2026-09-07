# Provisioning Directory

This directory contains configuration files that are mounted into Docker containers to auto-configure services on startup. Each file serves a specific purpose in the stack initialization.

## Files & Semantic IDs

Use these IDs when referring to files in local discussion:

### datasources/iotdb.yml `[gf-ds-iotdb]`

**What it does:** Auto-configures Grafana with the Apache IoTDB REST datasource on startup.

**Essential:** YES

**Why it matters:** Configures Grafana's connection to IoTDB. Without it, panels cannot query data.

**What breaks if removed:** Panels show "No data" because Grafana has no credentials or endpoint for IoTDB.

**How it works:**
- Tells Grafana: "Connect to http://iotdb:18080 (the IoTDB REST API) using root/root credentials"
- Registers the datasource as UID `iotdb-rest` so panels can reference it
- Sets it as the default datasource for new panels
- Mounted read-only into `/etc/grafana/provisioning/datasources/`

**Alternatives:** You could manually add the datasource in Grafana UI, but provisioning makes it automatic and reproducible.

---

### Dashboard provisioning (no file provider)

There is no `dashboards.yml`. Grafana loads no dashboards from disk.

Every customer org, its IoTDB datasource and its fleet dashboard are created
over the Grafana HTTP API by `scripts/setup_grafana_orgs.py`, which reads the
generated definitions from `dashboards/json/<customer_id>/`. Only
`datasources/iotdb.yml` is file-provisioned.

**What breaks if the JSON goes missing:** `setup_grafana_orgs.py` exits with a
message telling you to run `app/tools/generate_grafana_assets.py` first.

---

### iotdb/iotdb-system.properties `[iotdb-conf-rest]`

**What it does:** Override IoTDB's default configuration to enable the REST API service.

**Essential:** YES (for Grafana to work)

**Why it matters:** The apache/iotdb Docker image's built-in config doesn't include the REST service line. Even if you set `ENABLE_REST_SERVICE=true` as an environment variable, the image's config-substitution script silently ignores it (because it only overwrites lines that already exist in the file). This file provides the line so env-var substitution actually works.

**What breaks if removed:** IoTDB starts but port 18080 never opens. Grafana can't connect. Every panel fails with "connection refused" or "bad gateway".

**Root cause:** The image's `replace-conf-from-env.sh` uses grep to find a key before replacing it. If the key doesn't exist, the replacement is silently skipped. The original image has no `enable_rest_service` line.

**How it works:**
- Mounted at `/iotdb/conf/iotdb-system.properties` (replaces the image's built-in copy)
- Contains `enable_rest_service=true` and `rest_service_port=18080`
- Also includes cluster topology (cn_* and dn_* settings) for single-node standby mode

**Alternatives:** 
- Modify the Docker image to include this line (adds complexity)
- Bake an `enable_rest_service=true` line into the image (not portable)
- Use a different version of the image that has it (may not exist)

---

## Directory Structure

```
provisioning/
├── datasources/
│   └── iotdb.yml                 [gf-ds-iotdb] - Grafana datasource config
├── dashboards/
│   └── json/
│       ├── customer1/            - Generated fleet dashboard, imported via API
│       ├── customer2/
│       └── customer3/
└── iotdb/
    └── iotdb-system.properties   [iotdb-conf-rest] - IoTDB config override
```

## Usage

All files are mounted as read-only (`ro`) into containers via docker-compose.yml:

- Grafana: `./provisioning/datasources` → `/etc/grafana/provisioning/datasources`
- Grafana: `./provisioning/dashboards` → `/etc/grafana/provisioning/dashboards`
- IoTDB: `./provisioning/iotdb/iotdb-system.properties` → `/iotdb/conf/iotdb-system.properties`

Changes to these files require a container restart to take effect.

## Maintenance

**Adding a new dashboard:**
1. Create it in Grafana UI
2. Export as JSON from Grafana
3. Save to `provisioning/dashboards/json/new-dashboard.json`
4. Restart Grafana (`docker-compose restart grafana`)

**Adding a new Grafana datasource:**
1. Create a new file in `provisioning/datasources/` (e.g., `postgres.yml`)
2. Follow Grafana's provisioning format
3. Restart Grafana

**Modifying IoTDB config:**
1. Edit `provisioning/iotdb/iotdb-system.properties`
2. Restart IoTDB (`docker-compose restart iotdb`)
