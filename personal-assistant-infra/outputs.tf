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

# ⚠️ 注意：terraform.tfvars 文件包含敏感信息（AK/SK），已通过 .gitignore 排除。
# 实际 variables.tf 中的 ak/sk 变量通过 .tfvars 或环境变量 TF_VAR_* 注入。
