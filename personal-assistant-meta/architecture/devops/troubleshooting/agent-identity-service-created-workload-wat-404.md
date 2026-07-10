# Agent Identity service-created Workload Identity WAT 404

> 记录时间：2026-07-06  
> 区域：`cn-southwest-2`  
> 结论：`agent-personal-assistant` 是 AgentArts/AgentNetwork 创建的
> service-owned Workload Identity。它可以通过 Agent Identity list/get API
> 看见，但不能通过 SDK/API 主动创建 Workload Access Token (WAT)。

## 症状

本地 Calendar OAuth2 full flow 需要在没有 Gateway 注入 WAT 的情况下主动调用：

```python
IdentityClient(region="cn-southwest-2").create_workload_access_token(
    "agent-personal-assistant",
    user_token="<Microsoft Entra ID id_token>",
)
```

实际返回：

```text
ClientRequestException
status_code: 404
error_code: AgentIdentityDirectoryService.1002
error_msg: workload identity not found
url: https://agent-identity.cn-southwest-2.myhuaweicloud.com/v1/workload-access-token-for-jwt
```

同一个 workload name 在 no-user-token / user_id WAT 路径也返回相同 404：

```python
client.create_workload_access_token("agent-personal-assistant")
client.create_workload_access_token(
    "agent-personal-assistant",
    user_id="<oid-or-sub>",
)
```

## 已确认事实

`agent-personal-assistant` 在 Agent Identity 中真实存在：

```text
name: agent-personal-assistant
urn: agentIdentity:cn-southwest-2:a356e1fddc444dcc95f754bc5d7b9894:workloadIdentity:workloadIdentityDirectory/default/agent-personal-assistant
authorizer_type: CUSTOM_JWT
created_by: SERVICE service.AgentNetwork
```

JWT authorizer configuration 与 Microsoft Entra ID token 匹配：

```text
discovery_url: https://login.microsoftonline.com/2a1d3739-88c5-4314-b921-acbeac0abbfa/v2.0/.well-known/openid-configuration
allowed_audience:
  - 3a99a511-926c-475c-b6bc-325a037f574d
```

失败请求使用的 id_token claims 已验证：

```text
aud: 3a99a511-926c-475c-b6bc-325a037f574d
iss: https://login.microsoftonline.com/2a1d3739-88c5-4314-b921-acbeac0abbfa/v2.0
tid: 2a1d3739-88c5-4314-b921-acbeac0abbfa
ver: 2.0
```

Microsoft Discovery Document 与 JWKS 也匹配：

```text
issuer: https://login.microsoftonline.com/2a1d3739-88c5-4314-b921-acbeac0abbfa/v2.0
jwks_uri: https://login.microsoftonline.com/2a1d3739-88c5-4314-b921-acbeac0abbfa/discovery/v2.0/keys
token kid: present in JWKS
```

## 对照实验

同一套 AK/SK、同一区域、同一个 SDK，对其他可见的 customer-owned
`workload-*` identities 调用 basic WAT 成功：

```text
workload-5542e804  authorizer_type=NONE  created_by=CUSTOMER  basic WAT success
workload-6fc93beb  authorizer_type=NONE  created_by=CUSTOMER  basic WAT success
...
```

对 `authorizer_type=NONE` 的 workload 调用 JWT WAT 时返回预期错误：

```text
status_code: 400
error_code: AgentIdentityDirectoryService.2001
error_msg: authorizer type mismatch
```

这说明：

- credentials、region、endpoint、SDK wrapper 均可正常工作；
- WAT exchange API 可以解析并找到 customer-owned workload identity；
- 404 不是因为 `agent-personal-assistant` 拼错、AK/SK 不可见或 region 错误；
- 问题集中在 `created_by=SERVICE service.AgentNetwork` 的 workload identity 上。

## 不成立的修复方向

不要尝试把 workload name 改成完整 URN。JWT WAT endpoint 的
`workload_name` 参数只接受短名称：

```text
^[a-zA-Z0-9_-]{1,56}$
```

完整 URN 会在 request validation 阶段被拒绝：

```text
status_code: 400
error_code: SYS.0400
error_msg: attribute 'workload_name' size must be between 1 and 56
```

`default/agent-personal-assistant` 也不合法，因为 `/` 不符合
`workload_name` 正则。

## 当前判断

`agent-personal-assistant` 是 service-created / AgentNetwork-owned workload
identity。它对 list/get 与 Console 可见，但不适合作为本地代码主动调用
`create_workload_access_token()` 的目标。

平台表现像是 WAT exchange 后端只解析 customer-owned workload identity，或不会把
`SERVICE service.AgentNetwork` 创建的 identity 纳入主动 mint WAT 的 lookup 范围。
错误码仍然是 `AgentIdentityDirectoryService.1002 workload identity not found`，
因此排查时不能把该错误直接理解为 list/get 层面的资源不存在。

## 推荐处理

为本地 Calendar OAuth2 / SDK 主动 WAT exchange 创建一个 customer-owned
Workload Identity。它使用与 `agent-personal-assistant` 同类的 Microsoft Entra
v2 ID token authorizer；关键差异是它必须是 customer-owned workload，不能是
AgentArts / AgentNetwork service-created workload：

```text
discovery_url: https://login.microsoftonline.com/2a1d3739-88c5-4314-b921-acbeac0abbfa/v2.0/.well-known/openid-configuration
allowed_audience:
  - 3a99a511-926c-475c-b6bc-325a037f574d
# allowed_clients omitted
# allowed_scopes omitted
# custom_claims omitted
```

然后将 Service 本地配置指向该 customer-owned workload：

```env
AGENT_IDENTITY_LOCAL_JWT_WORKLOAD_NAME=pa-local-jwt-workload
```

生产 Gateway 路径仍优先使用 Gateway 注入的
`X-HW-AgentGateway-Workload-Access-Token`。本文结论只约束本地开发或非 Gateway
路径中由代码主动调用 `create_workload_access_token()` 的场景。

Infra helper 默认使用 `pa-local-jwt-workload`，并配置本地 inbound Microsoft
Entra ID token 的验证规则：v2 discovery URL、前端应用 client ID 作为
`allowed_audience`，并省略 `allowed_clients`。普通运行是 dry-run，
只有 `--apply` 会写云端：

```bash
cd personal-assistant-infra
uv run python scripts/ensure_local_jwt_workload_identity.py
uv run python scripts/ensure_local_jwt_workload_identity.py --apply
```

## 复现命令

列出当前可见 workload identities：

```bash
cd personal-assistant-infra
uv run python scripts/list_workload_identities.py \
  --region cn-southwest-2
```

测试 JWT-mode WAT exchange（不要把真实 token 写进 shell history）：

```bash
cd personal-assistant-infra
export AGENT_IDENTITY_USER_TOKEN="<Microsoft Entra ID token>"
uv run python scripts/smoke_jwt_workload_access_token.py \
  --region cn-southwest-2 \
  --workload-identity agent-personal-assistant
unset AGENT_IDENTITY_USER_TOKEN
```

Windows PowerShell：

```powershell
cd personal-assistant-infra
$env:AGENT_IDENTITY_USER_TOKEN = Read-Host -MaskInput "Paste Microsoft Entra ID token"
uv run python scripts/smoke_jwt_workload_access_token.py `
  --region cn-southwest-2 `
  --workload-identity agent-personal-assistant
Remove-Item Env:AGENT_IDENTITY_USER_TOKEN
```

期望当前 service-created identity 仍返回：

```text
404 AgentIdentityDirectoryService.1002 workload identity not found
```

创建 customer-owned `CUSTOM_JWT` workload 后，应使用同一命令验证新 workload。
若新 workload 返回 WAT，则可确认 `created_by=SERVICE service.AgentNetwork` 是
本地主动 WAT exchange 的根因。

## 最终根因与验证结果

2026-07-06 20:05 本地 `/invocations` 已验证成功：

```text
Getting workload access token for JWT...
Successfully retrieved workload access token
Retrieved workload access token from context
```

最终根因分两层：

1. `agent-personal-assistant` 是 service-created workload。它可见，但不能作为
   本地代码主动调用 `create_workload_access_token()` 的目标，因此返回
   `404 AgentIdentityDirectoryService.1002 workload identity not found`。
2. `pa-local-jwt-workload` 必须是 customer-owned workload，但它的 JWT
   authorizer 需要和 Microsoft Entra ID token 精确匹配。Entra ID token 只有
   `aud=<client id>`，没有 `appid` / `azp` / `client_id`。因此不能配置
   `allowed_clients`。

关键坑：在 Agent Identity 后端，**省略 optional list 字段** 和 **显式传空数组**
不是等价配置。下面这种 raw config 可以成功：

```text
custom_jwt:
  discovery_url: https://login.microsoftonline.com/2a1d3739-88c5-4314-b921-acbeac0abbfa/v2.0/.well-known/openid-configuration
  allowed_audience:
    - 3a99a511-926c-475c-b6bc-325a037f574d
```

下面这种看起来等价，但会导致 JWT WAT exchange 返回
`400 AgentIdentityDirectoryService.2007 invalid JWT client ID`：

```text
custom_jwt:
  discovery_url: https://login.microsoftonline.com/2a1d3739-88c5-4314-b921-acbeac0abbfa/v2.0/.well-known/openid-configuration
  allowed_audience:
    - 3a99a511-926c-475c-b6bc-325a037f574d
  allowed_clients: []
  allowed_scopes: []
  custom_claims: []
```

因此 infra helper 必须在 optional list 为空时传 `None`，让 SDK 请求省略字段，
不能传 `[]`。

如果新 workload 返回：

```text
400 AgentIdentityDirectoryService.2007 invalid JWT client ID
```

先解码 JWT，按 claim 对齐 workload 配置：

- Microsoft Entra `id_token` 通常是
  `iss=https://login.microsoftonline.com/.../v2.0`、`aud=<client id>`，但没有
  `appid` / `azp` / `client_id`；local workload 应省略 `allowed_clients`，
  只用 `allowed_audience=<client id>` 约束它。不要显式写
  `allowed_clients: []`，该形态仍会触发 Agent Identity client-id 校验。
- Microsoft Graph access token 通常是 `iss=https://sts.windows.net/.../`、
  `aud=00000003-0000-0000-c000-000000000000`、`appid=<client id>`；如果未来
  明确选择这类 token，才需要改成 v1 discovery URL、Graph audience 和
  `allowed_clients=<appid>`。

如果返回 `2005 failed to verify JWT claims`，优先检查 `iss` 是否匹配
`discovery_url` 的 issuer。v1 Graph access token 不能使用 `/v2.0/.well-known`
discovery URL。
