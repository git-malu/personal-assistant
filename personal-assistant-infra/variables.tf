# ============================================================
# 变量声明
# ============================================================
# region 等非敏感变量在此声明。
# HuaweiCloud Provider 凭据（AK/SK）通过 Provider 原生环境变量
# HW_ACCESS_KEY / HW_SECRET_KEY 注入，无需通过 Terraform 变量中转。

variable "region" {
  description = "HuaweiCloud 区域"
  type        = string
  default     = "cn-southwest-2"
}

variable "vpc_name" {
  description = "RDS 所在的 VPC 名称"
  type        = string
  default     = "vpc-default-smb"
}

variable "subnet_name" {
  description = "RDS 所在的子网名称"
  type        = string
  default     = "subnet-default-smb"
}

variable "rds_availability_zone" {
  description = "RDS 主可用区"
  type        = string
  default     = "cn-southwest-2f"
}

variable "rds_flavor" {
  description = "RDS PostgreSQL 规格"
  type        = string
  default     = "rds.pg.n1.medium.2"
}

variable "rds_application_username" {
  description = "应用连接 RDS 使用的账号"
  type        = string
  default     = "pa_app"
}

variable "rds_database_name" {
  description = "Personal Assistant 应用数据库名称"
  type        = string
  default     = "personal_assistant"
}

variable "rds_eip_type" {
  description = "RDS EIP 类型；5_bgp 为动态 BGP"
  type        = string
  default     = "5_bgp"
}

variable "rds_eip_bandwidth_size" {
  description = "RDS EIP 带宽上限，单位 Mbit/s"
  type        = number
  default     = 1

  validation {
    condition     = var.rds_eip_bandwidth_size >= 1
    error_message = "rds_eip_bandwidth_size must be at least 1 Mbit/s."
  }
}

variable "rds_password" {
  description = "RDS 管理账号与初始应用账号密码；只允许通过 TF_VAR_rds_password 注入"
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID"
  type        = string
}

variable "cloudflare_pages_project_name" {
  description = "Cloudflare Pages project name"
  type        = string
  default     = "agentarts-personal-assistant"
}

variable "cloudflare_production_branch" {
  description = "Git branch deployed to the production Pages environment"
  type        = string
  default     = "main"
}

variable "agentarts_invocations_url" {
  description = "AgentArts Runtime invocation endpoint used by Pages Functions"
  type        = string
  default     = "https://defaultgw-ha3wenzqga.cn-southwest-2.huaweicloud-agentarts.com/runtimes/personal-assistant/invocations"
}

variable "runtime_prewarm_timeout_ms" {
  description = "Pages Functions prewarm timeout in milliseconds"
  type        = number
  default     = 2500
}

variable "oidc_jwks_url" {
  description = "OIDC JSON Web Key Set URL"
  type        = string
}

variable "oidc_issuer" {
  description = "Expected OIDC token issuer"
  type        = string
}

variable "oidc_audience" {
  description = "Expected OIDC token audience"
  type        = string
}
