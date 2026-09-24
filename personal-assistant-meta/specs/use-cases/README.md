# Personal Assistant Use Case 索引

本文是 Personal Assistant Demo use case 的索引入口。Use Case 按当前后端实际注册的 tool 模块拆分，重点说明每类 tool 面向用户提供什么能力，以及这些能力使用了 Agent Identity 的哪些机制。

## Agent Identity 能力总览

| Agent Identity 能力 | Demo 中的落点 | 价值 |
|---|---|---|
| Inbound Identity | Web Chat 通过 Microsoft Entra ID 登录，AgentArts Gateway 校验 JWT，Service 从已验证 token 的 `sub` 派生 `user_id` | Conversation ownership 不信任 caller User header |
| Runtime Session | Cloudflare Pages BFF 用 `pa_runtime_session` HttpOnly Cookie 生成并覆盖 `x-hw-agentarts-session-id` | 仅用于 AgentArts Runtime 路由，不参与业务 ownership 或 checkpoint key |
| Conversation Identity | Service 校验 `user_id + conversation_id`，LangGraph 使用 `thread_id=user_id:conversation_id` | 同一 Conversation 连续，不同用户和不同 Conversation 隔离 |
| Workload Identity | Gateway 注入 `X-HW-AgentGateway-Workload-Access-Token`，后端写入 `AgentArtsRuntimeContext` | Agent 容器用短期 Workload token 访问 Identity Service，不依赖本地长期凭据 |
| API Key Credential Provider | `DEEPSEEK_API_KEY` Provider 为 LLM 调用提供 DeepSeek API Key | LLM API Key 不进代码、不进 `.env`、不进镜像 |
| OAuth2 User Federation | `m365-email-provider`、`m365-calendar-provider`、`github-provider`、`gitee-provider` | Agent 以用户委托身份访问 Microsoft Graph、GitHub、Gitee |
| OAuth2 Token Vault | 用户完成授权后，第三方 access token 保存在 AgentArts Identity | 浏览器、LLM prompt、日志和业务数据库都不接触第三方 token |
| OAuth2 Auth URL Callback | 未授权时 `on_auth_url` 通过 SSE AuthCard 展示授权链接 | 授权链接带外呈现，不由 LLM 转述，减少误传和泄露 |
| OAuth2 Full Flow | Calendar callback 由 Cloudflare Pages BFF 转发到 Service，Service 调用 `complete_resource_token_auth` | 展示完整的服务端 session binding、state 校验和 replay 防护 |
| STS Credential Provider | `iam-users-readonly` 为华为云 IAM 只读查询提供临时凭证 | 云资源访问使用短期 STS，按最小权限授予 |
| Guarded Actions | 发送邮件、回复邮件、GitHub star 需要用户明确确认 | 凭据层允许访问，应用层对高风险写操作加运行态 Guard |

## 端到端身份链路

所有 tool use case 共享同一条 Agent Identity 基础链路：

图类型：**Sequence Diagram（时序图）**。用于说明 Web Chat、BFF、Gateway、Service、Agent Identity 和外部 API 之间的端到端凭据与数据流。

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant Web as Web Chat
    participant BFF as Cloudflare Pages Function
    participant GW as AgentArts Gateway
    participant Svc as FastAPI Service
    participant DB as PostgreSQL
    participant Agent as deepagents Agent
    participant ID as AgentArts Identity
    participant Ext as External API

    User->>Web: Microsoft Entra ID 登录
    Web->>BFF: POST /invocations<br/>Bearer id_token + conversation_id
    BFF->>BFF: 创建 / 读取 HttpOnly Runtime Session cookie
    BFF->>GW: 转发 JWT + 覆盖 Runtime Session header
    GW->>GW: CUSTOM_JWT 校验与 Runtime 路由
    GW->>Svc: 转发 Authorization + 注入 workload token
    Svc->>Svc: 从已验证 JWT sub 派生 user_id<br/>设置 Runtime Context
    Svc->>DB: 校验 Conversation ownership<br/>持久化 user message
    Svc->>Agent: message + thread_id=user_id:conversation_id
    Agent->>ID: 通过 Credential Provider 获取凭据
    ID-->>Agent: API Key / OAuth2 token / STS token
    Agent->>Ext: 调用 Microsoft Graph / GitHub / Gitee / HuaweiCloud IAM
    Ext-->>Agent: 返回业务数据
    Agent->>DB: 保存 LangGraph Checkpoint
    Agent-->>Svc: token / AuthCard / final response
    Svc->>DB: 持久化 assistant message
    Svc-->>GW: SSE 或 JSON response
    GW-->>BFF: 流式透传
    BFF-->>Web: same-origin response
```

这条链路体现了 Demo 的核心边界：

- Browser 只负责登录、携带 ID Token 和展示授权状态。
- BFF 独占 Runtime Session header 的生成和覆盖，Browser 不能选择 routing key。
- Gateway 是 production Inbound JWT 校验者并注入 Runtime WAT。
- Service 从 Gateway 已验证并转发的 JWT `sub` 派生 canonical `user_id`，忽略 caller User header。
- Runtime Session 与 Conversation / Checkpoint 生命周期解耦。
- Agent 通过 Identity SDK 获取外部凭据。
- 第三方 access token 不暴露给浏览器、LLM、日志或业务数据库。

## 基础身份 Use Case 文档

| Use Case | 文档 | Agent Identity 能力 |
|---|---|---|
| 登录后进入 Web Chat | [Web Chat Inbound Identity](web-chat-inbound-identity.md) | Inbound Custom JWT、Gateway header injection、Workload Access Token |
| Conversation 连续性与用户隔离 | [Conversation Isolation 与 Runtime Session](session-isolation.md) | JWT `sub` ownership、BFF Runtime Session、user-scoped Conversation checkpoint |

## Tool Use Case 文档

| Tool 模块 | Use Case 文档 | Agent Identity 能力 |
|---|---|---|
| `email_tools.py` | [Email Tools](email-tools.md) | OAuth2 User Federation、Token Vault、AuthCard、Guarded Action |
| `calendar_tools.py` | [Calendar Tools](calendar-tools.md) | OAuth2 User Federation、backend-owned callback、`complete_resource_token_auth`、Signed State、Replay Guard |
| `github_tools.py` | [GitHub Tools](github-tools.md) | OAuth2 User Federation、Token Vault、AuthCard、tool-level confirmation |
| `gitee_tools.py` | [Gitee Tools](gitee-tools.md) | OAuth2 User Federation、Token Vault、AuthCard |
| `iam_tools.py` | [HuaweiCloud IAM Tools](huaweicloud-iam-tools.md) | STS Credential Provider、短期云凭证、最小权限 |

## Demo 展示顺序

建议按以下顺序展示：

1. Web Chat 登录，说明 Inbound Identity 和 Gateway 注入身份。
2. Email Tools，展示 OAuth2 User Federation、邮件读取和发送前确认。
3. Calendar Tools，展示完整 OAuth2 callback 和 `complete_resource_token_auth`。
4. GitHub / Gitee Tools，展示多个 OAuth2 Provider 的统一接入方式。
5. HuaweiCloud IAM Tools，展示 STS 临时凭证和云资源只读访问。
