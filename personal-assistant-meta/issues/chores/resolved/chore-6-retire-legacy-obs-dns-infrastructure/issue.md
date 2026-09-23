---
status: resolved
---

# Chore 6: 退役 Legacy OBS / DNS Infrastructure

## 变更动机

Production Web Chat 已于 2026-06-18 迁移至 Cloudflare Pages，并通过
Pages Function 将 same-origin `/api/invocations` 请求代理到 AgentArts
Gateway。原有华为云 OBS static website 与
`chat.resource-governance.cloud` CNAME 已不在当前 production request path
中，但仍由 `personal-assistant-infra`、OpenTofu state 和
`.github/workflows/deploy-infra.yml` 持续管理。

继续保留这些 Legacy resources 会产生以下问题：

- 公开可读的 OBS Bucket 扩大无必要的安全暴露面。
- DNS、OBS 和 OpenTofu state 产生持续维护成本，并容易让新成员误判当前
  production topology。
- Service CORS fallback、E2E tests 和部署文档仍包含 OBS / Netlify 历史配置，
  与当前 Cloudflare Pages 架构不一致。
- Infra workflow 在 `main` 变更后自动执行 `tofu apply`，可能长期维持已经没有
  production 用途的资源。

## 当前状态

```mermaid
flowchart LR
    Browser["Browser"] --> Pages["Cloudflare Pages"]
    Pages --> Function["Pages Function<br/>/api/invocations"]
    Function --> Gateway["AgentArts Gateway"]

    LegacyDNS["chat.resource-governance.cloud<br/>Legacy CNAME"] -. "不在 production path" .-> LegacyOBS["personal-assistant-web-chat<br/>Legacy OBS website"]
    Tofu["OpenTofu"] --> LegacyDNS
    Tofu --> LegacyOBS
    State["pa-terraform-state<br/>OBS backend"] --> Tofu
```

## 目标状态

- 删除 `personal-assistant-web-chat` Legacy static website Bucket。
- 删除 `chat.resource-governance.cloud` CNAME。
- 保留 `resource-governance.cloud` DNS Zone 本身，除非实施时确认整个域名及其
  全部 records 均已废弃。
- 清理 OBS / Netlify CORS fallback、过期 E2E assertions 和当前架构文档中的
  非历史性引用。
- 根据近期 HuaweiCloud IaC 需求，明确选择以下之一：
  - 保留精简后的 `personal-assistant-infra` 与 `pa-terraform-state`，用于未来
    RDS、IAM、VPC 或 EIP resources。
  - 完全退役 OpenTofu workflow，并在安全迁移或归档 state 后删除
    `pa-terraform-state`。

## 影响范围

### Infra

- `personal-assistant-infra/obs.tf`
- `personal-assistant-infra/dns.tf`
- `personal-assistant-infra/outputs.tf`
- `personal-assistant-infra/main.tf`
- `personal-assistant-infra/README.md`
- `personal-assistant-infra/AGENTS.md`
- `.github/workflows/deploy-infra.yml`

### Service

- `personal-assistant-service/app/main.py`
- `personal-assistant-service/.agentarts_config.yaml`
- `personal-assistant-service/.env.example`
- 对应 CORS unit tests

### E2E

- 删除或改写仍验证 CDKTF、OBS static website、OBS CORS origin 的 Legacy tests。
- Production deployment tests 应改为验证 Cloudflare Pages URL 与
  same-origin API Proxy。

### Meta

- 更新当前架构和 CI/CD 文档，使 OBS / DNS 只存在于明确标记为 Historical 的
 记录中。
- 保留必要的历史 ADR、resolved issue 和排障记录，不篡改历史决策。

## 实施顺序

```mermaid
flowchart TD
    Audit["审计 DNS Zone records、OBS objects 与访问日志"] --> Decision{"确认 Legacy resources<br/>无有效流量或外部依赖？"}
    Decision -->|"No"| Stop["停止销毁并记录依赖"]
    Decision -->|"Yes"| Backup["备份必要对象与 OpenTofu state"]
    Backup --> Plan["生成并 review tofu plan"]
    Plan --> RemoveRecord["删除 chat CNAME"]
    RemoveRecord --> RemoveBucket["清空并删除 Web Chat OBS Bucket"]
    RemoveBucket --> CleanRefs["清理 Service / E2E / Docs 引用"]
    CleanRefs --> InfraDecision{"近期仍需 HuaweiCloud IaC？"}
    InfraDecision -->|"Yes"| KeepState["保留 Infra workflow 与 state backend"]
    InfraDecision -->|"No"| RetireState["归档 state 后退役 workflow 与 state bucket"]
    KeepState --> Verify["执行 E2E 与 production smoke test"]
    RetireState --> Verify
```

## 任务拆解

- [x] 审计 `resource-governance.cloud` DNS Zone 的全部 records，确认不能删除
  Zone resource。
- [x] 检查 `chat.resource-governance.cloud` 当前解析、访问流量、OAuth Redirect
  URI、CORS allowlist 和外部 bookmark / integration。
- [x] 检查 `personal-assistant-web-chat` Bucket 内容、访问日志、versioning 和
  retention，备份必要对象。
- [x] 获取远程 OpenTofu state 备份，并确认 state 中实际管理的 resources。
- [x] 在修改 Terraform resources 前执行 GitNexus impact analysis。
- [x] 生成销毁 Legacy CNAME 与 Web Chat Bucket 的 `tofu plan`，人工 review
  后方可 apply。
- [x] 从 OpenTofu 管理中安全移除 DNS Zone；不得因删除 Terraform declaration
  而销毁仍在使用的 Zone。
- [x] 删除 OBS / DNS outputs 和无效 variables。
- [x] 清理 Service 中 OBS / Netlify CORS fallback；确认 Cloudflare
  same-origin path 不依赖 FastAPI CORS。
- [x] 更新或删除 Legacy OBS / CDKTF E2E tests。
- [x] 更新 Infra、CI/CD 和 architecture 文档。
- [x] 决定是否保留 OpenTofu：
  - [x] 若保留：将目录说明改为未来 HuaweiCloud resources 的空基线。
  - [ ] 若退役：禁用 Infra workflow，归档 state，再删除
    `pa-terraform-state`。
- [x] 运行 Service unit tests、Client tests、相关 E2E tests 和 Cloudflare
  production smoke test。
- [x] 在 commit 前运行 `gitnexus_detect_changes()`，确认影响范围符合预期。

## 安全约束

- 不得直接执行未 review 的 `tofu destroy`。
- 不得删除整个 `resource-governance.cloud` DNS Zone，除非已审计全部 records
  并得到明确批准。
- 不得先删除 `pa-terraform-state`；必须先备份或迁移 state，并确认不存在仍由
  OpenTofu 管理的有效 resources。
- 删除启用 versioning 的 OBS Bucket 前，必须处理所有 object versions 和
  delete markers。
- 云资源删除属于不可逆 external state change，实施阶段必须单独获得明确批准。

## 验收标准

- Cloudflare Pages 首页、SPA routes 与 `/invocations` smoke test 正常。
- AgentArts Gateway authentication 与 SSE streaming 不受影响。
- `chat.resource-governance.cloud` CNAME 和
  `personal-assistant-web-chat` Bucket 已按批准范围退役。
- `resource-governance.cloud` 的其他 DNS records 不受影响。
- 仓库当前配置与 tests 不再将 OBS / Netlify 视为 production frontend。
- OpenTofu 和 `pa-terraform-state` 的保留或退役决策已记录，且仓库配置与该
  决策一致。

## 关联文档

- `personal-assistant-meta/architecture/ADR/ADR-017-cloudflare-pages-proxy.md`
- `personal-assistant-meta/architecture/external-systems/cloudflare/pages.md`
- `personal-assistant-meta/architecture/external-systems/domain.md`
- `personal-assistant-meta/architecture/devops/cicd.md`
- `personal-assistant-infra/README.md`

## 实施记录（2026-06-19）

### 审计

- DNS Zone `resource-governance.cloud` 状态为 Active，共 3 条 records：SOA、
  NS、`chat.resource-governance.cloud` CNAME。结论：保留 Zone，仅删除 CNAME。
- Legacy CNAME 仍解析到
  `personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com`。
- OBS bucket 当前 14 个 objects、508 个 object versions、74 个 delete
  markers，总 version data 约 55.3 MB；versioning 为 Enabled，未配置 access
  logging。
- Cloudflare Pages `/` 与 `/chat` smoke test 均返回 HTTP 200。
- 远程 state 已备份到本地临时文件，SHA-256：
  `185714510fa9721346f68f86915e95b19cf15a794a6aa8c9df9a65e13a225530`。

### 决策

保留精简后的 `personal-assistant-infra` 与 `pa-terraform-state`，作为未来
RDS、IAM、VPC、EIP resources 的空基线。Infra workflow 改为默认只执行
plan，apply 仅允许通过显式 `workflow_dispatch`。

### 两阶段退役

1. 第一阶段 plan：从 state 解管 DNS Zone（`destroy = false`）、删除 Legacy
   CNAME、将 versioned OBS bucket 设置为 `force_destroy = true`。
2. 人工 review 并批准第一阶段 apply 后，删除 OBS resource declaration，
   生成第二阶段 plan，确认只删除 Legacy bucket 后再单独批准 apply。

### 实施结果

- 第一阶段 apply：0 added、1 changed、1 destroyed、1 forgotten。CNAME 已删除，
  DNS Zone 仅从 state 解管，OBS bucket 已启用 `force_destroy`。
- Provider bulk delete 因 OBS 返回 `MalformedXML` 失败。改用 OBS SDK 按
  `key + versionId` 清理 596 个 versions/delete markers 后，第二阶段 apply
  成功删除 bucket。
- 最终 authoritative DNS 无 `chat` CNAME，DNS Zone 仍 Active 且保留 NS/SOA。
- 最终 OpenTofu state 为空，`tofu plan` 显示 No changes；Legacy bucket
  metadata 返回 HTTP 404。
- 验证结果：Service `171 passed, 9 skipped`；Client `135 passed` 且 build
  成功；相关 E2E `5 passed`；Cloudflare `/` 与 `/chat` 返回 200，未认证
  `/invocations` Proxy probe 返回 401。
- Service 全量 Ruff 仍有 15 个既有 lint 问题，位于本 chore 未修改的
  `app/auth.py`、`app/tools/email_tools.py` 和根目录临时 test scripts。
