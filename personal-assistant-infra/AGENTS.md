# personal-assistant-infra

> 本文件是 `personal-assistant-infra/` 目录的专用 instructions，仅适用于该目录下的相关工作。开始前先阅读项目根目录的 [`AGENTS.md`](../AGENTS.md)。

## Directory Guide

`personal-assistant-infra/` 管理 HuaweiCloud 与 Cloudflare 的长期基础设施配置。当前管理 PostgreSQL 17 RDS、独立 Security Group、RDS EIP 与公网绑定、Production Web Chat 的 Pages Project/Hyperdrive/Pages Functions bindings，并通过 helper script 管理 Agent Identity Calendar OAuth2 return URL allowlist。

Production Web Chat 由 Cloudflare Pages 管理，AgentArts Runtime 由 `personal-assistant-service/.agentarts_config.yaml` 管理；两者均不属于本目录。Legacy OBS static website、`chat.resource-governance.cloud` CNAME 与 DNS Zone 不属于目标基线。

## Tech Stack

| 项 | 选择 |
|----|------|
| IaC | OpenTofu + HCL |
| Provider | `huaweicloud/huaweicloud` |
| State | OBS S3-compatible backend `pa-terraform-state` |
| Helper runtime | Python 3.12 + uv |
| Helper SDK | `huaweicloudsdkagentidentity` |
| 验证 | `tofu fmt -check -recursive`, `tofu validate`, `tofu plan` |

## Directory Structure

```text
personal-assistant-infra/
├── main.tf                # OpenTofu、Provider 与 OBS backend
├── variables.tf           # 通用变量
├── vpc.tf                 # Existing VPC/Subnet 与 RDS Security Group
├── rds.tf                 # PostgreSQL 17、应用账号与数据库
├── eip.tf                 # RDS EIP 与 association
├── agent_identity.tf      # OAuth2 return URL allowlist bridge
├── outputs.tf             # RDS endpoint metadata
├── scripts/               # Infra helper scripts
├── pyproject.toml         # Helper dependencies
├── uv.lock
├── .terraform.lock.hcl
├── README.md
└── AGENTS.md
```

## Build and Test Commands

```bash
cd personal-assistant-infra
uv sync
tofu init
tofu fmt -check -recursive
tofu validate
tofu plan
```

Calendar OAuth helper:

```bash
uv run python scripts/configure_calendar_oauth_return_url.py --list-current \
  --workload-identity-name agent-personal-assistant \
  --region cn-southwest-2
```

## Code Style Guidelines

- 使用 `tofu fmt` 保持 HCL 格式一致。
- Resource name 使用清晰的 snake_case；云端资源名称使用 `pa-` 前缀和 kebab-case。
- 敏感信息不得硬编码。Provider 使用 `HW_ACCESS_KEY` / `HW_SECRET_KEY`；OBS backend 使用 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`。
- 重要属性通过 `outputs.tf` 导出；没有 output 时不保留空文件。
- 新资源按类型拆分到对应文件，如 `rds.tf`、`iam.tf`、`vpc.tf`。不要把业务 runtime 配置混入 Infra。
- Demo 期公网访问和宽松 CIDR 必须在文档或变量说明中标注风险与退出条件。

## Change Flow

```mermaid
flowchart LR
    Edit["修改 HCL 或 helper"] --> Format["tofu fmt -check"]
    Format --> Validate["tofu validate"]
    Validate --> Plan["tofu plan"]
    Plan --> Review["人工 review"]
    Review --> Dispatch["workflow_dispatch: apply"]
```

Pull Request 和 `main` push 均不得自动 apply。`tofu apply` 只能通过手动 `workflow_dispatch` 并显式选择 `apply` 执行。外部资源销毁必须先完成审计、state 备份和 plan review，并单独获得明确批准。

## Testing Instructions

- 修改 HCL 后运行 `tofu fmt -check -recursive`、`tofu validate` 和 `tofu plan`。
- 修改 Python helper 后运行 `uv run ruff check .`（如未来在 pyproject 中加入 Ruff 配置，也运行 `uv run ruff format --check .`）。
- Calendar OAuth allowlist helper 只有传入 `--apply` 才会写云端；普通查看使用 `--list-current`。
- 不得对未 review 的配置运行 `tofu apply` 或 `tofu destroy`。

## Rollout Notes

RDS 相关 rollout 必须先执行 Infra apply，获取 `rds_public_ip` 后更新 GitHub Secret `POSTGRES_DSN`，再部署 Service。DSN 必须使用非管理员账号 `pa_app` 和 `sslmode=require`，password 中的 `@` 需编码为 `%40`。
