# Admin policy: Full access to all secrets and audit logs.
# Used only for infrastructure automation and disaster recovery.
# All admin access is audit-logged and requires MFA in production.

# Secrets engines: Full access
path "secret/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "database/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# AppRole: Create and manage roles
path "auth/approle/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Audit logs: Read-only (not delete)
path "sys/audit" {
  capabilities = ["list", "read"]
}

path "sys/audit/*" {
  capabilities = ["list", "read"]
}

# Policies: Full access
path "sys/policies/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Tokens: Manage
path "auth/token/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Sys config: Read-only
path "sys/config/*" {
  capabilities = ["read", "list"]
}

# Rekey/unseal: This is admin-only
path "sys/unseal" {
  capabilities = ["update"]
}

path "sys/rekey/*" {
  capabilities = ["create", "read", "update", "list"]
}
