# AGENTS.md

> 本文件是 **personal-assistant-infra** 目录的专用 instructions，仅适用于该目录下的相关工作。

## Directory Guide

`personal-assistant-infra/` 是系统的**基础设施即代码（IaC）**目录，管理 `agentarts_config.yaml` 管不到的华为云基础资源。技术选型见 [ADR-006](../personal-assistant-meta/architecture/ADR/ADR-006-iac-cdktf-typescript.md)。

开始前先阅读项目根目录的 [`AGENTS.md`](../AGENTS.md) 了解整体项目结构和规范。

### 设计文档

所有架构设计、ADR 和变更规划在 `personal-assistant-meta/` 中：

| 文档 | 内容 |
|------|------|
| `architecture/devops/cicd.md` | CI/CD 流水线、分层部署策略、IaC 触发时机 |
| `architecture/ADR/ADR-006-iac-cdktf-typescript.md` | OpenTofu + HCL 选型理由、技术对比、迁移记录 |
| `issues/refactor/refactor-6-migrate-cdktf-to-opentofu-hcl/issue.md` | CDKTF → OpenTofu + HCL 迁移任务 |

### 与 `agentarts_config.yaml` 的关系

两者互不冲突，管不同层的资源：

```
personal-assistant-service/.agentarts_config.yaml  → AgentArts 层（容器/认证/可观测）
personal-assistant-infra/*.tf                       → 华为云基础资源层（OBS/RDS/IAM/VPC/EIP/CDN）
```

## 技术栈

| 项 | 选择 | 依据 |
|----|------|------|
| **IaC 工具** | OpenTofu + HCL | ADR-006（修订 2026-06-09），Linux 基金会托管，100% Terraform 兼容 |
| **语言** | HCL（HashiCorp Configuration Language） | IaC 行业标准，1-2 天上手 |
| **Provider** | `huaweicloud/huaweicloud` | HuaweiCloud Terraform Provider |
| **状态管理** | OBS S3-compatible backend（`pa-terraform-state`） | 本地 state 仅用于一次性 bootstrap；CI 和本地共享远程 state |
| **验证** | `tofu validate` + `tofu plan` | CLI 内置 |

## 目录结构

```
personal-assistant-infra/
├── main.tf                # Terraform/Provider 配置 + OBS Backend
├── obs.tf                 # OBS Bucket 资源（web chat 静态托管）
├── dns.tf                 # DNS Zone + CNAME 记录
├── variables.tf           # 变量声明（region, dns_zone_id）
├── outputs.tf             # Stack outputs（website_endpoint 等）
├── .terraform.lock.hcl    # Provider 版本锁（git tracked）
├── .terraform/            # Provider 缓存（gitignored）
├── .gitignore
├── AGENTS.md              # 本文件
└── README.md              # 快速开始与运维手册
```

## 触发时机

以下场景出现任意一个，就需要在 `personal-assistant-infra/` 中编写 HCL：

| 场景 | 需要的资源 |
|------|-----------|
| Web Chat 前端需要静态托管 | OBS Bucket ✅（已实现） |
| 用户-渠道 ID 映射需要持久化存储 | RDS（PostgreSQL） |
| OfficeClaw 需要固定公网入口 | EIP + 带宽配置 |
| Identity STS Provider 需要授权 | IAM Agency / Role / Policy |
| Web Chat 需要 HTTPS | SSL 证书 + WAF / ELB |

## 常用命令

```bash
# 安装 OpenTofu（macOS）
brew install opentofu

# 初始化（首次或 provider 版本变更时）
cd personal-assistant-infra
tofu init

# 语法验证
tofu validate

# 格式检查
tofu fmt -check

# 自动格式化
tofu fmt

# 查看变更计划（需要 HuaweiCloud 凭据）
tofu plan

# 执行部署（需要 HuaweiCloud 凭据）
tofu apply

# 导入已有资源（从 CDKTF 迁移时）
tofu import huaweicloud_obs_bucket.web_chat personal-assistant-web-chat
```

## 开发约定

- **文件拆分**：按资源类型拆分 `.tf` 文件（`main.tf`, `obs.tf`, `rds.tf` 等），`main.tf` 只放 provider 和 backend 配置
- **Resource 命名**：使用 kebab-case，带 `pa-` 前缀避免与平台资源冲突
- **敏感信息**：禁止硬编码。HuaweiCloud Provider 凭据通过原生环境变量 `HW_ACCESS_KEY` / `HW_SECRET_KEY` 注入，无需在 `variables.tf` 中声明。其他敏感变量可通过 `terraform.tfvars` 赋值（gitignored）或环境变量 `TF_VAR_*` 注入
- **状态管理**：Terraform state 当前为本地存储。OBS backend（`pa-terraform-state` bucket）为最终目标，需在首次部署后迁移（chicken-and-egg 问题）
- **Outputs**：重要的资源属性通过 `outputs.tf` 导出，供 Service 配置读取（如 RDS endpoint、OBS bucket name）
- **变更流程**：修改 `.tf` → `tofu validate`（语法验证）→ `tofu plan`（查看变更）→ PR Review → `tofu apply`

## 当前管理的资源

| Resource | Terraform 类型 | Name | Region | 配置 |
|----------|---------------|------|--------|------|
| OBS Bucket | `huaweicloud_obs_bucket` | `personal-assistant-web-chat` | `cn-southwest-2` | ACL=public-read, versioning=true, static website hosting (SPA: error_document=index.html) |

## 迁移记录

2026-06-09：从 CDKTF (TypeScript) 迁移到 OpenTofu + HCL。动机：CDKTF 被 HashiCorp 归档（2025-12-10），社区 fork CDK Terrain 存活风险过高。详见 [Refactor 6](../personal-assistant-meta/issues/refactor/refactor-6-migrate-cdktf-to-opentofu-hcl/issue.md)。
