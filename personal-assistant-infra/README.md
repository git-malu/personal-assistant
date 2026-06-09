# Personal Assistant Infra

OpenTofu + HCL 管理华为云基础资源。Provider 为 `huaweicloud/huaweicloud`（`~> 1.92`）。

## 管理的资源

| Resource | Type | Name | Region | Config |
|----------|------|------|--------|--------|
| OBS Bucket | `huaweicloud_obs_bucket` | `personal-assistant-web-chat` | `cn-southwest-2` | ACL=public-read, versioning=true, static website hosting (SPA: error_document=index.html) |

> 更多资源（RDS、IAM、VPC、EIP、CDN）将随项目增长逐步添加。

## 前置条件

- **OpenTofu CLI** ≥ 1.6（Linux 基金会托管，MPL 协议）：`brew install opentofu`
- **华为云凭据**：AK/SK（通过 `terraform.tfvars` 或环境变量 `TF_VAR_ak` / `TF_VAR_sk` 注入）
- **IAM 权限**：OBS FullAccess（当前必需）

## 快速开始

```bash
cd personal-assistant-infra

# 初始化（首次或 provider 版本变更时）
tofu init

# 语法验证
tofu validate

# 格式检查与自动修复
tofu fmt -check
tofu fmt

# 预览变更计划（需要华为云凭据）
tofu plan
```

## 部署

```bash
# 1. 配置华为云凭据（二选一）
# 方式 A：通过 terraform.tfvars（推荐）
cat > terraform.tfvars <<EOF
ak = "your-ak"
sk = "your-sk"
EOF

# 方式 B：通过环境变量
export TF_VAR_ak="<your-ak>"
export TF_VAR_sk="<your-sk>"

# 2. 执行部署
tofu apply
```

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
```

## 目录结构

```
personal-assistant-infra/
├── main.tf                # Terraform/Provider 配置 + Backend
├── obs.tf                 # OBS Bucket 资源（web chat 静态托管）
├── variables.tf           # 变量声明（ak, sk, region）
├── outputs.tf             # Stack outputs（website_endpoint 等）
├── terraform.tfvars       # 变量赋值（gitignored，含敏感信息）
├── .terraform.lock.hcl    # Provider 版本锁（git tracked）
├── .terraform/            # Provider 缓存（gitignored）
├── .gitignore
├── AGENTS.md              # IaC 开发规范
└── README.md              # 本文件
```

## 迁移记录

2026-06-09：从 CDKTF (TypeScript) 迁移到 OpenTofu + HCL。动机：CDKTF 被 HashiCorp 归档（2025-12-10），社区 fork CDK Terrain 存活风险过高。详见 [Refactor 6](../personal-assistant-meta/issues/refactor/refactor-6-migrate-cdktf-to-opentofu-hcl/issue.md)。

## 相关文档

| 文档 | 说明 |
|------|------|
| [ADR-006 IaC 选型](../personal-assistant-meta/architecture/ADR/ADR-006-iac-cdktf-typescript.md) | OpenTofu + HCL 技术决策 |
| [CI/CD 架构](../personal-assistant-meta/architecture/devops/cicd.md) | 分层部署策略与 IaC 触发时机 |
| [Overall Architecture](../personal-assistant-meta/architecture/overall_architecture.md) | 系统整体架构 |
| [Infra AGENTS.md](./AGENTS.md) | IaC 开发约定与规范 |
