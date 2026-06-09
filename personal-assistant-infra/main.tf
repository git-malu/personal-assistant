# ============================================================
# Personal Assistant — 华为云基础资源
# ============================================================
# IaC 工具：OpenTofu（Linux 基金会托管，MPL 协议）
# 详见 ADR-006: personal-assistant-meta/architecture/ADR/ADR-006-iac-cdktf-typescript.md

terraform {
  required_providers {
    huaweicloud = {
      source  = "huaweicloud/huaweicloud"
      version = "~> 1.92"
    }
  }

  # State 当前为本地存储。
  # OBS backend（pa-terraform-state bucket）为长期目标，需在首次部署后迁移（chicken-and-egg 问题）。
  # backend "s3" {
  #   bucket = "pa-terraform-state"
  #   key    = "prod/terraform.tfstate"
  #   region = "cn-southwest-2"
  # }
}

provider "huaweicloud" {
  region     = var.region
  access_key = var.ak
  secret_key = var.sk
}
