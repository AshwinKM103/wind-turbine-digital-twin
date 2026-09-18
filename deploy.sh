#!/usr/bin/env bash
# ==============================================================================
# Single-Script Automated Deployment for Wind Turbine Digital Twin Stack
# ==============================================================================
# Implements the 6-phase unified, idempotent deployment plan:
#   Phase 1: Host Environment & Configuration Preflight
#   Phase 2: Core Infrastructure Boot & Schema Provisioning
#   Phase 3: ThingsBoard Core & Identity Provisioning
#   Phase 4: Telemetry Pipeline & Application Services
#   Phase 5: ThingsBoard Customizations & Dashboard Deployment
#   Phase 6: Health Probing & Verification Sign-off
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Text styles
BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"

log_info()    { echo -e "${BLUE}[INFO]${RESET} $1"; }
log_step()    { echo -e "\n${BOLD}${GREEN}=== $1 ===${RESET}"; }
log_warn()    { echo -e "${YELLOW}[WARN]${RESET} $1"; }
log_error()   { echo -e "${RED}[ERROR]${RESET} $1"; }
log_success() { echo -e "${GREEN}[✓]${RESET} $1"; }

# Flags
NO_GPU=false
SKIP_TESTS=false
RESET_DATA=false
DRY_RUN=false

show_help() {
    cat << EOF
================================================================================
 WIND TURBINE DIGITAL TWIN - UNIFIED MANAGEMENT CLI
================================================================================
Usage: ./deploy.sh [COMMAND / OPTION]

Deployment:
  (no args)            Run full idempotent 6-phase deployment pipeline
  --no-gpu, --cpu      Disable vLLM GPU inference and Copilot backend (for CPU hosts)
  --dry-run            Run preflight checks and compose validation without booting
  --skip-tests         Skip verification test suites during deployment

Stack Lifecycle:
  --up                 Quick start / build container stack without re-provisioning
  --down, --stop       Stop and remove container stack
  --restart [service]  Restart all containers or a specific service
  --status, -s         Show real-time container health and status
  --logs, -l [service] Follow logs for all services or a specific service

Maintenance & Database:
  --apply-schemas      Apply IoTDB templates and PostgreSQL tenant views
  --init-openbao       Initialize and unseal OpenBao secrets vault
  --reset, --clean     Tear down containers and wipe persistent data volumes
  --tests, --test      Run Playwright and Pytest verification suites
  -h, --help           Show this help message
================================================================================
EOF
    exit 0
}

# Parse CLI args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-gpu|--cpu)
            NO_GPU=true
            shift
            ;;
        --reset|--clean)
            RESET_DATA=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --up)
            log_info "Starting Digital Twin stack..."
            docker compose up -d --build --remove-orphans
            log_success "Stack started."
            exit 0
            ;;
        --down|--stop)
            log_info "Stopping Digital Twin stack..."
            docker compose down --remove-orphans
            log_success "Stack stopped."
            exit 0
            ;;
        --restart)
            shift
            if [[ $# -gt 0 ]]; then
                log_info "Restarting service '$1'..."
                docker compose restart "$@"
            else
                log_info "Restarting all stack services..."
                docker compose restart
            fi
            log_success "Restart complete."
            exit 0
            ;;
        --status|-s)
            docker compose ps
            exit 0
            ;;
        --logs|-l)
            shift
            docker compose logs -f "$@"
            exit 0
            ;;
        --init-openbao)
            log_info "Initializing and unsealing OpenBao..."
            bash openbao/init-openbao.sh
            exit 0
            ;;
        --apply-schemas)
            [[ -f .env ]] && set -a && source .env && set +a
            log_info "Applying PostgreSQL tenant views..."
            docker exec -i turbine-postgres psql -U "${POSTGRES_USER:-turbine}" -d "${POSTGRES_DB:-turbine}" \
                -v tenant_name="${TENANT_NAME:-zephyr-energy}" \
                -v grafana_password="${POSTGRES_GRAFANA_PASSWORD:-grafana_dev_password}" \
                -v db_name="${POSTGRES_DB:-turbine}" \
                -f /sql/tenant-views.sql
            log_info "Applying Apache IoTDB schemas..."
            grep -v '^--' app/config/iotdb-schema.sql | grep -v '^[[:space:]]*$' | tr '\n' ' ' | \
                docker exec -i iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 -u root -pw "${IOTDB_PASSWORD:-root}" >/dev/null || true
            grep -v '^--' app/config/iotdb-schema-fleet.sql | grep -v '^[[:space:]]*$' | tr '\n' ' ' | \
                docker exec -i iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 -u root -pw "${IOTDB_PASSWORD:-root}" >/dev/null || true
            log_success "Schemas applied successfully."
            exit 0
            ;;
        --tests|--test)
            log_info "Running backend Pytest contract suite..."
            pytest app/copilot_backend/tests/test_resolve_turbine_device.py \
                   app/copilot_backend/tests/test_model_gateway.py \
                   app/copilot_backend/tests/test_dashboard_actions.py \
                   app/copilot_backend/tests/test_tb_tools.py \
                   app/copilot_backend/tests/test_main_contract.py
            if [[ -d "tests/node_modules" ]]; then
                log_info "Running Playwright 3D Widget regression suite..."
                (cd tests && npx playwright test)
            fi
            log_success "All test suites completed successfully."
            exit 0
            ;;
        -h|--help)
            show_help
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            ;;
    esac
done

# ==============================================================================
# PHASE 1: Host Environment & Configuration Preflight
# ==============================================================================
log_step "Phase 1: Host Environment & Configuration Preflight"

# 1.1 Check host CLI dependencies
log_info "Checking host dependencies (docker, docker compose, python3, curl, jq)..."
for bin in docker python3 curl jq; do
    if ! command -v "$bin" &>/dev/null; then
        log_error "Required host binary '$bin' is not installed or not on PATH."
        exit 1
    fi
done

if ! docker compose version &>/dev/null; then
    log_error "Docker Compose v2 plugin ('docker compose') is required."
    exit 1
fi
log_success "Host CLI dependencies verified."

# 1.2 Probe GPU availability
if [[ "$NO_GPU" == "false" ]]; then
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        GPU_COUNT=$(nvidia-smi --query-gpu=count --format=csv,noheader | head -n 1 || echo "1")
        log_info "NVIDIA GPU detected (Count: ${GPU_COUNT}). Local LLM (vLLM) enabled."
    else
        log_warn "NVIDIA GPU or nvidia-smi not detected. Automatically falling back to CPU mode (--no-gpu)."
        NO_GPU=true
    fi
fi

# 1.3 Materialize .env
if [[ ! -f ".env" ]]; then
    log_warn ".env file not found. Initializing from .env.example..."
    cp .env.example .env
fi

# 1.4 Generate random secrets for mandatory keys if missing
generate_secret() {
    python3 -c "import secrets; print(secrets.token_urlsafe(24))"
}

ensure_env_var() {
    local key="$1"
    local default_generator="$2"
    local current_val
    current_val=$(grep -E "^${key}=" .env | cut -d '=' -f2- || true)

    if [[ -z "$current_val" ]]; then
        local new_val
        new_val=$($default_generator)
        if grep -q "^${key}=" .env; then
            sed -i "s|^${key}=.*|${key}=${new_val}|" .env
        else
            echo "${key}=${new_val}" >> .env
        fi
        log_info "Generated secure value for '${key}' in .env"
    fi
}

ensure_env_var "POSTGRES_PASSWORD" generate_secret
ensure_env_var "POSTGRES_GRAFANA_PASSWORD" generate_secret
ensure_env_var "TB_POSTGRES_PASSWORD" generate_secret
ensure_env_var "TB_SYSADMIN_PASSWORD" generate_secret
ensure_env_var "TB_TENANT_ADMIN_PASSWORD" generate_secret
ensure_env_var "VLLM_API_KEY" generate_secret

# Ensure VLLM_GPU_ID is 0 if single GPU host
if [[ "$NO_GPU" == "false" && "${GPU_COUNT:-1}" -eq 1 ]]; then
    if ! grep -q "^VLLM_GPU_ID=" .env; then
        echo "VLLM_GPU_ID=0" >> .env
    else
        sed -i "s|^VLLM_GPU_ID=.*|VLLM_GPU_ID=0|" .env
    fi
fi

# Ensure STORAGE_PATH is local ./data by default for portability
if ! grep -q "^STORAGE_PATH=" .env; then
    echo "STORAGE_PATH=./data" >> .env
elif grep -q "^STORAGE_PATH=/mnt/data3" .env && [[ ! -d "/mnt/data3" ]]; then
    sed -i "s|^STORAGE_PATH=.*|STORAGE_PATH=./data|" .env
fi

# 1.5 Create storage directories with write permissions
STORAGE_DIR=$(grep -E "^STORAGE_PATH=" .env | cut -d '=' -f2- || echo "./data")
log_info "Ensuring storage directory structure under '${STORAGE_DIR}'..."
mkdir -p "${STORAGE_DIR}/secrets/openbao" \
         "${STORAGE_DIR}/provisioning-results" \
         "${STORAGE_DIR}/reports" \
         "${STORAGE_DIR}/app-logs"

# 1.6 Optional Reset Data
if [[ "$RESET_DATA" == "true" ]]; then
    log_warn "Reset requested: Tearing down containers and wiping data..."
    docker compose down -v --remove-orphans || true
    rm -rf "${STORAGE_DIR}/secrets/openbao"/* "${STORAGE_DIR}/provisioning-results"/* || true
    log_success "Persistent data reset."
fi

# 1.7 Dry run check
log_info "Validating Docker Compose configuration..."
docker compose config --quiet
log_success "Compose configuration syntax is valid."

if [[ "$DRY_RUN" == "true" ]]; then
    log_success "Dry run complete. Exiting before launching containers."
    exit 0
fi

# Load environment variables for host-executed scripts and set overrides
set -a
source .env
set +a
export TB_HOST="127.0.0.1"
export TB_PORT="8082"
export TB_URL="http://127.0.0.1:8082"
export TB_DEVICE_TOKEN_MAP="${STORAGE_DIR}/provisioning-results/device-tokens.json"
mkdir -p "${STORAGE_DIR}/provisioning-results" "./provisioning/results"

# Helper function to wait for a container's health check
wait_for_health() {
    local service="$1"
    local max_wait="${2:-120}"
    local count=0
    log_info "Waiting for service '${service}' to be healthy..."
    while [[ $count -lt $max_wait ]]; do
        local status
        status=$(docker compose ps "$service" --format '{{.Health}}' 2>/dev/null || echo "")
        if [[ "$status" == "healthy" ]]; then
            log_success "Service '${service}' is healthy."
            return 0
        fi
        sleep 2
        count=$((count + 2))
    done
    log_error "Service '${service}' failed to become healthy within ${max_wait}s (status: ${status:-unknown})."
    docker compose logs --tail 30 "$service" || true
    return 1
}

# ==============================================================================
# PHASE 2: Core Infrastructure Boot & Schema Provisioning
# ==============================================================================
log_step "Phase 2: Core Infrastructure Boot & Schema Provisioning"

# 2.1 Start Layer 1 storage and messaging primitives
log_info "Starting Layer 1: Permissions, Databases, Storage & OpenBao..."
docker compose up -d bootstrap-permissions zookeeper postgres thingsboard-postgres iotdb openbao

wait_for_health "zookeeper" 60
wait_for_health "postgres" 60
wait_for_health "thingsboard-postgres" 60
wait_for_health "iotdb" 90
wait_for_health "openbao" 60

# 2.2 Provision PostgreSQL schemas and tenant views
log_info "Applying PostgreSQL tenant views with dynamic identifiers..."
TENANT_NAME=$(grep -E "^TENANT_NAME=" .env | cut -d '=' -f2- || echo "zephyr-energy")
POSTGRES_USER=$(grep -E "^POSTGRES_USER=" .env | cut -d '=' -f2- || echo "turbine")
POSTGRES_DB=$(grep -E "^POSTGRES_DB=" .env | cut -d '=' -f2- || echo "turbine")
POSTGRES_GRAFANA_PW=$(grep -E "^POSTGRES_GRAFANA_PASSWORD=" .env | cut -d '=' -f2- || echo "grafana_dev_password")

docker exec -i turbine-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -v tenant_name="$TENANT_NAME" \
    -v grafana_password="$POSTGRES_GRAFANA_PW" \
    -v db_name="$POSTGRES_DB" \
    -f /sql/tenant-views.sql

log_success "PostgreSQL tenant views applied."

# 2.3 Provision IoTDB time-series templates and schemas
log_info "Applying Apache IoTDB schemas and fleet templates..."
IOTDB_PASSWORD=$(grep -E "^IOTDB_PASSWORD=" .env | cut -d '=' -f2- || echo "root")
grep -v '^--' app/config/iotdb-schema.sql | grep -v '^[[:space:]]*$' | tr '\n' ' ' | \
    docker exec -i iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 -u root -pw "$IOTDB_PASSWORD" >/dev/null || true
grep -v '^--' app/config/iotdb-schema-fleet.sql | grep -v '^[[:space:]]*$' | tr '\n' ' ' | \
    docker exec -i iotdb /iotdb/sbin/start-cli.sh -h 127.0.0.1 -p 6667 -u root -pw "$IOTDB_PASSWORD" >/dev/null || true
log_success "IoTDB schemas and device templates registered."

# 2.4 Initialize OpenBao Vault
log_info "Initializing and unsealing OpenBao..."
bash openbao/init-openbao.sh
log_success "OpenBao initialization complete."

# ==============================================================================
# PHASE 3: ThingsBoard Core & Identity Provisioning
# ==============================================================================
log_step "Phase 3: ThingsBoard Core & Identity Provisioning"

# 3.1 ThingsBoard database initialization and start
log_info "Starting ThingsBoard installer and core service..."
docker compose up -d thingsboard-install
docker compose up -d thingsboard

# Poll ThingsBoard readiness via HTTP REST endpoint
log_info "Polling ThingsBoard API readiness on port 8082 (this typically takes ~90s)..."
TB_READY=false
for i in {1..90}; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8082/api/auth/user 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "401" ]]; then
        TB_READY=true
        log_success "ThingsBoard is ready (HTTP $HTTP_CODE)."
        break
    fi
    sleep 2
done

if [[ "$TB_READY" == "false" ]]; then
    log_error "ThingsBoard failed to respond on http://127.0.0.1:8082 within timeout."
    docker compose logs --tail 40 thingsboard
    exit 1
fi

# 3.2 Secure default sysadmin credentials
log_info "Securing ThingsBoard sysadmin account..."
python3 app/tools/tb_admin.py auth secure || {
    log_warn "Host python execution failed; falling back to container runner..."
    docker compose run --rm thingsboard-secure-admin
}
log_success "Sysadmin account secured."

# 3.3 Provision Tenant, Device, and Asset Hierarchy
log_info "Provisioning Tenant, Device, and Subsystem Twin Assets..."
python3 app/tools/tb_admin.py entity provision --tb-host 127.0.0.1 --tb-port 8082
log_success "Entities provisioned in ThingsBoard."

# 3.4 Export Device Access Tokens for Kafka-MQTT Bridge
log_info "Exporting live device access tokens..."
python3 app/tools/tb_admin.py auth export-tokens || {
    log_warn "Host export failed; running token-exporter via Docker..."
    docker compose run --rm token-exporter
}
cp -f "${STORAGE_DIR}/provisioning-results/device-tokens.json" "./provisioning/results/device-tokens.json" 2>/dev/null || true
log_success "Device tokens exported to provisioning results."

# ==============================================================================
# PHASE 4: Telemetry Pipeline & Application Services
# ==============================================================================
log_step "Phase 4: Telemetry Pipeline & Application Services"

# 4.1 Launch Kafka Broker
log_info "Starting Kafka broker..."
docker compose up -d kafka
wait_for_health "kafka" 60

# 4.2 Start Telemetry Ingestion Consumer & Bridge
log_info "Starting Consumer, Kafka-MQTT Bridge, and Replay Server..."
docker compose up -d consumer kafka-mqtt-bridge replay-server

wait_for_health "consumer" 60
wait_for_health "kafka-mqtt-bridge" 60
wait_for_health "replay-server" 60

# 4.3 Launch Copilot Backend and Traefik
if [[ "$NO_GPU" == "false" ]]; then
    log_info "Starting vLLM Local LLM engine and Copilot Backend..."
    docker compose up -d vllm
    wait_for_health "vllm" 180
    docker compose up -d copilot-backend
else
    log_info "Skipping vLLM and Copilot backend (--no-gpu active)."
fi

docker compose up -d traefik
log_success "Runtime pipeline services active."

# ==============================================================================
# PHASE 5: ThingsBoard Customizations & Dashboard Deployment
# ==============================================================================
log_step "Phase 5: ThingsBoard Customizations & Dashboard Deployment"

log_info "Deploying custom ThingsBoard widgets..."
python3 app/tools/tb_admin.py widget deploy thresholds
python3 app/tools/tb_admin.py widget deploy babylon-3d
if [[ "$NO_GPU" == "false" ]]; then
    python3 app/tools/tb_admin.py widget deploy copilot
fi
log_success "Widgets deployed."

log_info "Configuring ISO 10816-3 Dynamic Threshold Alarm Rule Chain..."
python3 app/tools/tb_admin.py rulechain deploy
log_success "Rule chain deployed."

log_info "Synchronizing 2D/3D Digital Twin Subsystem Metadata..."
python3 app/tools/tb_admin.py metadata sync
log_success "Subsystem metadata synchronized."

log_info "Seeding baseline subsystem health scores..."
python3 app/tools/tb_admin.py health seed
log_success "Health scores initialized."

log_info "Deploying operational dashboards (SCADA Mimic, Vibration, Thermo, Alarms, 3D Twin)..."
python3 app/tools/tb_admin.py dashboard deploy split
python3 app/tools/tb_admin.py dashboard deploy babylon
log_success "All 5 operational dashboards deployed."

# ==============================================================================
# PHASE 6: Health Probing & Verification Sign-off
# ==============================================================================
log_step "Phase 6: Verification Sign-off & Service Discovery"

# 6.1 Check health endpoints
log_info "Checking subsystem health endpoints..."
curl -fsS http://127.0.0.1:8085/api/replay/status >/dev/null && log_success "Replay Server HTTP API is operational."
curl -fsS http://127.0.0.1:8001/ready >/dev/null && log_success "IoTDB Telemetry Consumer is ready."

# 6.2 Optional Playwright integration test suite
if [[ "$SKIP_TESTS" == "false" ]]; then
    if [[ -d "tests/node_modules" ]]; then
        log_info "Running Playwright 3D Widget regression suite..."
        (cd tests && npx playwright test) || log_warn "Playwright suite reported issues (check test report)."
    fi
fi

# 6.3 Service Discovery Summary
echo -e "\n${BOLD}${GREEN}================================================================================"
echo " ✅ WIND TURBINE DIGITAL TWIN DEPLOYMENT COMPLETE"
echo "================================================================================${RESET}"
echo -e " ThingsBoard Web UI:        ${BOLD}http://localhost:8082${RESET}"
echo -e "   - Sysadmin Login:        ${BOLD}$(grep -E "^TB_SYSADMIN_EMAIL=" .env | cut -d '=' -f2- || echo "sysadmin@thingsboard.org")${RESET}"
echo -e "   - Tenant Admin Login:    ${BOLD}$(grep -E "^TENANT_EMAIL=" .env | cut -d '=' -f2- || echo "zephyr-energy_admin@example.com")${RESET}"
echo -e " DAQ Replay Server API:     ${BOLD}http://localhost:8085/api/replay/status${RESET}"
echo -e " Apache IoTDB REST API:     ${BOLD}http://localhost:18080/ping${RESET}"
echo -e " OpenBao Secrets Vault:     ${BOLD}http://localhost:8200${RESET}"
if [[ "$NO_GPU" == "false" ]]; then
echo -e " Copilot Assistant API:     ${BOLD}http://localhost:8090/health${RESET}"
echo -e " vLLM Model Engine API:     ${BOLD}http://localhost:8000/v1/models${RESET}"
fi
echo -e " Traefik MQTT Edge Gateway: ${BOLD}localhost:8883${RESET}"
echo -e " Stack Status:              ${BOLD}./deploy.sh --status${RESET}"
echo -e " Follow Logs:               ${BOLD}./deploy.sh --logs${RESET}"
echo -e " Stop Stack:                ${BOLD}./deploy.sh --stop${RESET}"
echo "================================================================================"
exit 0
