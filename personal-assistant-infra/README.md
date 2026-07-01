# Personal Assistant Infra

OpenTofu + HCL 的 HuaweiCloud 与 Cloudflare 长期基础设施。当前管理
PostgreSQL 17 RDS、Security Group、RDS EIP、Cloudflare Hyperdrive、
Pages Project、Pages Functions bindings 与生产环境变量。前端与 Functions
代码仍由 Wrangler workflow 发布。

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
- Hyperdrive 使用同一应用账号并强制 TLS；query caching 默认关闭，保证
  Conversation 写入后的读取一致性。
- Pages Functions 的 `HYPERDRIVE` binding 与 OIDC 配置由 OpenTofu 管理。
- `pa-runtime-sg` 仅为迁移期保留，PUBLIC Runtime 验证完成后删除。
- 保留 `pa-terraform-state` OBS backend，供未来 HuaweiCloud IaC 继续使用。
- Pull Request 和 `main` push 只执行 `tofu plan`。
- `tofu apply` 只能通过手动 `workflow_dispatch` 并显式选择 `apply` 执行。

## 前置条件

- OpenTofu CLI ≥ 1.9
- uv（用于执行 `scripts/configure_calendar_oauth_return_url.py`）
- Provider credentials：`HW_ACCESS_KEY` / `HW_SECRET_KEY`
- Cloudflare Provider credential：`CLOUDFLARE_API_TOKEN`
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

## 本地验证

```bash
cd personal-assistant-infra

export HW_ACCESS_KEY="<your-access-key>"
export HW_SECRET_KEY="<your-secret-key>"
export AWS_ACCESS_KEY_ID="$HW_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$HW_SECRET_KEY"
export CLOUDFLARE_API_TOKEN="<least-privilege-api-token>"
export TF_VAR_cloudflare_account_id="<account-id>"
export TF_VAR_rds_password="<database-password>"
export TF_VAR_oidc_jwks_url="<jwks-url>"
export TF_VAR_oidc_issuer="<issuer>"
export TF_VAR_oidc_audience="<audience>"

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
├── cloudflare.tf          # Hyperdrive、Pages Project 与 Functions bindings
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

## 接管现有 Pages Project

`agentarts-personal-assistant` 已存在，第一次 OpenTofu apply 前必须先导入
现有资源，避免创建冲突：

```bash
tofu import \
  cloudflare_pages_project.personal_assistant \
  "<cloudflare_account_id>/agentarts-personal-assistant"
```

导入后先执行 `tofu plan`，重点 review `deployment_configs`。Pages Project
配置了 `prevent_destroy`，不得为解决 drift 而删除重建。Hyperdrive 尚不存在时
由 OpenTofu 创建；若已手工创建，则使用
`<cloudflare_account_id>/<hyperdrive_id>` 导入。

OIDC issuer、audience、JWKS URL 不是 credential，可通过 GitHub Variables
注入。RDS password 与 Cloudflare API token 必须来自 GitHub Secrets。注意：
OpenTofu 的 `sensitive` 只隐藏 CLI 输出，RDS password 仍会进入加密的 OBS
remote state，因此必须严格限制 state bucket 访问。

Rollout 必须按以下顺序执行，避免 PUBLIC Runtime 在 EIP 尚未就绪时启动失败：

1. 导入现有 Pages Project，并 review OpenTofu plan；
2. Infra Apply 创建 RDS EIP、Hyperdrive 与 Pages Functions binding；
3. 使用 `rds_public_ip` 更新 GitHub Secret `POSTGRES_DSN`；
4. Service workflow 执行 `alembic upgrade head` 后部署 Runtime；
5. Wrangler 发布前端与 Pages Functions 代码；
6. 验证完成后删除迁移期 `pa-runtime-sg`。

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
