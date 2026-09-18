# Tenant-specific secrets access.
# Can read only secrets for this customer namespace.
# Enforces multi-tenant data isolation at the Vault layer (default-deny applies to all unlisted paths).

# Read-only access to tenant secrets
path "secret/data/{{TENANT_NAME:-zephyr-energy}}/*" {
  capabilities = ["read", "list"]
}

# Database credentials (read-only): allows rotation tracking
path "database/static-creds/{{TENANT_NAME:-zephyr-energy}}-*" {
  capabilities = ["read"]
}

# Deny access to shared service secrets
path "secret/data/shared/*" {
  capabilities = ["deny"]
}

# Self-renew token (standard practice)
path "auth/token/renew-self" {
  capabilities = ["update"]
}
