# ============================================================
# Personal Assistant — HuaweiCloud + Cloudflare 基础资源
# ============================================================
# IaC 工具：OpenTofu（Linux 基金会托管，MPL 协议）
# 详见 ADR-006: personal-assistant-meta/architecture/ADR/ADR-006-iac-cdktf-typescript.md

terraform {
  required_version = ">= 1.9"

  required_providers {
    huaweicloud = {
      source  = "huaweicloud/huaweicloud"
      version = "~> 1.92"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket                      = "pa-terraform-state"
    key                         = "prod/terraform.tfstate"
    region                      = "cn-southwest-2"
    endpoint                    = "https://obs.cn-southwest-2.myhuaweicloud.com"
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
  }
}

provider "huaweicloud" {
  region = var.region
}

# Authentication uses CLOUDFLARE_API_TOKEN. The token must have the minimum
# account permissions required for Pages and Hyperdrive.
provider "cloudflare" {}
