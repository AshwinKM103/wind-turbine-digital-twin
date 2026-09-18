# Service Policy: Microservices (generators, consumer, anomaly detector).
# Services need read access to all customer secrets for aggregation and routing.
# This is more permissive than per-tenant policies because services are
# infrastructure components, not customer identities.
#
# In production: Consider creating separate policies per service type if
# you want to further isolate them (e.g., generator-service-policy).

# Read access to all customer secrets and shared secrets (needed for multi-tenant aggregation)
path "secret/data/*" {
  capabilities = ["read", "list"]
}

# Database dynamic credentials (services can fetch ephemeral credentials)
path "database/static-creds/+/username" {
  capabilities = ["read"]
}

path "database/static-creds/+/password" {
  capabilities = ["read"]
}

# Self-renew token
path "auth/token/renew-self" {
  capabilities = ["update"]
}

# Token lookup (for debugging)
path "auth/token/lookup-self" {
  capabilities = ["read"]
}
