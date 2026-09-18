#!/bin/bash
# First-boot provisioning for the alerts / KPI Postgres database.
# Applies schema and per-tenant views using psql variable interpolation.

set -euo pipefail

if [ -z "${POSTGRES_GRAFANA_PASSWORD:-}" ]; then
    echo "init.sh: POSTGRES_GRAFANA_PASSWORD is unset; the Grafana datasources" >&2
    echo "         would be provisioned with no way to authenticate." >&2
    exit 1
fi

psql_run() {
    psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
         --set ON_ERROR_STOP=1 --no-psqlrc "$@"
}

echo "init.sh: applying schema"
psql_run --file /sql/postgres-schema.sql

echo "init.sh: applying tenant views and read-only roles"
psql_run --set "grafana_password=$POSTGRES_GRAFANA_PASSWORD" \
         --set "db_name=$POSTGRES_DB" \
         --set "tenant_name=${TENANT_NAME:-zephyr-energy}" \
         --file /sql/tenant-views.sql

echo "init.sh: provisioning complete"
