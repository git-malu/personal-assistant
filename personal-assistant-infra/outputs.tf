output "rds_instance_id" {
  description = "RDS PostgreSQL Instance ID"
  value       = huaweicloud_rds_instance.postgresql.id
}

output "rds_private_ips" {
  description = "RDS PostgreSQL Private IP 地址"
  value       = huaweicloud_rds_instance.postgresql.private_ips
}

output "rds_public_ip" {
  description = "RDS PostgreSQL 公网 EIP；用于构造 POSTGRES_DSN"
  value       = huaweicloud_vpc_eip.rds.address
}

output "rds_database_name" {
  description = "应用数据库名称"
  value       = huaweicloud_rds_pg_database.application.name
}

output "cloudflare_hyperdrive_id" {
  description = "Hyperdrive configuration ID bound to Pages Functions"
  value       = cloudflare_hyperdrive_config.personal_assistant.id
}

output "cloudflare_pages_subdomain" {
  description = "Cloudflare Pages project subdomain"
  value       = cloudflare_pages_project.personal_assistant.subdomain
}
