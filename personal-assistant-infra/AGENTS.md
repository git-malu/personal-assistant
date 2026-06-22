# AGENTS.md

> 本文件仅适用于 `personal-assistant-infra/`。

## 定位

本目录管理 HuaweiCloud 与 Cloudflare 的长期基础设施配置。Production Web
Chat 的 Pages Project、Hyperdrive、Pages Functions bindings 和环境变量属于
本目录；前端与 Functions 代码发布仍由 Wrangler workflow 管理。AgentArts
Runtime 由 `personal-assistant-service/.agentarts_config.yaml` 管理。

近期可能纳入本目录的资源包括 RDS、IAM、VPC 和 EIP。Legacy Web Chat OBS
bucket、`chat.resource-governance.cloud` CNAME 与 DNS Zone 不属于目标基线。

## 技术栈

| 项 | 选择 |
|----|------|
| IaC | OpenTofu + HCL |
| Provider | `huaweicloud/huaweicloud`、`cloudflare/cloudflare` |
| State | OBS S3-compatible backend `pa-terraform-state` |
| 验证 | `tofu fmt -check`、`tofu validate`、`tofu plan` |

## 目录约定

```text
personal-assistant-infra/
├── main.tf
├── cloudflare.tf
├── variables.tf
├── .terraform.lock.hcl
├── .gitignore
├── AGENTS.md
└── README.md
```

- `main.tf` 只放 OpenTofu、Provider 和 backend 配置。
- 新资源按类型拆分到 `rds.tf`、`iam.tf`、`vpc.tf`、`cloudflare.tf` 等文件。
- Resource name 使用清晰的 snake_case；云端资源名称使用 `pa-` 前缀和
  kebab-case。
- 敏感信息不得硬编码。Provider 使用 `HW_ACCESS_KEY` /
  `HW_SECRET_KEY`；backend 使用 `AWS_ACCESS_KEY_ID` /
  `AWS_SECRET_ACCESS_KEY`；Cloudflare Provider 使用
  `CLOUDFLARE_API_TOKEN`。
- 重要属性通过 `outputs.tf` 导出；没有 output 时不保留空文件。

## 变更流程

```mermaid
flowchart LR
    Edit["修改 HCL"] --> Format["tofu fmt -check"]
    Format --> Validate["tofu validate"]
    Validate --> Plan["tofu plan"]
    Plan --> Review["人工 review"]
    Review --> Dispatch["workflow_dispatch: apply"]
```

Pull Request 和 `main` push 均不得自动 apply。外部资源销毁必须先完成审计、
state 备份和 plan review，并单独获得明确批准。

## 常用命令

```bash
cd personal-assistant-infra
tofu init
tofu fmt -check -recursive
tofu validate
tofu plan
```

禁止对未 review 的配置运行 `tofu destroy`。
