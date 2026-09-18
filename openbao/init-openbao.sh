#!/bin/bash
# init-openbao.sh - Initialize OpenBao with policies, AppRoles, and secrets engines.
# Idempotent: detects existing initialization and unseals, skips re-creating AppRoles.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

OPENBAO_ADDR="${OPENBAO_ADDR:-http://localhost:8200}"
OPENBAO_POLICY_DIR="$SCRIPT_DIR/policies"
# Repo-relative by default so a fresh clone works on any machine; override
# for a real deployment where secrets should live outside the repo.
OPENBAO_SECRETS_DIR="${OPENBAO_SECRETS_DIR:-$REPO_ROOT/secrets/openbao}"
mkdir -p "$OPENBAO_SECRETS_DIR"
UNSEAL_KEY_FILE="$OPENBAO_SECRETS_DIR/unseal-key"
ROOT_TOKEN_FILE="$OPENBAO_SECRETS_DIR/root-token"
APPROLES_FILE="$OPENBAO_SECRETS_DIR/approles.txt"

# Color output (for readability in CI/CD logs)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[OpenBao]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[OpenBao WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[OpenBao ERROR]${NC} $1"
}

# ============================================================================
# 1. WAIT FOR OPENBAO TO BE READY
# ============================================================================
log_info "Waiting for OpenBao to be ready at $OPENBAO_ADDR..."
for i in $(seq 1 90); do
    if curl -s -m 3 "$OPENBAO_ADDR/v1/sys/health" > /dev/null 2>&1; then
        log_info "OpenBao is ready!"
        break
    fi
    if [ "$i" -eq 90 ]; then
        log_error "OpenBao did not become ready within 90 seconds"
        exit 1
    fi
    echo -n "."
    sleep 1
done

# ============================================================================
# 2. CHECK INITIALIZATION STATUS
# ============================================================================
HEALTH=$(curl -s "$OPENBAO_ADDR/v1/sys/health")
IS_INITIALIZED=$(echo "$HEALTH" | grep -q '"initialized":true' && echo "true" || echo "false")

if [ "$IS_INITIALIZED" = "true" ]; then
    log_warn "OpenBao is already initialized. Skipping init."
    if [ -f "$ROOT_TOKEN_FILE" ]; then
        ROOT_TOKEN=$(cat "$ROOT_TOKEN_FILE")
        export OPENBAO_TOKEN="$ROOT_TOKEN"
    else
        log_warn "No root token file found ($ROOT_TOKEN_FILE). You may need to authenticate manually."
    fi

    # Unseal if sealed after restart
    IS_SEALED=$(curl -s "$OPENBAO_ADDR/v1/sys/health" | jq -r '.sealed')
    if [ "$IS_SEALED" = "true" ]; then
        if [ ! -f "$UNSEAL_KEY_FILE" ]; then
            log_error "OpenBao is sealed and $UNSEAL_KEY_FILE is missing -- cannot unseal automatically."
            exit 1
        fi
        log_info "OpenBao is sealed after restart; unsealing with stored keys..."
        mapfile -t KEY_ARRAY < "$UNSEAL_KEY_FILE"
        for key in "${KEY_ARRAY[@]}"; do
            [ -z "$key" ] && continue
            RESULT=$(curl -s -X POST "$OPENBAO_ADDR/v1/sys/unseal" \
                -H "Content-Type: application/json" \
                -d "{\"key\": \"$key\"}")
            if [ "$(echo "$RESULT" | jq -r '.sealed')" = "false" ]; then
                break
            fi
        done
        if [ "$(curl -s "$OPENBAO_ADDR/v1/sys/health" | jq -r '.sealed')" = "true" ]; then
            log_error "Failed to unseal with the keys in $UNSEAL_KEY_FILE"
            exit 1
        fi
        log_info "OpenBao unsealed."
    fi
else
    log_info "Initializing OpenBao..."

    # ========================================================================
    # 3. INITIALIZE OPENBAO (3-of-5 Shamir key threshold)
    # ========================================================================
    INIT_RESPONSE=$(curl -s -X POST \
        "$OPENBAO_ADDR/v1/sys/init" \
        -H "Content-Type: application/json" \
        -d '{
            "secret_shares": 5,
            "secret_threshold": 3
        }')

    UNSEAL_KEYS=$(echo "$INIT_RESPONSE" | jq -r '.keys[]')
    ROOT_TOKEN=$(echo "$INIT_RESPONSE" | jq -r '.root_token')
    [ "$ROOT_TOKEN" = "null" ] && ROOT_TOKEN=""

    if [ -z "$ROOT_TOKEN" ]; then
        log_error "Failed to extract root token from initialization response"
        echo "$INIT_RESPONSE" | head -20
        exit 1
    fi

    log_info "OpenBao initialized successfully."
    log_info "Root Token: ${ROOT_TOKEN:0:8}... (saved to $ROOT_TOKEN_FILE)"

    # ========================================================================
    # 4. STORE UNSEAL KEY AND ROOT TOKEN
    # ========================================================================
    echo "$ROOT_TOKEN" > "$ROOT_TOKEN_FILE"
    chmod 600 "$ROOT_TOKEN_FILE"
    log_info "Root token stored in $ROOT_TOKEN_FILE (mode 0600)"

    # Store unseal keys
    echo "$UNSEAL_KEYS" > "$UNSEAL_KEY_FILE"
    chmod 600 "$UNSEAL_KEY_FILE"
    log_warn "Unseal key stored in $UNSEAL_KEY_FILE (mode 0600)"
    log_warn "SECURITY: In production, distribute unseal keys to team members and remove from version control."

    # ========================================================================
    # 5. UNSEAL OPENBAO (using first 3 of 5 keys)
    # ========================================================================
    log_info "Unsealing OpenBao with first 3 unseal keys..."
    mapfile -t KEY_ARRAY <<< "$UNSEAL_KEYS"
    for i in {0..2}; do
        curl -s -X POST \
            "$OPENBAO_ADDR/v1/sys/unseal" \
            -H "Content-Type: application/json" \
            -d "{\"key\": \"${KEY_ARRAY[$i]}\"}" > /dev/null
    done
    log_info "OpenBao unsealed."

    # Set root token for subsequent commands
    export OPENBAO_TOKEN="$ROOT_TOKEN"
fi

# Guard: ensure we have a usable token before proceeding
if [ -z "${OPENBAO_TOKEN:-}" ]; then
    log_error "No usable OpenBao token available -- cannot continue setup."
    exit 1
fi

# ============================================================================
# 6. ENABLE AUDIT LOGGING (File backend)
# ============================================================================
log_info "Enabling audit logging..."
curl -s -X POST \
    "$OPENBAO_ADDR/v1/sys/audit/file" \
    -H "X-Vault-Token: $OPENBAO_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "type": "file",
        "options": {
            "file_path": "/openbao/logs/audit.log",
            "hmac_accessor": false,
            "log_raw": false,
            "elide_list_responses": false
        },
        "description": "Audit log for all secret access and policy changes"
    }' 2>/dev/null || log_warn "Audit logging may already be enabled"

log_info "Audit logs will be written to /openbao/logs/audit.log"

# ============================================================================
# 7. REGISTER POLICIES
# ============================================================================
log_info "Registering policies..."

for policy_file in "$OPENBAO_POLICY_DIR"/*.hcl; do
    if [ -f "$policy_file" ]; then
        policy_name=$(basename "$policy_file" .hcl)
        tenant_name="${TENANT_NAME:-zephyr-energy}"
        policy_content=$(sed -e "s/{{TENANT_NAME:-zephyr-energy}}/$tenant_name/g" -e "s/{{TENANT_NAME}}/$tenant_name/g" "$policy_file")

        HTTP_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
            "$OPENBAO_ADDR/v1/sys/policies/acl/$policy_name" \
            -H "X-Vault-Token: $OPENBAO_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"policy\": $(echo "$policy_content" | jq -Rs .)}")

        if [[ "$HTTP_STATUS" =~ ^2[0-9]{2}$ ]]; then
            log_info "Registered policy: $policy_name"
        else
            log_error "Failed to register policy '$policy_name': HTTP $HTTP_STATUS"
        fi
    fi
done

# ============================================================================
# 8. ENABLE KV v2 SECRETS ENGINE (at path 'secret/')
# ============================================================================
log_info "Enabling KV v2 secrets engine..."
curl -s -X POST \
    "$OPENBAO_ADDR/v1/sys/mounts/secret" \
    -H "X-Vault-Token: $OPENBAO_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "type": "kv-v2",
        "description": "KV v2 secrets engine for storing application secrets",
        "options": {
            "version": "2",
            "delete_version_after": "3600s"
        }
    }' 2>/dev/null || log_warn "KV v2 secrets engine may already be enabled"

# ============================================================================
# 9. ENABLE APPROLE AUTHENTICATION
# ============================================================================
APPROLE_ALREADY_ENABLED=false
if curl -s -H "X-Vault-Token: $OPENBAO_TOKEN" "$OPENBAO_ADDR/v1/sys/auth" | grep -q '"approle/"'; then
    APPROLE_ALREADY_ENABLED=true
fi

if [ "$APPROLE_ALREADY_ENABLED" = "false" ]; then
    log_info "Enabling AppRole authentication..."
    curl -s -X POST \
        "$OPENBAO_ADDR/v1/sys/auth/approle" \
        -H "X-Vault-Token: $OPENBAO_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
            "type": "approle",
            "description": "AppRole authentication for microservices",
            "options": {
                "version": "2"
            }
        }' > /dev/null
else
    log_info "AppRole auth method already enabled."
fi

# ============================================================================
# 10. CREATE APPROLE ROLES FOR SERVICES
# ============================================================================
# Skip if roles already exist: every call to create_approle mints a brand
# new secret_id, which would silently invalidate the one any running
# service already holds. This makes the whole script safe to re-run on
# every `docker compose up` without rotating live credentials.
if [ "$APPROLE_ALREADY_ENABLED" = "true" ] && curl -s -o /dev/null -w '%{http_code}' \
        -H "X-Vault-Token: $OPENBAO_TOKEN" \
        "$OPENBAO_ADDR/v1/auth/approle/role/generator-role" | grep -q '^200$'; then
    log_info "AppRole roles already exist; skipping (delete them in OpenBao first to force new secret IDs)."
else
log_info "Creating AppRole roles for services..."

# Helper function to create AppRole
create_approle() {
    local role_name="$1"
    local policy_name="$2"
    local bind_secret_id="${3:-true}"

    log_info "Creating AppRole: $role_name with policy: $policy_name"

    # Create the AppRole
    curl -s -X POST \
        "$OPENBAO_ADDR/v1/auth/approle/role/$role_name" \
        -H "X-Vault-Token: $OPENBAO_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{
            \"token_ttl\": \"3600s\",
            \"token_max_ttl\": \"86400s\",
            \"token_policies\": [\"$policy_name\"],
            \"bind_secret_id\": $bind_secret_id
        }" > /dev/null

    # Get Role ID
    ROLE_ID=$(curl -s \
        -H "X-Vault-Token: $OPENBAO_TOKEN" \
        "$OPENBAO_ADDR/v1/auth/approle/role/$role_name/role-id" | jq -r '.data.role_id')

    # Generate Secret ID (valid for 24 hours)
    SECRET_ID_RESPONSE=$(curl -s -X POST \
        "$OPENBAO_ADDR/v1/auth/approle/role/$role_name/secret-id" \
        -H "X-Vault-Token: $OPENBAO_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
            "ttl": "86400s",
            "response_wrapped": false
        }')

    SECRET_ID=$(echo "$SECRET_ID_RESPONSE" | jq -r '.data.secret_id')

    echo "$role_name|$ROLE_ID|$SECRET_ID"
}

# Generate AppRoles and save to file
{
    echo "# OpenBao AppRole Credentials for Services"
    echo "# Format: role_name|role_id|secret_id"
    echo "# WARNING: Keep these secret! Treat as credentials."
    echo ""
    create_approle "generator-role" "service-policy"
    create_approle "consumer-role" "service-policy"
    create_approle "anomaly-detector-role" "service-policy"
} > "$APPROLES_FILE"

chmod 600 "$APPROLES_FILE"
log_info "AppRole credentials stored in $APPROLES_FILE"

# ============================================================================
# 11. CREATE PER-CUSTOMER APPROLE ROLES
# ============================================================================
# One role per customer policy in openbao/policies/ (excluding the shared
# admin/service policies), so a new customer's policy file gets a role
# automatically without editing this script.
log_info "Creating tenant-specific AppRole roles..."
for policy_file in "$OPENBAO_POLICY_DIR"/*-policy.hcl; do
    [ -f "$policy_file" ] || continue
    policy_name=$(basename "$policy_file" .hcl)
    case "$policy_name" in
        admin-policy|service-policy) continue ;;
    esac
    create_approle "${policy_name%-policy}-role" "$policy_name" || true
done

fi # end: skip-if-approles-already-exist (section 10-11)

# ============================================================================
# 12. VERIFICATION
# ============================================================================
log_info "OpenBao initialization complete!"
echo ""
echo "=== OpenBao Summary ==="
echo "Address: $OPENBAO_ADDR"
echo "Status: Unsealed and ready"
echo "Root Token: ${ROOT_TOKEN:0:20}... (saved to $ROOT_TOKEN_FILE)"
echo "Unseal Key: $(head -c 20 "$UNSEAL_KEY_FILE")... (saved to $UNSEAL_KEY_FILE)"
echo "AppRole Credentials: $APPROLES_FILE"
echo ""
echo "=== Next Steps ==="
echo "1. Keep $APPROLES_FILE out of version control (already gitignored) -- treat it as live credentials"
echo "2. Update app/secrets_loader.py with AppRole credentials"
echo "3. Run migration/migrate_secrets.py to populate secrets"
echo "4. Test service authentication: bash openbao/test-approle.sh"
echo ""
echo "=== Security Checklist ==="
echo "[ ] Store root token securely (AWS Secrets Manager, 1Password, etc.)"
echo "[ ] Distribute unseal keys to team members (3 of 5 threshold needed)"
echo "[ ] Remove unseal key from version control before production deployment"
echo "[ ] Test disaster recovery: unseal with 3 different unseal keys"
echo "[ ] Enable OIDC or other auth methods for human access (recommended)"
echo "[ ] Rotate AppRole secret IDs weekly in production"
echo ""
