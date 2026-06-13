# Personal Assistant Infra

OpenTofu + HCL 管理华为云基础资源。Provider 为 `huaweicloud/huaweicloud`（`~> 1.92`）。State 通过 OBS S3-compatible backend 持久化存储（`pa-terraform-state` bucket）。

## 管理的资源

| Resource | Type | Name | Region | Config |
|----------|------|------|--------|--------|
| OBS Bucket | `huaweicloud_obs_bucket` | `personal-assistant-web-chat` | `cn-southwest-2` | ACL=public-read, versioning=true, static website hosting (SPA: error_document=index.html) |
| DNS Zone | `huaweicloud_dns_zone` | `resource-governance.cloud` | — | 华为云购买域名时自动创建，由 tofu 管理 |
| DNS Recordset | `huaweicloud_dns_recordset` | `chat.resource-governance.cloud` | — | CNAME → OBS website endpoint |
| IAM Custom Policy | `huaweicloud_identity_role` | `pa-obs-sts-read-only` | global | OBS object list/read only |
| IAM Agency | `huaweicloud_identity_agency` | `pa-agentarts-obs-sts` | global | AgentArts Identity STS Provider 委托访问 OBS |
| OBS State Bucket | — | `pa-terraform-state` | `cn-southwest-2` | 由 CI `aws s3 mb` 创建，不归 tofu 管理 |

> 更多资源（RDS、IAM、VPC、EIP、CDN）将随项目增长逐步添加。

## 前置条件

- **OpenTofu CLI** ≥ 1.6（Linux 基金会托管，MPL 协议）：`brew install opentofu`
- **华为云凭据**：AK/SK（通过 Provider 原生环境变量 `HW_ACCESS_KEY` / `HW_SECRET_KEY` 注入）
- **OBS Backend 凭据**：同上 AK/SK，额外设置 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`（OBS 兼容 S3 API，需要 AWS SDK 格式的凭据变量）
- **IAM 权限**：OBS FullAccess + DNS FullAccess + IAM FullAccess（当前必需）

## 快速开始

```bash
cd personal-assistant-infra

# 配置凭据（Provider + OBS Backend 共用同一套 AK/SK）
export HW_ACCESS_KEY="<your-access-key>"
export HW_SECRET_KEY="<your-secret-key>"
export AWS_ACCESS_KEY_ID="$HW_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$HW_SECRET_KEY"

# 初始化（首次或 provider 版本变更时；从 OBS 拉取 state）
tofu init

# 语法验证
tofu validate

# 格式检查与自动修复
tofu fmt -check
tofu fmt

# 预览变更计划（需要华为云凭据）
tofu plan -var 'agentarts_delegated_domain_name=<agentarts-domain-name>'
```

## 部署

```bash
# 1. 配置凭据
export HW_ACCESS_KEY="<your-access-key>"
export HW_SECRET_KEY="<your-secret-key>"
export AWS_ACCESS_KEY_ID="$HW_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$HW_SECRET_KEY"

# 2. 执行部署
tofu apply -var 'agentarts_delegated_domain_name=<agentarts-domain-name>'
```

> ⚠️ 如果你本地存在旧的 `terraform.tfvars` 文件且其中包含 `ak`/`sk` 变量赋值，请手动删除这些项——`ak`/`sk` 变量已不再声明，否则 `tofu plan` 会产生 "Undeclared variables" 警告。
>
> **State 存储**：tfstate 保存在 OBS bucket `pa-terraform-state`（S3-compatible backend），不再使用本地文件。CI 和本地共享同一份 state，无需每次 import 已有资源。

## AgentArts STS Provider

OpenTofu 管理 IAM Agency 和 OBS read-only custom policy。AgentArts Credential Provider 属于 AgentArts 控制面，部署 IAM 后用 service 侧 bootstrap script 创建：

```bash
cd ../personal-assistant-service

export HUAWEICLOUD_SDK_AK="$HW_ACCESS_KEY"
export HUAWEICLOUD_SDK_SK="$HW_SECRET_KEY"
export AGENTARTS_STS_AGENCY_URN="<agency-urn-from-huawei-cloud>"

uv run python scripts/create_sts_provider.py
```

脚本默认创建 `huaweicloud-sts-provider`，Agent 工具通过该 provider 获取 STS 临时凭据访问 OBS。

## 销毁

```bash
# ⚠️ 删除 OBS bucket 及所有内容。生产环境慎用。
tofu destroy
```

## 部署后验证

```bash
# 静态网站主页可访问
curl -sI https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com/index.html
# Expected: HTTP 200

# SPA 路由回退（关键测试）
curl -sI https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com/chat
# Expected: HTTP 200（非 404）

# 自定义域名 CNAME 解析
curl -sI https://chat.resource-governance.cloud/
# Expected: HTTP 200
```

## 目录结构

```
personal-assistant-infra/
├── main.tf                # Terraform/Provider 配置 + OBS Backend
├── obs.tf                 # OBS Bucket 资源（web chat 静态托管）
├── dns.tf                 # DNS Zone + CNAME 记录
├── iam.tf                 # AgentArts Identity STS → OBS read-only Agency/Policy
├── variables.tf           # 变量声明（region, dns_zone_id）
├── outputs.tf             # Stack outputs（website_endpoint 等）
├── .terraform.lock.hcl    # Provider 版本锁（git tracked）
├── .terraform/            # Provider 缓存（gitignored）
├── .gitignore
├── AGENTS.md              # IaC 开发规范
└── README.md              # 本文件
```

## 迁移记录

2026-06-10：State 从本地迁移到 OBS S3-compatible backend（`pa-terraform-state`）。消除 CI ephemeral state 导致的重复 import 问题。

2026-06-10：华为云凭据从 `TF_VAR_ak`/`TF_VAR_sk` 切换为 Provider 原生 `HW_ACCESS_KEY`/`HW_SECRET_KEY`。

2026-06-09：从 CDKTF (TypeScript) 迁移到 OpenTofu + HCL。动机：CDKTF 被 HashiCorp 归档（2025-12-10），社区 fork CDK Terrain 存活风险过高。详见 [Refactor 6](../personal-assistant-meta/issues/refactor/resolved/refactor-6-migrate-cdktf-to-opentofu-hcl/issue.md)。

## 相关文档

| 文档 | 说明 |
|------|------|
| [ADR-006 IaC 选型](../personal-assistant-meta/architecture/ADR/ADR-006-iac-cdktf-typescript.md) | OpenTofu + HCL 技术决策 |
| [CI/CD 架构](../personal-assistant-meta/architecture/devops/cicd.md) | 分层部署策略与 IaC 触发时机 |
| [Overall Architecture](../personal-assistant-meta/architecture/overall_architecture.md) | 系统整体架构 |
| [Infra AGENTS.md](./AGENTS.md) | IaC 开发约定与规范 |
