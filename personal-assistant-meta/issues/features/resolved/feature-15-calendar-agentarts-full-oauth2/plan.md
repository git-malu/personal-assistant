# Feature 15 Implementation Plan: Calendar Tool 使用 AgentArts 完整 OAuth2 流程

> 版本：v1.0 | 状态：Meta-Synthesized | Issue: [`issue.md`](./issue.md)
>
> 目标：新增 Microsoft 365 Calendar read-only Tool，并将它作为 AgentArts
> `complete_resource_token_auth` 完整 OAuth2 USER_FEDERATION 流程的示范实现。

---

## Executive Summary

本 Feature 在不修改既有 Email Tool 行为的前提下，为 Personal Assistant 增加只读
Microsoft 365 Calendar 能力：用户可以询问“今天有哪些会议”“下周日程”“查看某个会议详情”
和“搜索日历事件”。Calendar Tool 通过 AgentArts Identity SDK
`@require_access_token` 获取 Microsoft Graph `Calendars.Read` access token；当用户首次未授权时，
Web Chat 展示 AuthCard，用户在 popup 中完成 Microsoft 授权后跳回前端 callback page。
callback page 只负责读取 redirect query params，并通过同源 BroadcastChannel 将 callback
envelope 投递给主聊天窗口；主聊天窗口再使用自己的登录态完成
`/invocations/auth/oauth2/complete`。真正的 Resource Token Auth session binding 与
`complete_resource_token_auth` 只在可信后端完成，授权信任锚由服务端保存的 signed state
+ pending auth record 提供。

**核心结论**：本 Feature 是 Service + Client + Meta + E2E 联合变更。Service 新增
Calendar Tool 和 OAuth2 complete endpoint；Client 新增 callback page 与 AuthCard 状态扩展；
Infra 不新增 OpenTofu/HCL 资源，但需要部署配置与外部平台 allowlist 更新。Calendar 首版严格只读，
不创建、修改、删除或回复事件。

**SDK 实证约束**：本地 `agentarts-sdk-python` 源码已确认当前 SDK 的 `on_auth_url`
callback 签名为 `Callable[[str], Any]`，只传 `auth_url`，不会传 `session_uri`。因此
AuthCard / SSE event 不携带 `session_uri`；`session_uri` 的来源是用户完成授权后的浏览器
redirect callback query parameter。

---

## 1. 架构总览

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant UI as Web Chat
    participant CB as Callback Page
    participant Win as Main Window Auth Coordinator
    participant Agent as Personal Assistant Service
    participant Store as Signed State / Pending Auth Store
    participant SDK as AgentArts Identity SDK
    participant IdSvc as AgentArts Identity Service
    participant MS as Microsoft OAuth2
    participant Graph as Microsoft Graph API

    User->>UI: 询问日程
    UI->>Agent: POST /invocations
    Agent->>Store: 生成 signed state + pending auth record
    Agent->>Agent: 设置 session_id/workload token/callback_url/custom_state
    Agent->>SDK: 调用 @require_access_token 包裹的 Calendar Tool
    SDK->>IdSvc: get_resource_oauth2_token(provider=m365-calendar-provider)
    IdSvc-->>SDK: authorization_url + session_uri
    SDK-->>Agent: on_auth_url(auth_url)
    Agent-->>UI: SSE auth_card(auth_required, auth_url, provider)
    User->>MS: popup 打开 auth_url 并完成授权
    MS-->>CB: GET /auth/callback/m365-calendar?code&state&session_uri
    CB-->>Win: BroadcastChannel callback envelope
    Win->>Agent: POST /invocations/auth/oauth2/complete
    Agent->>Store: 校验 state / pending auth record / user binding
    Agent->>IdSvc: complete_resource_token_auth(session_uri, ServerBoundUser)
    IdSvc->>MS: code exchange
    IdSvc->>IdSvc: 保存 Calendar Resource Token
    Agent-->>Win: complete success + green AuthCard
    CB-->>UI: 可选 UI 同步 / auto-close
    UI->>Agent: 用户重试或自动重试原日历请求
    Agent->>SDK: 再次调用 Calendar Tool
    SDK->>IdSvc: get_resource_oauth2_token(provider=m365-calendar-provider)
    IdSvc-->>SDK: stored access token
    Agent->>Graph: Microsoft Graph Calendar API
    Graph-->>Agent: calendar events
    Agent-->>UI: 日程摘要
```

### 1.1 URL 与职责边界

| URL | 所在层 | 调用者 | 职责 |
|-----|--------|--------|------|
| `/auth/callback/m365-calendar` | Client | Microsoft / browser redirect | 展示授权结果，读取 `session_uri` / `state` / error query params，并通过 BroadcastChannel 向主窗口投递 callback envelope |
| `/invocations/auth/oauth2/complete` | Service via Cloudflare Pages Function proxy | 主聊天窗口 auth coordinator | 在可信服务端完成 `complete_resource_token_auth` |
| `/invocations` | Service via Gateway | Web Chat | 正常 Agent 对话与 Calendar Tool 调用 |

`AgentArtsRuntimeContext.set_oauth2_callback_url(...)` 必须设置为前端 absolute callback URL，
例如本地 `http://localhost:5173/auth/callback/m365-calendar`，生产
`https://<frontend-domain>/auth/callback/m365-calendar`。

主窗口 auth coordinator 负责接收 callback envelope、触发 complete request、更新 AuthCard；
callback page 本身不承担授权判定。

---

## 2. 文件变更矩阵

| 子系统 | 文件 | 操作 | 说明 |
|--------|------|------|------|
| Service | `app/settings.py` | 修改 | 增加 Calendar OAuth2 provider/callback/state TTL 等 typed settings |
| Service | `app/auth.py` | 修改 | 复用/扩展可信 user/session/workload token 提取逻辑；新增 callback complete 辅助校验 |
| Service | `app/main.py` | 修改 | `/invocations` 设置 OAuth2 callback/custom_state；新增 `/invocations/auth/oauth2/complete` endpoint |
| Service | `app/tools/calendar_tools.py` | 新建 | 3 个只读 Calendar tools + Graph API formatting/parsing/error handling |
| Service | `app/tools/__init__.py` | 修改 | 注册 `CALENDAR_TOOLS` |
| Service | `app/agent_handler.py` | 修改 | system prompt 增加 Calendar read-only 能力和隐私/只读边界 |
| Service Tests | `tests/test_calendar_tools.py` | 新建 | Calendar Tool 单元测试 |
| Service Tests | `tests/test_oauth2_complete.py` | 新建 | complete endpoint / state / replay / server-side auth context 测试 |
| Client | `src/App.tsx` | 修改 | 安装主窗口 BroadcastChannel coordinator，按 pathname 分流 callback page |
| Client | `src/components/auth/M365CalendarCallbackPage.tsx` | 新建 | OAuth2 callback relay page |
| Client | `src/lib/auth/calendar-oauth-bridge.ts` | 新建 | shared BroadcastChannel message schema / request-response helper |
| Client | `src/lib/auth/oauth2-complete.ts` | 新建 | 由主窗口 coordinator 调用的 complete API client |
| Client | `src/lib/chat/chat-event-handler.ts` | 修改 | 支持 `auth_failed` 和 coordinator 结果后的 AuthCard transition |
| Client | `src/types/chat.ts` | 修改 | 扩展 AuthCard/SSE event 类型 |
| Client | `src/stores/auth-card-store.ts` | 修改 | 增加 failed / provider-scoped complete 状态 |
| Client Tests | `src/components/auth/M365CalendarCallbackPage.test.tsx` | 新建 | callback page 成功/失败/缺参测试 |
| Client Tests | `src/lib/chat-adapter.test.ts` 或相关测试 | 修改 | AuthCard failed/complete 状态回归 |
| Meta | specs / architecture docs | 修改 | Email 与 Calendar 分开描述；AgentArts OAuth2 complete flow 文档化 |
| E2E | `personal-assistant-e2e/tests/features/feature-15-calendar-agentarts-full-oauth2/` | 新建 | 授权卡片、callback complete、Calendar read flow E2E |
| Infra | `.agentarts_config.yaml` / deployment runbook | 修改配置说明 | 不新增 HCL；同步 callback URL allowlist 与 provider 配置 |

---

## 3. Service Implementation Plan

### 3.1 Settings

在 `app/settings.py` 中新增 typed settings，避免 OAuth2 配置散落在代码里：

| Setting | 默认值 | 说明 |
|---------|--------|------|
| `m365_calendar_provider_name` | `m365-calendar-provider` | Calendar 独立 provider；若后续决定复用 common provider，需在 plan 修订中说明 |
| `m365_calendar_scopes` | `["https://graph.microsoft.com/Calendars.Read"]` | 最小权限 read-only scope |
| `oauth2_calendar_callback_url` | 无默认，生产必填 | absolute frontend callback URL |
| `oauth2_state_secret` | 无默认，生产必填 | signed state HMAC secret |
| `oauth2_pending_auth_ttl_seconds` | `600` | pending auth / replay window TTL |
| `graph_request_timeout_seconds` | `30` | Microsoft Graph request timeout |
| `graph_timezone` | `Asia/Shanghai` | `Prefer: outlook.timezone` 默认值，可配置 |

本地开发允许通过 `.env` 设置 `oauth2_calendar_callback_url=http://localhost:5173/auth/callback/m365-calendar`。
生产环境若缺失 callback URL 或 state secret，应在 startup validation 或首次 Calendar 调用时返回明确配置错误。

### 3.2 OAuth2 State 与 Pending Auth

MVP 推荐使用 signed state + 短 TTL server-side pending auth record：

```mermaid
flowchart LR
    Inv["/invocations"] --> State["生成 signed state<br/>user_id + session_id + provider + nonce + exp"]
    State --> Ctx["AgentArtsRuntimeContext.set_oauth2_custom_state(state)"]
    SDK["@require_access_token"] --> AuthURL["authorization_url"]
    AuthURL --> Browser["Microsoft OAuth2"]
    Browser --> Callback["/auth/callback?...state&session_uri"]
    Callback --> Complete["/invocations/auth/oauth2/complete"]
    Complete --> Verify["校验签名、exp、provider、user binding、nonce replay"]
    Verify --> IdSvc["complete_resource_token_auth"]
```

实现要点：

- `state` 必须绑定服务端可恢复的 user binding、`session_id`、provider、nonce、expiry。
- complete endpoint 不信任浏览器 body 中的 `user_id`，而是从 signed state + pending auth record
  恢复授权上下文。
- pending auth record 负责 replay 防护与完成态追踪；重复 callback 若已 complete，可返回
  idempotent success。
- 若未来 AgentArts Runtime 多副本部署，pending auth record 需要迁移到共享 store；
  本 Feature 将该点记录为 known limitation。

### 3.3 `/invocations` Context 设置

`main.py::invocations()` 当前已设置：

- `extract_gateway_user_id(request)`
- `extract_gateway_session_id(request)`
- `extract_workload_access_token(request)`

本 Feature 需在调用 handler 前追加：

- `AgentArtsRuntimeContext.set_oauth2_callback_url(settings.oauth2_calendar_callback_url)`
- `AgentArtsRuntimeContext.set_oauth2_custom_state(signed_state)`

注意：Email Tool 也会看到同一 request context 的 callback URL/custom_state。由于本 Feature 不改变 Email 行为，需验证这不会破坏现有 `m365-provider-common` 授权。若 SDK 对所有 provider 共用 callback URL，则 Email 未授权时也可能使用 Calendar callback URL；Implementation 阶段必须通过测试确认。若存在冲突，Calendar Tool 应改为 decorator 参数级 `callback_url` / `custom_state`，而不是 request-wide context。

### 3.4 Complete Endpoint

新增：

```text
POST /invocations/auth/oauth2/complete
```

Request body：

```json
{
  "provider": "m365-calendar-provider",
  "session_uri": "urn:uuid:...",
  "state": "...",
  "error": null,
  "error_description": null
}
```

Response：

```json
{
  "status": "complete",
  "provider": "m365-calendar-provider",
  "message": "Calendar authorization completed."
}
```

安全规则：

- 不接受 body 中的 `user_id` 作为授权依据。
- 完整授权上下文必须来自服务端保存的 signed state + pending auth record。
- 缺少 `session_uri` / `state` 返回 400。
- `state` 签名不合法、过期、provider 不匹配、user mismatch 返回 403。
- Identity SDK complete 失败返回 502/400 的安全错误，不回显 token、code、完整 `session_uri`。
- 重复 callback：若 nonce 已完成，返回 idempotent success 或 `already_complete`，不报惊吓式错误。

SDK 调用：

```python
from agentarts.sdk import IdentityClient

client = IdentityClient(region=get_region())
client.complete_resource_token_auth(
    session_uri=session_uri,
    user_identifier=server_bound_user,
)
```

### 3.5 Calendar Tool

新增 `app/tools/calendar_tools.py`：

| Tool | Graph endpoint | 关键参数 |
|------|----------------|----------|
| `list_calendar_events(start_time, end_time, calendar_id="primary")` | `GET /me/calendarView` 或 `/me/calendars/{id}/calendarView` | `startDateTime`, `endDateTime`, `$orderby=start/dateTime`, `$top` |
| `get_calendar_event(event_id, calendar_id="primary")` | `GET /me/events/{event_id}` 或 calendar-scoped event endpoint | `$select` 精简字段 |
| `search_calendar_events(query, start_time=None, end_time=None)` | Plan 阶段先验证 Graph `$search`；MVP 可回退为时间范围内拉取后本地过滤 | 避免因 Graph search 限制阻塞首版 |

统一 Graph response 结构：

```json
{
  "events": [
    {
      "id": "...",
      "subject": "...",
      "start": {"dateTime": "...", "timeZone": "..."},
      "end": {"dateTime": "...", "timeZone": "..."},
      "location": "...",
      "organizer": "...",
      "attendees": [],
      "isOnlineMeeting": true,
      "onlineMeetingUrl": "..."
    }
  ],
  "count": 1,
  "timezone": "Asia/Shanghai"
}
```

Tool 约束：

- 只读，禁止 `POST` / `PATCH` / `DELETE` Graph events。
- 不将 access token 写入 logs、tool result、LLM-visible error。
- Graph error 使用与 Email Tool 类似的 `_extract_graph_error` / `_format_tool_error` 模式，但返回用户友好中文。
- 使用 shared `httpx.AsyncClient` 或 module-level lazy client，避免每次调用建立连接。
- 设置 `Prefer: outlook.timezone="<configured timezone>"`。
- 支持分页 MVP：`limit` 默认 20，上限 50；如返回 `@odata.nextLink`，首版可返回 `has_more=True`。

### 3.6 Tool Registry 与 Prompt

`app/tools/__init__.py` 新增：

```python
try:
    from app.tools.calendar_tools import CALENDAR_TOOLS
    tools.extend(CALENDAR_TOOLS)
except ImportError as e:
    logger.warning("Calendar tools not available ...", exc_info=True)
```

`agent_handler.py` system prompt 增加：

- Calendar Tool 可读取用户日历和会议详情。
- Calendar Tool 首版 read-only，不能创建、修改、删除事件。
- 日历内容可能敏感；仅按用户请求范围读取和总结。
- 授权状态由 AuthCard / callback page 带外呈现，不要要求用户复制 token/code/session_uri。

---

## 4. Client Implementation Plan

### 4.1 Callback Page Routing 与 Relay

当前 `src/App.tsx` 没有 React Router。MVP 采用 pathname 分流：

```tsx
if (window.location.pathname === "/auth/callback/m365-calendar") {
  return <M365CalendarCallbackPage />;
}
```

该 callback page 仍包在 `MsalProvider` / `AuthGuard` 外层语境中时需谨慎：callback page
本身不做 complete，因此不依赖主窗口的 auth hydration。主窗口 auth coordinator 应在
`App.tsx` 顶层安装 BroadcastChannel listener，并在 hydrated + idToken 可用后处理 callback
envelope。

由于 AuthCard 打开 popup 使用 `noopener noreferrer`，生产实现不能依赖 `window.opener`
作为主通路；BroadcastChannel 是主要回传机制，`postMessage` 仅作兼容补充。

### 4.2 `M365CalendarCallbackPage`

职责：

- 读取 `window.location.search` 中的 `session_uri`、`state`、`error`、`error_description`。
- 如果 `error` 存在，展示授权失败并通过 BroadcastChannel / `postMessage`
  通知主窗口。
- 如果缺少 `session_uri` 或 `state`，展示可理解错误，不调用后端。
- 通过 BroadcastChannel 发送 callback envelope 给主窗口；主窗口负责发起
  `/invocations/auth/oauth2/complete`。
- complete 成功后展示“授权完成，可以关闭窗口”，并可发出 UI 同步消息；
- 如果浏览器环境支持跨窗通信，可选实现 `postMessage`，但不作为授权依赖。

- 不写入 localStorage/sessionStorage access token。
- 不展示 raw token/code/session_uri；debug 信息只在开发日志中脱敏输出。

### 4.3 Main Window OAuth Coordinator

`src/App.tsx` 需要在主窗口安装 BroadcastChannel coordinator：

- 监听 callback envelope request；
- 如果 auth store 已 hydrated 且已有可用 idToken，立即调用 complete API；
- 如果尚未 hydrated，则将 request 暂存，等登录态 ready 后再处理；
- complete 成功后更新匹配 provider 的 AuthCard 为 green；
- complete 失败后发送失败 response，让 callback page 展示安全错误；
- 将成功 / 失败 response 回传给 callback page，便于 popup 自动关闭或重试提示。

Coordinator 应使用主窗口的登录态构建同样的 auth headers，避免 popup/sessionStorage
不一致问题。

### 4.4 Complete API Client

新增 `src/lib/auth/oauth2-complete.ts`：

- 发送 `POST /invocations/auth/oauth2/complete`。
- 复用现有 auth token 发送机制。如果现有 `invokeChat` 的 header 构造只封装在 chat API
  client 中，应提取 shared `buildAuthHeaders()`，让主窗口 coordinator 具备同样的登录态上下文。
- 响应非 2xx 时解析 `detail`，返回用户友好错误。

### 4.5 AuthCard 状态扩展

现有 AuthCard 已支持 provider-scoped `auth_required` 和 `auth_complete`。本 Feature 增加：

- `auth_failed` 状态；
- callback envelope 经过主窗口 coordinator 处理后更新匹配 provider 的 AuthCard；
- 授权完成后提供“重试刚才的问题”提示或自动重试 hook。

MVP 建议先做半自动重试：AuthCard 显示“授权已完成，请重新发送刚才的日历请求”。自动重试需要可靠保存原始 user message 与 run lifecycle，复杂度较高，可作为 P2。

---

## 5. Test Plan

### 5.1 Service Unit Tests

`tests/test_calendar_tools.py`：

- `list_calendar_events` 构造正确 endpoint、query params、headers。
- `list_calendar_events` 解析 subject/start/end/location/organizer/attendees。
- `list_calendar_events` 支持 timezone `Prefer` header。
- `get_calendar_event` 解析单事件详情。
- `search_calendar_events` 验证 Graph `$search` 或 fallback 本地过滤策略。
- Graph 401/429/503/error JSON 转为安全错误。
- access token 不出现在 result/log message。
- Tool 函数不调用写操作 endpoint。

`tests/test_oauth2_complete.py`：

- 缺少 `session_uri` → 400。
- 缺少/非法/过期 `state` → 403。
- body 伪造 `user_id` 不影响可信 user 校验。
- user mismatch → 403。
- valid request 调用 `IdentityClient.complete_resource_token_auth`，参数为服务端恢复的 auth context。
- duplicate callback idempotent。
- SDK complete 失败返回安全错误。

### 5.2 Service Integration Tests

- 未授权 Calendar Tool 触发 SSE `auth_card`，只包含 `auth_url`，不包含 `session_uri`。
- main-window coordinator 完成 `/invocations/auth/oauth2/complete` 后，同一 user 再次调用
  Calendar Tool 可获得 injected token（mock SDK）。
- Email Tool 授权行为不回归。

### 5.3 Client Tests

- callback page success：query params → BroadcastChannel request → wait for ack → success UI。
- main-window coordinator：request envelope → POST complete → success response → green AuthCard。
- callback page error query：不 POST complete → failed UI → `postMessage(auth_failed)` 或
  BroadcastChannel failed envelope。
- missing `session_uri/state`：failed UI。
- complete API 401/403/500：展示可理解错误。
- AuthCard `auth_failed` 状态渲染。
- request/response provider mismatch 不更新 unrelated card。

### 5.4 E2E Tests

目录：`personal-assistant-e2e/tests/features/feature-15-calendar-agentarts-full-oauth2/`

场景：

1. 用户询问日程，未授权时 Web Chat 显示 Calendar AuthCard。
2. AuthCard 打开 popup 到 Microsoft/模拟 OAuth URL。
3. callback page 带 `session_uri/state` 通过 BroadcastChannel 投递 callback envelope。
4. main-window coordinator 调用 complete endpoint，主窗口 AuthCard 变为 complete。
5. 用户重试日历请求，看到日程摘要。
6. callback failed / expired session 显示安全错误，可重新发起授权。

真实 Microsoft OAuth2 不适合在 CI 中跑；CI 使用 mock/staging identity fixture，人工 staging 验证覆盖真实 Entra App allowlist。

---

## 6. Meta / Architecture 文档更新

Implementation 完成时至少更新：

| 文档 | 更新内容 |
|------|----------|
| `specs/overall_specifications.md` | 增加 Calendar read-only 用户能力 |
| `specs/dictionary.md` | 增加 Calendar Tool、Resource Token Auth complete flow、OAuth2 callback page 术语 |
| `architecture/backend_architecture.md` | 增加 Calendar Tool、OAuth2 complete endpoint、state/session binding diagram |
| `architecture/frontend_architecture.md` | 增加 AuthCard callback page / BroadcastChannel relay flow |
| `architecture/overall_architecture.md` | 更新 Microsoft 365 Tools 总览 |
| `architecture/cloud-service/huaweicloud/` | AgentArts OAuth2 complete flow、Allowed Resource OAuth2 Return URL、Gateway proxy path |
| `personal-assistant-service/README.md` | 本地 env 与 Calendar OAuth2 调试说明 |
| `personal-assistant-client/README.md` | callback URL 与 Cloudflare Pages Function proxy 说明 |

---

## 7. Deployment / Configuration

### 7.1 外部平台配置

以下 URL 必须一致：

```text
https://<frontend-domain>/auth/callback/m365-calendar
```

配置位置：

- Microsoft Entra App redirect URI allowlist；
- AgentArts workload identity Allowed Resource OAuth2 Return URL allowlist；
- Calendar OAuth2 Credential Provider callback/return URL 配置（如平台要求 provider 级配置）。

### 7.2 Cloudflare Pages Function Proxy

需要确认生产 proxy 覆盖：

```text
POST /invocations/auth/oauth2/complete
→ AgentArts Gateway /runtimes/personal-assistant/invocations/auth/oauth2/complete
```

如果现有 Pages Function 只 proxy `/invocations` exact path，需要扩展为 `/invocations/*`。
主窗口发起 complete request 时也必须走 same-origin proxy，不能绕过 Cloudflare Pages。

### 7.3 Provider 策略

首选独立 provider：

```text
m365-calendar-provider
scope: https://graph.microsoft.com/Calendars.Read
```

理由：

- Calendar 首版只读，独立 consent 更符合 least privilege。
- 不改变 Email `m365-provider-common` token cache 与 consent UX。
- complete flow 示例边界清晰。

若 Implementation 发现 AgentArts / Microsoft provider 管理要求复用 common provider，必须在 plan 修订中记录 scope、consent UX、token cache 的 trade-off。

---

## 8. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|:------:|------|
| SDK `on_auth_url` 不传 `session_uri`，实现误以为 AuthCard 可拿到 | High | 已写入 issue 与本 plan：`session_uri` 仅来自 redirect callback query parameter |
| request-wide `set_oauth2_callback_url/custom_state` 影响 Email Tool | High | Implementation 必须测试 Email 未授权路径；若冲突，Calendar decorator 使用参数级 callback/custom_state |
| popup 直连 complete 会因 `noopener` / `sessionStorage` / 缺少主窗口登录态而在生产失败 | High | 让主窗口 coordinator 完成 `/invocations/auth/oauth2/complete`，popup 只投递 callback envelope |
| callback complete 缺少可信 user header | High | complete endpoint 必须走 same-origin proxy/Gateway auth；主窗口 coordinator 复用登录 Authorization header |
| state/replay 防护不足 | High | signed state + TTL + nonce replay guard；不信任 body user_id |
| AgentArts Runtime 多副本导致 in-memory nonce 不共享 | Medium | MVP 记录 known limitation；生产多副本前迁移 external store |
| Cloudflare Pages Function 没有 proxy complete path | High | 部署前验证 `/invocations/auth/oauth2/complete` path |
| Graph search 行为受限 | Medium | Plan 阶段验证；必要时采用时间范围拉取 + 本地过滤 |
| 日历内容敏感 | High | 只读 scope、日志脱敏、按用户请求范围读取、不暴露 token/session_uri |
| 重复 callback 用户看到失败 | Medium | complete endpoint 做 idempotent success / already_complete |
| 真实 OAuth2 E2E 难以自动化 | Medium | CI mock + staging 人工验证真实 Entra/AgentArts allowlist |

---

## 9. Implementation Order

```mermaid
gantt
    title Feature 15 Calendar OAuth2 Full Flow Implementation Order
    dateFormat  YYYY-MM-DD
    axisFormat  %m/%d

    section Meta
    plan.md accepted                         :m1, 2026-06-22, 1d

    section Service
    Settings + OAuth2 state helpers          :s1, after m1, 1d
    Complete endpoint                        :s2, after s1, 1d
    Calendar tools                           :s3, after s1, 2d
    Tool registry + prompt                   :s4, after s3, 1d
    Service tests                            :s5, after s2, 2d

    section Client
    Callback relay + main-window coordinator :c1, after s2, 2d
    AuthCard failed/complete UX              :c2, after c1, 1d
    Client tests                             :c3, after c2, 1d

    section Docs and E2E
    Architecture/spec updates                :d1, after s4, 1d
    E2E mock/staging tests                   :e1, after c3, 2d
```

执行顺序：

1. Service：先实现 settings + signed state helpers + complete endpoint。
2. Service：实现 Calendar Tool，并注册到 `build_tools()`。
3. Service：补 system prompt 和 unit/integration tests。
4. Client：实现 callback relay page、main-window coordinator 和 complete API client。
5. Client：扩展 AuthCard failed/complete 状态与 tests。
6. Meta：同步 specs/architecture/README/runbook。
7. E2E：先 mock flow，再 staging 验证真实 Microsoft/AgentArts allowlist。
8. 全量验证：`uv run ruff check .`、`uv run pytest tests/`、`npm run test`、`npm run build`、E2E。

---

## 10. Verification Commands

Service：

```bash
cd personal-assistant-service
uv run ruff check .
uv run pytest tests/test_calendar_tools.py tests/test_oauth2_complete.py -v
uv run pytest tests/ -v
```

Client：

```bash
cd personal-assistant-client
npm run test
npm run build
```

E2E：

```bash
cd personal-assistant-e2e
pytest tests/features/feature-15-calendar-agentarts-full-oauth2/ -v
```

Manual staging：

- 配置 Microsoft Entra redirect URI。
- 配置 AgentArts Allowed Resource OAuth2 Return URL。
- 配置 Calendar OAuth2 Credential Provider。
- 通过 Web Chat 触发 Calendar 授权。
- 完成 callback 后重试日历读取。
- 确认 Email Tool 授权/发送 guard 不回归。

---

## 11. Acceptance Criteria Mapping

| AC | Plan 覆盖 |
|----|-----------|
| AC1 Calendar Tool | §3.5, §3.6, §5.1 |
| AC2 OAuth2 callback + complete | §1, §3.2, §3.4, §4.1-4.4, §5.2 |
| AC3 安全与隔离 | §3.2, §3.4, §8 |
| AC4 用户体验 | §4.2, §4.3, §4.5, §5.3 |
| AC5 回归保护 | §5.2, §9, §10 |

---

## 12. Four-Question Gate

| Question | Answer | 说明 |
|----------|:------:|------|
| Is it best practice? | Yes | OAuth callback page 只做 relay，真正的 token binding 在可信主窗口与服务端完成；signed state + pending auth record + least privilege 符合 Separation of Concerns 与 Defense in Depth。 |
| Is it industry standard? | Yes | Popup OAuth + same-origin callback relay + server-side authorization code / session binding 是主流生产模式；BroadcastChannel 属于现代浏览器推荐的同源跨窗通信手段。 |
| Is it conventional? | Yes | 新成员会自然预期“主应用完成授权、popup 只做回调载体”；这种 BFF 式授权收口比让 popup 直连后端更常见。 |
| Is it modern? | Yes | BroadcastChannel、typed settings、structured logging、server-side replay guard 和 E2E/staging OAuth 验证都属于当前 web / agent 应用的现代实践。 |

---

## 13. Implementation Checklist

### Service

- [ ] 新增 Calendar OAuth2 settings。
- [ ] 新增 signed state helper 与 replay guard。
- [ ] `/invocations` 设置 calendar callback URL/custom state。
- [ ] 新增 `/invocations/auth/oauth2/complete`。
- [ ] 新增 `calendar_tools.py` 三个只读工具。
- [ ] 注册 `CALENDAR_TOOLS`。
- [ ] 更新 system prompt。
- [ ] Service unit/integration tests 通过。

### Client

- [ ] 新增 callback relay page 分流。
- [ ] 新增 main-window BroadcastChannel coordinator。
- [ ] 新增 complete API client。
- [ ] callback page success/failed/missing param UX。
- [ ] AuthCard 支持 `auth_failed`。
- [ ] callback envelope request/response 更新主窗口 AuthCard。
- [ ] Client tests/build 通过。

### Meta / E2E / Deploy

- [ ] specs / architecture / README / runbook 同步。
- [ ] Cloudflare Pages Function proxy complete path。
- [ ] Microsoft Entra + AgentArts allowlist 同步。
- [ ] E2E mock flow 通过。
- [ ] Staging 真实 OAuth2 验证通过。
- [ ] Email Tool 行为回归验证通过。
