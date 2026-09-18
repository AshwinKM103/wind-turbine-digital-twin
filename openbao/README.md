# OpenBao Secrets Manager - Complete Implementation Guide

**Status**: Production-ready integration for multi-tenant wind turbine digital twin system

**Deployment Model**: OpenBao single-node with integrated Raft storage, AppRole authentication, and per-tenant access control

**Security Level**: Suitable for staging/production with proper unseal key management and TLS

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Quick Start (5 minutes)](#quick-start-5-minutes)
3. [Complete Setup (20 minutes)](#complete-setup-20-minutes)
4. [Services Integration](#services-integration)
5. [Multi-Tenant Isolation](#multi-tenant-isolation)
6. [Security Procedures](#security-procedures)
7. [Troubleshooting](#troubleshooting)
8. [Production Deployment](#production-deployment)

---

## Architecture Overview

### Current Problem (Before OpenBao)

```
❌ .env file on disk
   ├─ Contains all credentials (root password, API keys, etc.)
   ├─ Readable by any process with file access
   ├─ Committed accidentally to git (audit nightmare)
   ├─ No rotation mechanism
   └─ No audit trail
```

### Solved Problem (With OpenBao)

```
✅ Centralized Secrets Manager
   ├─ Credentials stored in encrypted Raft storage
   ├─ AppRole authentication (role_id + secret_id only, no passwords)
   ├─ Audit logging (every access recorded)
   ├─ Multi-tenant isolation (each customer sees only their secrets)
   └─ Future: Dynamic secrets with auto-rotation
```

### Deployment Stack

| Component | Purpose | Storage |
|-----------|---------|---------|
| **OpenBao** | Secrets manager | Raft (encrypted) |
| **PostgreSQL** | Alerts & KPI timeline | PostgreSQL data volume |
| **Apache IoTDB** | Time-series telemetry | IoTDB data volume |
| **Kafka** | Event broker | Zookeeper + Kafka logs |
| **Microservices** | Turbine generators, consumer, anomaly detector | Code + logs |

### Network Diagram

```
┌─────────────────────────── Docker Network (turbine-net) ────────────────────────────┐
│                                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐     │
│  │   OpenBao    │    │   Kafka      │    │   IoTDB      │    │  PostgreSQL  │     │
│  │  :8200       │    │   :29092     │    │   :6667      │    │   :5432      │     │
│  │  (Raft)      │    │              │    │              │    │              │     │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └──────┬───────┘     │
│         │                   │                   │                   │              │
│         └───────────────────┼───────────────────┼───────────────────┘              │
│                             │                   │                                  │
│         ┌───────────────────┴───────────────────┴──────────────┐                   │
│         │                                                      │                   │
│  ┌──────▼─────────┐  ┌──────────────┐  ┌──────────────┐      │                   │
│  │   Generator    │  │   Consumer   │  │   Anomaly    │      │                   │
│  │   Services     │  │   Service    │  │   Detector   │      │                   │
│  │  (50 turbines) │  │              │  │              │      │                   │
│  └────────────────┘  └──────────────┘  └──────────────┘      │                   │
│         │                   │                   │              │                   │
│         └───────────────────┼───────────────────┼──────────────┘                   │
│                             │                   │                                  │
│                  All services authenticate to OpenBao via AppRole                  │
│                  (role_id + secret_id → short-lived token)                        │
│                                                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start (5 minutes)

### Prerequisites

- Docker & Docker Compose installed
- `.env` file with current credentials (backup before proceeding)
- Git (to track changes)

### Step-by-Step

#### 1. Start OpenBao Container

```bash
docker compose up -d openbao
sleep 3
```

Verify:

```bash
curl -s http://localhost:8200/v1/sys/health | jq .
# Expected: {"initialized":false,"sealed":true,...}
```

#### 2. Initialize OpenBao

This is a one-time operation that generates unseal keys and root token:

```bash
./openbao/init-openbao.sh
```

**IMPORTANT**: Save the output containing:
- Root Token (in `.openbao-root-token`)
- Unseal Keys (in `.openbao-unseal-key`)

**Security Note**: In production, distribute the 5 unseal keys among 5 team members. Only 3 are needed to unseal.

#### 3. Migrate Secrets

Move all credentials from `.env` to OpenBao:

```bash
# Dry run (no changes)
python migration/migrate_secrets.py --dry-run

# Actually migrate
python migration/migrate_secrets.py

# Verify
python migration/migrate_secrets.py
```

#### 4. Test Multi-Tenant Isolation

```bash
bash openbao/test-approle.sh
```

Expected output shows:
- ✓ AppRole authentication works
- ✓ Services can read their secrets
- ✓ Tenants isolated (cannot read each other's secrets)

---

## Complete Setup (20 minutes)

### 1. Initialize OpenBao (if not already done)

```bash
docker compose up -d openbao
./openbao/init-openbao.sh
```

### 2. Verify Policies Are Registered

```bash
ROOT_TOKEN=$(cat .openbao-root-token)

# List all policies
curl -s -H "X-Vault-Token: $ROOT_TOKEN" \
  http://localhost:8200/v1/sys/policies/acl | jq .data.policies

# Expected output:
# ["admin-policy","aurora-power-policy","ecowatt-renewable-policy",
#  "service-policy","skygale-solutions-policy","windstream-utilities-policy",
#  "zephyr-energy-policy"]
```

### 3. Migrate Secrets from .env

```bash
python migration/migrate_secrets.py
```

### 4. Create AppRole Credentials in docker-compose.yml

Edit `docker-compose.yml` and add environment variables to each service:

```yaml
services:
  generator-czephyr-energy-tboreas:
    environment:
      # Add these (from openbao/approles.txt)
      - OPENBAO_ADDR=http://openbao:8200
      - OPENBAO_ROLE_ID=<copy-from-approles.txt>
      - OPENBAO_SECRET_ID=<copy-from-approles.txt>
    depends_on:
      openbao:
        condition: service_healthy

  kafka-consumer:
    environment:
      - OPENBAO_ADDR=http://openbao:8200
      - OPENBAO_ROLE_ID=<consumer-role-id>
      - OPENBAO_SECRET_ID=<consumer-role-secret>
    depends_on:
      openbao:
        condition: service_healthy

  anomaly-detector:
    environment:
      - OPENBAO_ADDR=http://openbao:8200
      - OPENBAO_ROLE_ID=<detector-role-id>
      - OPENBAO_SECRET_ID=<detector-role-secret>
    depends_on:
      openbao:
        condition: service_healthy
```

### 5. Enable Secret Loading in Services

Modify each service's main entry point:

**app/src/kafka_consumer.py**:

```python
import secrets_loader

def main():
    # Load secrets from OpenBao (or fall back to .env)
    if os.environ.get("OPENBAO_DISABLED") != "true":
        secrets_loader.load_secrets_from_openbao()
    
    # Rest of the code
    from src.config import Config
    # ... start consumer
```


```python
import secrets_loader

def main():
    # Load secrets from OpenBao
    if os.environ.get("OPENBAO_DISABLED") != "true":
        secrets_loader.load_secrets_from_openbao()
    
    # Rest of code
```

**app/src/anomaly_detection.py**:

```python
import secrets_loader

def main():
    # Load secrets from OpenBao
    if os.environ.get("OPENBAO_DISABLED") != "true":
        secrets_loader.load_secrets_from_openbao()
    
    # Rest of code
```

### 6. Test Integration

Start services and verify they can fetch secrets:

```bash
# Build Docker image with updated code
docker compose build

# Start all services
docker compose up -d

# Check logs for successful secret loading
docker logs kafka-consumer | grep "Successfully loaded"
docker logs generator-czephyr-energy-tboreas | grep "Loaded secret"
```

### 7. Verify End-to-End

```bash
# Check IoTDB is receiving data
curl -s http://localhost:18080/rest/v1/query \
  -H "Authorization: Basic cm9vdDpyb290" \
  -d "select * from root.digitaltwin.zephyr-energy.cascade-ridge.boreas"

# Check Postgres alerts are being written
docker exec turbine-postgres psql -U turbine turbine -c \
  "SELECT count(*) FROM alerts WHERE created_at > now() - interval '5 minutes';"

# Check audit logs
docker exec turbine-openbao tail -20 /openbao/logs/audit.log | jq .
```

---

## Services Integration

### Microservices Using OpenBao

| Service | Purpose | Secrets Needed |
|---------|---------|----------------|
| **kafka_consumer.py** | Read Kafka, write to IoTDB | `KAFKA_BOOTSTRAP_SERVERS`, `IOTDB_HOST`, `IOTDB_PORT`, `IOTDB_USER`, `IOTDB_PASSWORD` |
| **anomaly_detection.py** | Detect anomalies, write alerts | `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `IOTDB_*` |

### Example: Enabling Consumer Service

**Current setup (.env-based)**:

```bash
docker compose up kafka-consumer
# Uses: IOTDB_PASSWORD from .env
# Issue: Password visible in .env, docker-compose.yml, process env
```

**With OpenBao**:

```yaml
services:
  kafka-consumer:
    image: turbine-digitaltwin-app:latest
    container_name: turbine-kafka-consumer
    command: ["python", "kafka_consumer.py"]
    depends_on:
      openbao:
        condition: service_healthy
    environment:
      # No IOTDB_PASSWORD here!
      - KAFKA_BOOTSTRAP_SERVERS_INTERNAL=kafka:29092
      - IOTDB_HOST=iotdb
      - IOTDB_PORT=6667
      - OPENBAO_ADDR=http://openbao:8200
      - OPENBAO_ROLE_ID=<from approles.txt>
      - OPENBAO_SECRET_ID=<from approles.txt>
    volumes:
      - ./app:/app
      - ./app/logs:/app/logs
    networks:
      - turbine-net
```

**In kafka_consumer.py**:

```python
#!/usr/bin/env python3

import secrets_loader
import os
import sys

def main():
    # FIRST: Load secrets from OpenBao
    try:
        secrets_loader.load_secrets_or_die("kafka-consumer")
    except Exception as e:
        print(f"Fatal: Could not load secrets: {e}", file=sys.stderr)
        sys.exit(1)
    
    # NOW: Config loads from os.environ (which includes OpenBao secrets)
    from src.config import Config
    from src.kafka_consumer import KafkaConsumer
    
    consumer = KafkaConsumer()
    consumer.start()  # Uses Config.IOTDB_PASSWORD etc. from OpenBao

if __name__ == "__main__":
    main()
```

---

## Multi-Tenant Isolation

### How Isolation Works

Each customer has a separate HCL policy that restricts access to their secrets only:

**zephyr-energy-policy.hcl**:

```hcl
path "secret/data/zephyr-energy/*" {
  capabilities = ["read", "list"]
}

# Explicit denies for other customers
path "secret/data/aurora-power/*" {
  capabilities = ["deny"]
}
```

### Testing Tenant Isolation

Simulate a compromised tenant's AppRole credentials:

```bash
# Get Zephyr Energy's credentials
ZEPHYR_ROLE_ID="..."  # from approles.txt
ZEPHYR_SECRET_ID="..."

# Authenticate as Zephyr
ZEPHYR_TOKEN=$(curl -s -X POST http://localhost:8200/v1/auth/approle/login \
  -H "Content-Type: application/json" \
  -d "{\"role_id\":\"$ZEPHYR_ROLE_ID\",\"secret_id\":\"$ZEPHYR_SECRET_ID\"}" \
  | jq -r '.auth.client_token')

# Try to read Zephyr's secrets (should work)
curl -s -H "X-Vault-Token: $ZEPHYR_TOKEN" \
  http://localhost:8200/v1/secret/data/zephyr-energy/all-credentials

# Try to read Aurora's secrets (should DENY)
curl -s -H "X-Vault-Token: $ZEPHYR_TOKEN" \
  http://localhost:8200/v1/secret/data/aurora-power/all-credentials
# Expected response: {"errors":["permission denied"]}
```

### Adding a New Tenant

When a new customer signs up:

1. Create policy file:

```bash
cat > openbao/policies/new-customer-policy.hcl <<EOF
path "secret/data/new-customer/*" {
  capabilities = ["read", "list"]
}

# Deny access to other customers
path "secret/data/*" {
  capabilities = ["deny"]
}

path "auth/token/renew-self" {
  capabilities = ["update"]
}
EOF
```

2. Re-run init script (or manually register):

```bash
ROOT_TOKEN=$(cat .openbao-root-token)

curl -X POST http://localhost:8200/v1/sys/policies/acl/new-customer-policy \
  -H "X-Vault-Token: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"policy\": $(cat openbao/policies/new-customer-policy.hcl | jq -Rs .)}"
```

3. Create AppRole for customer (if they need API access):

```bash
curl -X POST http://localhost:8200/v1/auth/approle/role/new-customer-api \
  -H "X-Vault-Token: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "token_ttl": "3600s",
    "token_policies": ["new-customer-policy"]
  }'
```

4. Add customer secrets:

```bash
curl -X POST http://localhost:8200/v1/secret/data/new-customer/all-credentials \
  -H "X-Vault-Token: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "IOTDB_USER": "new-customer-user",
      "IOTDB_PASSWORD": "secure-password"
    }
  }'
```

---

## Security Procedures

### Regular Security Tasks

#### Weekly: Rotate AppRole Secret IDs

```bash
ROOT_TOKEN=$(cat .openbao-root-token)

# Generate new Secret ID
NEW_SECRET=$(curl -s -X POST http://localhost:8200/v1/auth/approle/role/generator-role/secret-id \
  -H "X-Vault-Token: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ttl":"86400s"}' | jq -r '.data.secret_id')

echo "New Secret ID: $NEW_SECRET"
# Update docker-compose.yml and restart services
```

#### Monthly: Review Audit Logs

```bash
# Extract failed authentication attempts
docker exec turbine-openbao jq -r \
  'select(.auth.successful==false) | "\(.request_time) \(.auth.metadata.role_name) \(.error)"' \
  /openbao/logs/audit.log | tail -20

# Count secret accesses by service
docker exec turbine-openbao jq -r \
  'select(.request_path | contains("secret/data")) | .auth.metadata.role_name' \
  /openbao/logs/audit.log | sort | uniq -c
```

#### Quarterly: Disaster Recovery Drill

Test that unseal works with 3 different keys:

```bash
# Seal OpenBao
docker exec turbine-openbao openbao operator seal

# Verify sealed
curl -s http://localhost:8200/v1/sys/health | jq .sealed

# Unseal with 3 keys (from team members)
KEY1="<member-1-unseal-key>"
KEY2="<member-2-unseal-key>"
KEY3="<member-3-unseal-key>"

for key in "$KEY1" "$KEY2" "$KEY3"; do
  curl -X POST http://localhost:8200/v1/sys/unseal \
    -H "Content-Type: application/json" \
    -d "{\"key\":\"$key\"}"
done

# Verify unsealed
curl -s http://localhost:8200/v1/sys/health | jq .sealed
# Expected: false
```

### Backup Procedures

#### Automated Backup (Recommended)

```bash
#!/bin/bash
# openbao-backup.sh

BACKUP_DIR="/backups/openbao"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup of Raft storage
docker exec turbine-openbao tar -czf - \
  -C /openbao data | \
  gpg -c --output "$BACKUP_DIR/openbao-backup-$DATE.tar.gz.gpg"

# Verify backup
if gpg -t "$BACKUP_DIR/openbao-backup-$DATE.tar.gz.gpg" 2>/dev/null; then
  echo "✓ Backup verified: $BACKUP_DIR/openbao-backup-$DATE.tar.gz.gpg"
else
  echo "✗ Backup failed!"
  exit 1
fi

# Keep only last 30 days
find "$BACKUP_DIR" -name "*.gpg" -mtime +30 -delete
```

Schedule with cron:

```bash
# Daily backup at 2 AM
0 2 * * * /opt/bin/openbao-backup.sh >> /var/log/openbao-backup.log 2>&1
```

#### Restore from Backup

```bash
# Stop OpenBao
docker compose down openbao

# Decrypt and restore backup
gpg -d "$BACKUP_DIR/openbao-backup-20260908_020000.tar.gz.gpg" | \
  tar -xz -C ./data/openbao/

# Start OpenBao (still sealed, needs unseal keys)
docker compose up -d openbao

# Unseal with 3 keys
# (same procedure as disaster recovery drill above)
```

---

## Troubleshooting

### Symptoms & Solutions

#### 1. Service Can't Connect to OpenBao

**Symptom**: `Connection refused` or `Name resolution failed`

**Root Cause**: OpenBao container not running or network unreachable

**Fix**:

```bash
# Check OpenBao is running
docker ps | grep openbao

# Check health
curl -s http://localhost:8200/v1/sys/health

# Check network connectivity from service
docker exec kafka-consumer ping -c 1 openbao

# Verify docker-compose.yml networks section
docker network inspect turbine-net | jq '.Containers'
```

#### 2. AppRole Login Fails

**Symptom**: `AppRole login failed: HTTP 400: invalid request`

**Root Cause**: Wrong role_id or secret_id

**Fix**:

```bash
# Verify role exists
ROOT_TOKEN=$(cat .openbao-root-token)
curl -s -H "X-Vault-Token: $ROOT_TOKEN" \
  http://localhost:8200/v1/auth/approle/role/generator-role

# Verify role_id matches
curl -s -H "X-Vault-Token: $ROOT_TOKEN" \
  http://localhost:8200/v1/auth/approle/role/generator-role/role-id | jq .

# Generate new secret_id if needed
curl -X POST http://localhost:8200/v1/auth/approle/role/generator-role/secret-id \
  -H "X-Vault-Token: $ROOT_TOKEN"
```

#### 3. Secrets Not Accessible

**Symptom**: `permission denied` when reading secrets

**Root Cause**: Policy doesn't allow reading that path

**Fix**:

```bash
# Check policy
ROOT_TOKEN=$(cat .openbao-root-token)
curl -s -H "X-Vault-Token: $ROOT_TOKEN" \
  http://localhost:8200/v1/sys/policies/acl/service-policy | jq .

# Check token's policies
TOKEN="<service-token>"
curl -s -H "X-Vault-Token: $TOKEN" \
  http://localhost:8200/v1/auth/token/lookup-self | jq .data.policies

# Test with root token (should work)
curl -s -H "X-Vault-Token: $ROOT_TOKEN" \
  http://localhost:8200/v1/secret/data/shared/iotdb
```

#### 4. Disk Full

**Symptom**: `no space left on device` or Raft storage corruption

**Root Cause**: Audit logs or Raft data exceeding disk capacity

**Fix**:

```bash
# Check disk usage
df -h ./data/openbao/

# Clean old audit logs (keep last 1GB)
docker exec turbine-openbao sh -c \
  'du -sh /openbao/logs/audit.log && rm /openbao/logs/audit.log && touch /openbao/logs/audit.log'

# Set up log rotation
docker exec turbine-openbao cron -f  # Inside container

# Or clean backup files
rm -f ./data/openbao/data/raft/snapshots/old-*
```

---

## Production Deployment

### Pre-Production Checklist

- [ ] Use managed OpenBao (AWS Secrets Manager, HashiCorp Cloud) or hardened VM
- [ ] Enable TLS/HTTPS (self-signed certificates at minimum)
- [ ] Implement auto-unseal via cloud KMS (AWS, GCP, Azure)
- [ ] Distribute 5 unseal keys to team members (3-of-5 threshold)
- [ ] Store root token in secure vault (1Password, Bitwarden, AWS Secrets Manager)
- [ ] Configure automated backups with encryption
- [ ] Enable audit log shipping to SIEM (Splunk, DataDog, CloudWatch)
- [ ] Rotate AppRole secret IDs weekly (automate if possible)
- [ ] Set up monitoring & alerting (disk, unsealed status, token expiry)
- [ ] Test disaster recovery (full unseal from backup)
- [ ] Create runbook for on-call engineer
- [ ] Pass security audit/compliance review

### Production-Grade Deployment

Use HashiCorp Cloud Platform or AWS:

```yaml
# Example: AWS + Terraform
resource "aws_secretsmanager_secret" "openbao_unseal_key" {
  name       = "prod/openbao/unseal-key"
  kms_key_id = aws_kms_key.openbao.id
}

resource "aws_secretsmanager_secret_version" "openbao_unseal_key" {
  secret_id       = aws_secretsmanager_secret.openbao_unseal_key.id
  secret_string   = jsonencode({
    unseal_keys = [...]
  })
}
```

Then fetch at startup:

```bash
# In deployment script
UNSEAL_KEYS=$(aws secretsmanager get-secret-value \
  --secret-id prod/openbao/unseal-key \
  --query SecretString \
  --output text | jq -r '.unseal_keys[]')

for key in $UNSEAL_KEYS; do
  curl -X POST https://openbao.prod.company.com/v1/sys/unseal \
    -d "{\"key\":\"$key\"}"
done
```

---

## Support & Documentation

- **OpenBao Official Docs**: https://openbao.org/docs/
- **Vault Docs** (OpenBao compatible): https://www.vaultproject.io/docs/
- **This System**: See `openbao/README.md` for detailed operations guide

---

## Summary

| Aspect | Before OpenBao | After OpenBao |
|--------|-----------------|---------------|
| Secrets Storage | `.env` file (plaintext) | Encrypted Raft storage |
| Authentication | Environment variables | AppRole (role_id + secret_id) |
| Audit Trail | None | Every access logged |
| Multi-Tenancy | No isolation | Per-policy tenant isolation |
| Rotation | Manual password changes | Centralized secret updates |
| Compliance | No (impossible to audit) | Yes (full audit trail) |
| Secret Expiry | N/A | Tokens auto-expire |
| Disaster Recovery | Backup .env | Raft backups + unseal key distribution |

**Result**: Production-ready secrets management with full compliance and audit trail.

---

Last Updated: 2026-09-08  
Maintained by: Infrastructure Security Team
