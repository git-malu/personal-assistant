# Personal Assistant Infra

OpenTofu + HCL 的华为云基础资源。当前管理 PostgreSQL 17 RDS、独立
Security Group、RDS EIP 与公网绑定。Production Web Chat 由 Cloudflare
Pages 托管，前端请求通过 Pages Function same-origin Proxy 转发到 AgentArts
Gateway；本目录不管理 Cloudflare resources。

Legacy `personal-assistant-web-chat` OBS static website 和
`chat.resource-governance.cloud` CNAME 已退役。注册域名对应的
`resource-governance.cloud` DNS Zone 保留在华为云，不再由 OpenTofu 管理。

## 当前架构

- AgentArts Runtime 使用 PUBLIC Mode，以保留 IAM、LLM 和外部 API Egress。
- AgentArts Calendar OAuth2 return URL allowlist 暂通过 `terraform_data`
  + `local-exec` 调用 infra SDK helper 管理；HuaweiCloud Provider 当前未暴露
  Agent Identity Workload Identity 资源。OpenTofu 拥有该 allowlist 的完整
  desired state，helper 会全量覆盖云端列表。
- RDS 位于现有 VPC/Subnet，但通过独立 EIP 提供 Demo 公网连接。
- RDS Security Group 仅开放 TCP 5432；当前 Demo 来源为 `0.0.0.0/0`。
- 应用 DSN 必须使用 `sslmode=require` 和非管理员账号 `pa_app`。
- `pa-runtime-sg` 仅为迁移期保留，PUBLIC Runtime 验证完成后删除。
- 保留 `pa-terraform-state` OBS backend，供未来 HuaweiCloud IaC 继续使用。
- Pull Request 和 `main` push 只执行 `tofu plan`。
- `tofu apply` 只能通过手动 `workflow_dispatch` 并显式选择 `apply` 执行。

## 前置条件

- OpenTofu CLI ≥ 1.9
- uv（用于执行 `scripts/configure_calendar_oauth_return_url.py`）
- Provider credentials：`HW_ACCESS_KEY` / `HW_SECRET_KEY`
- OBS backend credentials：`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
- 与待管理资源匹配的最小 IAM permissions

## 手动执行 Calendar OAuth helper

`agent_identity.tf` 里的 `terraform_data + local-exec` 使用同一个脚本，
可以手动查看或同步 Agent Identity 的 OAuth2 return URL allowlist。

先进入目录并准备凭据：

```bash
cd personal-assistant-infra

export HW_ACCESS_KEY="<your-access-key>"
export HW_SECRET_KEY="<your-secret-key>"
export AWS_ACCESS_KEY_ID="$HW_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$HW_SECRET_KEY"
```

查看当前 allowlist：

```bash
uv run python scripts/configure_calendar_oauth_return_url.py \
  --list-current \
  --workload-identity-name agent-personal-assistant \
  --region cn-southwest-2
```

同步 allowlist（只有加 `--apply` 才会写入云端）：

```bash
uv run python scripts/configure_calendar_oauth_return_url.py \
  --workload-identity-name agent-personal-assistant \
  --region cn-southwest-2 \
  --return-url "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar" \
  --return-url "http://localhost:5173/auth/callback/m365-calendar" \
  --apply
```

`--return-url` 可以重复传入；如果不传，脚本也会读取
`OAUTH2_CALENDAR_CALLBACK_URL`。

## 手动执行本地 JWT Workload helper

本地 Calendar OAuth2 full flow 在没有 Gateway 注入 WAT 时，需要一个
customer-owned `CUSTOM_JWT` Workload Identity 来主动 mint JWT-mode WAT。
默认名称为 `pa-local-jwt-workload`，对应 Service 默认配置
`AGENT_IDENTITY_LOCAL_JWT_WORKLOAD_NAME=pa-local-jwt-workload`。
本地前端发送 Microsoft Entra ID token 作为 inbound `Authorization` token。
因此该 workload 默认使用 Microsoft Entra v2 discovery URL，校验
`allowed_audience=<VITE_ENTRA_CLIENT_ID>`，并省略 `allowed_clients`。
Microsoft Entra ID token 通常没有 `appid` / `azp` / `client_id` claim，
不要在默认本地配置里要求 client-id claim；显式空数组和省略字段在
Agent Identity 后端行为不同，默认必须省略。

查看当前可见 workload identities：

```bash
uv run python scripts/list_workload_identities.py \
  --region cn-southwest-2
```

验证或创建本地 JWT workload。普通运行只读云端并展示 diff，只有加
`--apply` 才会创建或更新：

```bash
uv run python scripts/ensure_local_jwt_workload_identity.py \
  --region cn-southwest-2

uv run python scripts/ensure_local_jwt_workload_identity.py \
  --region cn-southwest-2 \
  --apply
```

拿到本地前端使用的 Microsoft Entra ID token 后，可以 smoke-test JWT WAT exchange。
脚本从环境变量读取 token，默认不打印 WAT：

```bash
export AGENT_IDENTITY_USER_TOKEN="<Microsoft Entra ID token>"
uv run python scripts/smoke_jwt_workload_access_token.py \
  --workload-identity pa-local-jwt-workload \
  --region cn-southwest-2
unset AGENT_IDENTITY_USER_TOKEN
```

## 本地验证

```bash
cd personal-assistant-infra

export HW_ACCESS_KEY="<your-access-key>"
export HW_SECRET_KEY="<your-secret-key>"
export AWS_ACCESS_KEY_ID="$HW_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$HW_SECRET_KEY"

tofu init
tofu fmt -check -recursive
tofu validate
tofu plan
```

不得对未 review 的 plan 执行 `tofu apply` 或 `tofu destroy`。

## 目录结构

```text
personal-assistant-infra/
├── main.tf                # OpenTofu、Provider 与 OBS backend
├── agent_identity.tf      # Agent Identity OAuth2 return URL allowlist bridge
├── scripts/               # Infra helper scripts
├── vpc.tf                 # Existing VPC/Subnet 与 RDS Security Group
├── rds.tf                 # PostgreSQL 17、应用账号与数据库
├── eip.tf                 # RDS EIP 与 Association
├── outputs.tf             # RDS Private/Public Endpoint metadata
├── pyproject.toml         # Infra helper Python dependencies
├── uv.lock                # Infra helper Python dependency lockfile
├── variables.tf           # 通用变量
├── .terraform.lock.hcl    # Provider 版本锁
├── .gitignore
├── AGENTS.md              # IaC 开发规范
└── README.md              # 本文件
```

Apply 完成后，通过 `tofu output -raw rds_public_ip` 获取公网地址，并更新
GitHub Secret `POSTGRES_DSN`。Password 中的 `@` 必须编码为 `%40`：

```text
postgresql://pa_app:<url-encoded-password>@<rds_public_ip>:5432/personal_assistant?sslmode=require
```

完整 DSN 和 password 不得提交到 Git。

Rollout 必须按以下顺序执行，避免 PUBLIC Runtime 在 EIP 尚未就绪时启动失败：

1. 先执行 Infra Apply，创建并绑定 RDS EIP；
2. 使用 `rds_public_ip` 更新 GitHub Secret `POSTGRES_DSN`；
3. 再部署 Service，将 Runtime 切换为 PUBLIC；
4. 验证完成后删除迁移期 `pa-runtime-sg`。

## Legacy retirement 记录

2026-06-19：Production Web Chat 已由 Cloudflare Pages 承载。审计确认 DNS
Zone 仅包含 SOA、NS 和待删除的 `chat` CNAME；OBS bucket 启用 versioning，
包含 508 个 object versions 和 74 个 delete markers。退役过程中保留 DNS
Zone 与 `pa-terraform-state`，删除 CNAME 和 Legacy website bucket。

## 相关文档

- [ADR-006 IaC 选型](../personal-assistant-meta/architecture/ADR/ADR-006-iac-cdktf-typescript.md)
- [Cloudflare Pages](../personal-assistant-meta/architecture/cloud-service/cloudflare/pages.md)
- [CI/CD 架构](../personal-assistant-meta/architecture/devops/cicd.md)
- [Legacy domain 记录](../personal-assistant-meta/architecture/cloud-service/huaweicloud/domain.md)
