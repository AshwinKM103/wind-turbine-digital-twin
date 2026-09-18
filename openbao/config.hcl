# OpenBao Configuration (Reference for advanced deployments)
#
# This file is NOT used by default. It's provided as a reference for
# users who want to configure OpenBao with custom settings beyond the
# docker-compose.yml OPENBAO_LOCAL_CONFIG environment variable.
#
# To use this config, mount it into the container:
#
#   volumes:
#     - ./.claude/openbao/config.hcl:/openbao/config.hcl
#   entrypoint: openbao server -config=/openbao/config.hcl

# =========================================================================
# STORAGE
# =========================================================================
# Integrated Raft storage (single-node, no external dependencies)
# For cluster deployments, consider using Consul or S3 backend instead.

storage "raft" {
  # Path to store encrypted data
  path = "/openbao/data"
  # Unique node name (required for clustering)
  node_id = "raft_node_1"
  # High availability failover (clustering only)
  # retry_join = [
  #   "openbao-node-2:8201",
  #   "openbao-node-3:8201",
  # ]
}

# =========================================================================
# LISTENERS
# =========================================================================
# Accept connections from services and users

listener "tcp" {
  # Bind to all interfaces (required for Docker networking)
  address = "0.0.0.0:8200"

  # TLS configuration (production: enable and use real certificates)
  tls_disable = true
  # tls_cert_file  = "/openbao/certs/server.crt"
  # tls_key_file   = "/openbao/certs/server.key"
  # tls_min_version = "tls12"

  # CORS (for web UI and API clients)
  cors_enabled = true
  cors_allowed_headers = [
    "Content-Type",
    "X-Requested-With",
    "X-Vault-Token",
  ]
  cors_allowed_origins = [
    "http://localhost:8200",
    # In production: restrict to your domain
    # "https://openbao.yourcompany.com",
  ]
}

# =========================================================================
# SERVICE REGISTRATION (OPTIONAL)
# =========================================================================
# For high availability and auto-discovery
# Comment out in single-node deployments

# service_registration "kubernetes" {
#   namespace = "default"
# }

# =========================================================================
# TELEMETRY (MONITORING)
# =========================================================================
# Prometheus metrics for monitoring (optional)

telemetry {
  # Export Prometheus metrics (requires scraper to collect)
  prometheus_retention_time = "30s"

  # Send metrics to external service (optional)
  # statsite_address = "localhost:8125"
  # statsd_address   = "localhost:8125"
}

# =========================================================================
# UI
# =========================================================================
# Enable the web UI (useful for development, restrict in production)

ui = true

# =========================================================================
# LOGGING
# =========================================================================
# Log level: trace, debug, info, warn, error

log_level = "info"

# =========================================================================
# REPLICATION (CLUSTERING)
# =========================================================================
# For multi-node deployments (not used in single-node setup)

# replication {
#   resolver "dns" {
#     addr = "consul.service.consul"
#     service_name = "openbao"
#   }
# }

# =========================================================================
# HIGH AVAILABILITY
# =========================================================================
# Raft provides built-in HA (leader election, failover)
# No additional config needed for single-node.
# For multi-node, configure retry_join in storage block above.

# =========================================================================
# AUTO UNSEAL (CLOUD DEPLOYMENTS)
# =========================================================================
# Use cloud provider's KMS for automatic unsealing (production)
# Requires cloud credentials and IAM permissions.

# seal "awskms" {
#   region     = "us-west-2"
#   kms_key_id = "arn:aws:kms:us-west-2:123456789012:key/12345678-1234-1234-1234-123456789012"
# }

# seal "gcpkms" {
#   project    = "my-project"
#   region     = "global"
#   key_ring   = "openbao-key-ring"
#   crypto_key = "openbao-master-key"
# }

# =========================================================================
# ADVANCED SETTINGS
# =========================================================================

# Disable mlock for performance (production: enable with sufficient privileges)
disable_mlock = true

# =========================================================================
# PLUGINS
# =========================================================================
# Load external secret engines or auth methods (optional)

# plugin_directory = "/openbao/plugins"
