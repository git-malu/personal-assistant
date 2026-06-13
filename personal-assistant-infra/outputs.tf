# ============================================================
# Stack Outputs
# ============================================================
# 供 Service 配置及部署脚本引用

output "bucket_name" {
  description = "OBS Bucket 名称"
  value       = huaweicloud_obs_bucket.web_chat.bucket
}

output "website_endpoint" {
  description = "OBS 静态网站托管 endpoint（SPA 入口 — 仅调试，浏览器会触发下载）"
  value       = "https://${huaweicloud_obs_bucket.web_chat.bucket}.obs-website.${var.region}.myhuaweicloud.com"
}

output "custom_domain" {
  description = "自定义域名（浏览器正常渲染，无 Content-Disposition: attachment）"
  value       = "https://chat.resource-governance.cloud"
}

output "obs_sts_agency_name" {
  description = "AgentArts Identity STS Provider 绑定的 IAM Agency 名称"
  value       = huaweicloud_identity_agency.agentarts_obs_sts.name
}

output "obs_sts_policy_name" {
  description = "OBS read-only custom policy 名称"
  value       = huaweicloud_identity_role.obs_sts_read_only.name
}

# ⚠️ 注意：HuaweiCloud Provider 凭据（AK/SK）通过原生环境变量
# HW_ACCESS_KEY / HW_SECRET_KEY 注入，不再通过 variables.tf 中转。
