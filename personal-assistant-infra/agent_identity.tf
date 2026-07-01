# ============================================================
# Agent Identity — OAuth2 return URL allowlist bridge
# ============================================================
# The HuaweiCloud OpenTofu provider does not currently expose AgentArts
# Agent Identity resources, so this bridges the control-plane update through
# the idempotent SDK helper in this infra directory.

locals {
  calendar_oauth2_workload_identity_name = "agent-personal-assistant"
  calendar_oauth2_return_urls = [
    "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar",
    "http://localhost:5173/auth/callback/m365-calendar",
  ]
}

resource "terraform_data" "calendar_oauth2_return_url_allowlist" {
  input = {
    workload_identity_name = local.calendar_oauth2_workload_identity_name
    return_urls            = local.calendar_oauth2_return_urls
    region                 = var.region
  }

  triggers_replace = {
    workload_identity_name = local.calendar_oauth2_workload_identity_name
    return_urls            = local.calendar_oauth2_return_urls
    region                 = var.region
  }

  provisioner "local-exec" {
    working_dir = path.module
    command = join(" ", concat(
      [
        "uv",
        "run",
        "python",
        "scripts/configure_calendar_oauth_return_url.py",
        "--workload-identity-name",
        local.calendar_oauth2_workload_identity_name,
        "--region",
        var.region,
      ],
      flatten([
        for return_url in local.calendar_oauth2_return_urls : [
          "--return-url",
          return_url,
        ]
      ]),
      [
        "--apply",
      ],
    ))
  }
}
