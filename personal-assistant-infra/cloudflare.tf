resource "cloudflare_hyperdrive_config" "personal_assistant" {
  account_id = var.cloudflare_account_id
  name       = "pa-postgresql"

  origin = {
    host     = huaweicloud_vpc_eip.rds.address
    port     = 5432
    database = huaweicloud_rds_pg_database.application.name
    user     = huaweicloud_rds_pg_account.application.name
    password = var.rds_password
    scheme   = "postgresql"
  }

  mtls = {
    sslmode = "require"
  }

  # The Functions workload includes writes and read-after-write behavior.
  caching = {
    disabled = true
  }
}

resource "cloudflare_pages_project" "personal_assistant" {
  account_id        = var.cloudflare_account_id
  name              = var.cloudflare_pages_project_name
  production_branch = var.cloudflare_production_branch

  deployment_configs = {
    production = {
      compatibility_date  = "2026-06-18"
      compatibility_flags = ["nodejs_compat"]

      hyperdrive_bindings = {
        HYPERDRIVE = {
          id = cloudflare_hyperdrive_config.personal_assistant.id
        }
      }

      env_vars = {
        AGENTARTS_INVOCATIONS_URL = {
          type  = "plain_text"
          value = var.agentarts_invocations_url
        }
        RUNTIME_PREWARM_TIMEOUT_MS = {
          type  = "plain_text"
          value = tostring(var.runtime_prewarm_timeout_ms)
        }
        OIDC_JWKS_URL = {
          type  = "plain_text"
          value = var.oidc_jwks_url
        }
        OIDC_ISSUER = {
          type  = "plain_text"
          value = var.oidc_issuer
        }
        OIDC_AUDIENCE = {
          type  = "plain_text"
          value = var.oidc_audience
        }
      }
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
