# Provisioning Directory

This directory contains configuration files that are mounted into Docker containers to auto-configure services on startup. Each file serves a specific purpose in the stack initialization.

## Files & Semantic IDs

Use these IDs when referring to files in local discussion:

### iotdb/iotdb-system.properties `[iotdb-conf-rest]`

**What it does:** Override IoTDB's default configuration to enable the REST API service.

**Essential:** YES

**Why it matters:** The apache/iotdb Docker image's built-in config doesn't include the REST service line. Even if you set `ENABLE_REST_SERVICE=true` as an environment variable, the image's config-substitution script silently ignores it (because it only overwrites lines that already exist in the file). This file provides the line so env-var substitution actually works.

**What breaks if removed:** IoTDB starts but port 18080 never opens. Every REST client fails with "connection refused" or "bad gateway".

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
├── postgres/
│   ├── init.sh                   - Postgres init entrypoint
│   └── tenant-views.sql          - Per-tenant roles and views
└── iotdb/
    └── iotdb-system.properties   [iotdb-conf-rest] - IoTDB config override
```

## Usage

All files are mounted as read-only (`ro`) into containers via docker-compose.yml:

- IoTDB: `./provisioning/iotdb/iotdb-system.properties` → `/iotdb/conf/iotdb-system.properties`
- Postgres: `./provisioning/postgres/init.sh` → `/docker-entrypoint-initdb.d/01-init.sh`
- Postgres: `./provisioning/postgres/tenant-views.sql` → `/sql/tenant-views.sql`

Changes to these files require a container restart to take effect (init.sh
and tenant-views.sql only run on first init of a fresh Postgres volume).

## Maintenance

**Modifying IoTDB config:**
1. Edit `provisioning/iotdb/iotdb-system.properties`
2. Restart IoTDB (`docker-compose restart iotdb`)
