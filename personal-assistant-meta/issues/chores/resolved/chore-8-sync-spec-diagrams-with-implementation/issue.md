---
status: resolved
---

# Chore 8: 同步 Specs 架构图与当前实现

## 变更动机

`personal-assistant-meta/specs/` 中的架构图仍混有早期设计：浏览器直接管理
Runtime Session、Checkpoint 使用 `user_id:session_id`、Service 信任 Gateway User
header、Web Chat 调用 `/chat/stream`，以及已接入 AgentArts Memory / Sandbox、飞书和
OfficeClaw。这些描述与当前 Web Chat、Cloudflare Pages BFF、Conversation API 和
FastAPI Service 的实现不一致。

## 影响范围

- `specs/overall_specifications.md`
- `specs/dictionary.md`
- `specs/use-cases/README.md`
- `specs/use-cases/web-chat-inbound-identity.md`
- `specs/use-cases/session-isolation.md`
- `specs/use-cases/calendar-tools.md`

## 实现基线

- 当前唯一 production 产品入口是 Web Chat；飞书和 OfficeClaw 属于 roadmap。
- Cloudflare Pages BFF 通过 HttpOnly Cookie 管理 Runtime Session，并覆盖上游
  `x-hw-agentarts-session-id`；该 ID 只用于 Gateway 路由。
- AgentArts Gateway 校验 CUSTOM_JWT，Service 从已验证 Bearer JWT 的 `sub` 派生
  canonical `user_id`，不信任 caller User header。
- Conversation 与 Message 存储在 PostgreSQL；LangGraph Checkpoint 使用
  `thread_id = user_id:conversation_id`。
- Calendar OAuth callback 由 Pages Function 恢复短期 callback context，再经 Gateway
  转发到 Service；signed state 绑定 user、provider、nonce 和 expiry，不绑定 Runtime
  Session。
- AgentArts Memory 和 Sandbox 尚未接入。

## 验收标准

- [x] `specs/` 下所有 Mermaid 图都有图类型和用途说明。
- [x] 图中的路由、身份来源、Runtime Session、Conversation 和 Checkpoint 边界与代码一致。
- [x] Calendar OAuth callback 图包含 BFF callback bridge、signed state 校验和 replay guard。
- [x] 当前能力与 roadmap 在图和正文中明确区分。
- [x] Mermaid 语法通过 renderer 验证。

## 验证依据

- GitNexus execution flow / symbol context：`proxyInvocationsRequest`、`invocations`、
  `AgentHandler._build_config`、`calendar_oauth2_callback`、`build_tools`。
- 当前实现：Client Pages Functions、Service route/auth/invocation/conversation/OAuth2 代码。
- 当前架构 source of truth：`architecture/overall_architecture.md`、
  `architecture/frontend_architecture.md`、`architecture/backend_architecture.md` 和
  `architecture/session-state-management.md`。
