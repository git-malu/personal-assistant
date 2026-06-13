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

variable "agentarts_delegated_domain_name" {
  description = "AgentArts STS Agency 委托的华为云账号/domain 名称"
  type        = string
}

variable "obs_sts_agency_name" {
  description = "AgentArts Identity STS Provider 使用的 IAM Agency 名称"
  type        = string
  default     = "pa-agentarts-obs-sts"
}

variable "obs_sts_policy_name" {
  description = "OBS 只读自定义策略名称"
  type        = string
  default     = "pa-obs-sts-read-only"
}
