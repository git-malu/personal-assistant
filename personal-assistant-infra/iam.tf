# ============================================================
# IAM Agency — AgentArts Identity STS outbound OBS read-only
# ============================================================

resource "huaweicloud_identity_role" "obs_sts_read_only" {
  name        = var.obs_sts_policy_name
  description = "Personal Assistant OBS read-only policy for AgentArts STS outbound tools"
  type        = "AX"

  policy = jsonencode({
    Version = "1.1"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "obs:bucket:ListBucket",
          "obs:object:GetObject",
          "obs:object:GetObjectVersion"
        ]
        Resource = [
          "obs:*:*:*:*",
          "obs:*:*:*:*/*"
        ]
      }
    ]
  })
}

resource "huaweicloud_identity_agency" "agentarts_obs_sts" {
  name                  = var.obs_sts_agency_name
  description           = "Agency assumed by AgentArts Identity STS provider for OBS read-only outbound access"
  delegated_domain_name = var.agentarts_delegated_domain_name

  all_resources_roles = [huaweicloud_identity_role.obs_sts_read_only.name]
}
