# Personal Assistant — 总体功能规格书

> 版本：v0.6 | 状态：当前实现基线 | 最后核对：2026-09-24 | 基于 AgentArts 平台

---

## 1. 项目概述

Personal Assistant 是一个对话式 AI 助手应用，用户通过自然语言对话管理邮件、日历、代码仓库并生成工作报表。当前实现通过 PostgreSQL Conversation / Message 和 LangGraph Checkpoint 保存对话状态；跨 Conversation 的 AgentArts 长期 Memory 尚未接入。系统可在用户授权后以用户身份访问 Microsoft 365、GitHub 和 Gitee，也可通过受限 STS 凭据访问华为云 IAM。

### 1.1 核心价值

- **Web Chat 接入**：当前 production 产品入口是 Web Chat；飞书直连和 OfficeClaw 仍在 roadmap
- **安全委托**：Agent 以用户委托身份调用外部服务，无需暴露个人凭证给 Agent 代码

### 1.2 目标用户

| 用户类型 | 典型场景 |
|----------|----------|
| 职场人士 | 通过对话处理邮件、查询收件箱摘要 |
| 开发者 | 通过对话管理邮件，辅助日常工作 |

---

## 2. 接入渠道与当前拓扑

当前只有 Web Chat 接入 production。浏览器通过 Cloudflare Pages Functions BFF 访问 AgentArts Gateway 和 FastAPI Service；BFF 管理 Runtime Session routing key，Service 管理 Conversation、Message 和 Agent Checkpoint。

图类型：**Container / Deployment Diagram（容器 / 部署图）**。用于区分当前 production 调用链与尚未接入的 roadmap 渠道。

```mermaid
flowchart LR
    subgraph Current["当前 production"]
        User["用户"] --> WebChat["Web Chat<br/>React + MSAL"]
        WebChat -->|"same-origin /invocations<br/>/api/conversations/*"| Pages["Cloudflare Pages<br/>Pages Functions BFF"]
        Pages -->|"Bearer JWT + BFF Runtime Session"| Gateway["AgentArts Gateway<br/>CUSTOM_JWT"]
        Gateway -->|"validated request + Runtime WAT"| Service["FastAPI Service<br/>:8080"]
        Service --> Invocation["InvocationService<br/>ownership + persistence + SSE"]
        Invocation --> Agent["AgentHandler<br/>deepagents + LangGraph"]
        Invocation --> DB["PostgreSQL<br/>Conversation / Message"]
        Agent --> Checkpoint["PostgreSQL<br/>LangGraph Checkpoint"]
        Agent --> Tools["Registered Tools"]
        Tools --> Identity["AgentArts Identity<br/>OAuth2 / STS"]
    end

    subgraph Roadmap["Roadmap，尚未接入"]
        Feishu["飞书直连"]
        OfficeClaw["OfficeClaw"]
        Adapters["待实现 channel adapter"]
        Feishu -.-> Adapters
        OfficeClaw -.-> Adapters
    end
```

| 渠道 | 接入方式 | 状态 | 说明 |
|------|----------|------|------|
| **Web Chat** | 浏览器 → Cloudflare Pages BFF → AgentArts Gateway → `/invocations` | 已实现 | Microsoft Entra ID 登录、Conversation 管理、SSE 流式响应和 OAuth Auth Card |
| **飞书直连** | 待实现 channel adapter | Roadmap | 当前仓库没有 `/feishu/webhook` route 或 Bot adapter |
| **OfficeClaw** | 待实现 AgentArts / client integration | Roadmap | 当前没有可用 OfficeClaw client 或 Service adapter |

当前 Conversation 状态只服务 Web Chat。AgentArts Memory 与 Sandbox 尚未接入，不能把 LangGraph Checkpoint 等同于跨 Conversation 长期 Memory。

---

## 3. 功能模块

详细 use case 已拆分到 [`UseCase/`](use-cases/README.md)。当前功能模块分为两类：基础身份能力和已注册 tool 能力。

| 类型 | 模块 | Use Case 文档 | 当前状态 |
|---|---|---|---|
| 基础身份能力 | Web Chat Inbound Identity | [`UseCase/web-chat-inbound-identity.md`](use-cases/web-chat-inbound-identity.md) | 已实现 |
| 基础身份能力 | Conversation Isolation | [`UseCase/session-isolation.md`](use-cases/session-isolation.md) | 已实现 |
| Tool 能力 | Email Tools | [`UseCase/email-tools.md`](use-cases/email-tools.md) | 已实现 |
| Tool 能力 | Calendar Tools | [`UseCase/calendar-tools.md`](use-cases/calendar-tools.md) | 已实现 |
| Tool 能力 | GitHub Tools | [`UseCase/github-tools.md`](use-cases/github-tools.md) | 已实现 |
| Tool 能力 | Gitee Tools | [`UseCase/gitee-tools.md`](use-cases/gitee-tools.md) | 已实现 |
| Tool 能力 | HuaweiCloud IAM Tools | [`UseCase/huaweicloud-iam-tools.md`](use-cases/huaweicloud-iam-tools.md) | 已实现 |
| Root capability | Report | [§3.9 Report Root Capability](#39-report-root-capability) | 已实现 |

### 3.1 Web Chat Inbound Identity

用户通过 Microsoft Entra ID 登录 Web Chat 后，浏览器向 same-origin `/invocations` 发送 `Authorization: Bearer <id_token>` 和 Conversation-aware request body。Cloudflare Pages BFF 从 HttpOnly Cookie 创建或复用 Runtime Session，并覆盖上游 `x-hw-agentarts-session-id`。AgentArts Gateway 校验 JWT、路由到 Runtime 并注入 Workload token；Service 从 Gateway 已验证并转发的 JWT `sub` 派生 canonical `user_id`。

- **登录入口**：Web Chat + Microsoft Entra ID。
- **可信身份来源**：Gateway 已验证并转发的 Bearer JWT `sub`；caller User header 不参与 ownership。
- **Runtime Session**：由 Cloudflare Pages BFF 的 `pa_runtime_session` HttpOnly Cookie resolver 管理，只用于 Gateway 路由。
- **Conversation identity**：request body 中的 `conversation_id`，Service 必须结合 `user_id` 校验 ownership。
- **Workload Identity**：`X-HW-AgentGateway-Workload-Access-Token` 用于 Runtime 访问 AgentArts Identity。
- **详细规格**：[`UseCase/web-chat-inbound-identity.md`](use-cases/web-chat-inbound-identity.md)。

### 3.2 Conversation Isolation

系统使用从已验证 JWT 派生的 `user_id` 和 Service 管理的 `conversation_id` 构造 LangGraph checkpoint key：`thread_id = "{user_id}:{conversation_id}"`。Runtime Session 与业务 Conversation 解耦，一个 Runtime Session 可以承载多个 Conversation，同一 Conversation 也可以从新的 Runtime Session 恢复。

- **同一 Conversation 连续**：Agent 能恢复当前 Conversation 的短期上下文。
- **不同 Conversation 隔离**：同一用户的不同 Conversation 不共享 checkpoint。
- **跨用户隔离**：所有 Conversation / Message 查询同时按 `user_id + conversation_id` 过滤，thread namespace 也包含 `user_id`。
- **Checkpoint 后端**：支持 in-memory、SQLite 和 PostgreSQL。
- **详细规格**：[`UseCase/session-isolation.md`](use-cases/session-isolation.md)。

### 3.3 Email Tools

Email Tools 以 User Federation 模式调用 Microsoft Graph Mail API，支持邮件列表、邮件详情、邮件搜索、发送邮件和回复邮件。

- **Provider**：`m365-email-provider`。
- **读操作**：`list_emails`、`get_email`、`search_emails`。
- **写操作**：`send_email`、`reply_to_email`。
- **Guard**：发送和回复必须先展示预览并获得用户明确确认。
- **详细规格**：[`UseCase/email-tools.md`](use-cases/email-tools.md)。

### 3.4 Calendar Tools

Calendar Tools 以 User Federation 模式只读访问 Microsoft 365 Calendar，是当前项目中 AgentArts OAuth2 full flow 的完整示范。

- **Provider**：`m365-calendar-provider`。
- **Scope**：`https://graph.microsoft.com/Calendars.Read`。
- **只读能力**：`list_calendar_events`、`get_calendar_event`、`search_calendar_events`。
- **OAuth2 Full Flow**：Service-owned callback、signed state、replay guard、`complete_resource_token_auth`。
- **详细规格**：[`UseCase/calendar-tools.md`](use-cases/calendar-tools.md)。

### 3.5 GitHub Tools

GitHub Tools 以用户身份访问 GitHub API，支持仓库列表、目录查看、文件读取、代码搜索和仓库 star。

- **Provider**：`github-provider`。
- **读操作**：`github_list_repositories`、`github_list_repo_contents`、`github_get_file_content`、`github_search_code`。
- **写操作**：`github_star_repository`。
- **Tool-level Guard**：`confirm=False` 返回预览，用户确认后 `confirm=True` 才执行 star。
- **详细规格**：[`UseCase/github-tools.md`](use-cases/github-tools.md)。

### 3.6 Gitee Tools

Gitee Tools 以用户身份访问 Gitee API，当前提供仓库列表读取能力。

- **Provider**：`gitee-provider`。
- **只读能力**：`gitee_list_repositories`。
- **授权方式**：OAuth2 User Federation + AuthCard。
- **详细规格**：[`UseCase/gitee-tools.md`](use-cases/gitee-tools.md)。

### 3.7 HuaweiCloud IAM Tools

HuaweiCloud IAM Tools 使用 AgentArts Identity STS Credential Provider 获取短期云凭证，调用 Huawei Cloud IAM API 进行只读查询。

- **Provider**：`iam-users-readonly`。
- **能力**：`huaweicloud_list_iam_users`。
- **凭据类型**：STS 临时凭证，不使用长期 AK/SK。
- **安全边界**：只读查询，不返回 AK/SK/Token。
- **详细规格**：[`UseCase/huaweicloud-iam-tools.md`](use-cases/huaweicloud-iam-tools.md)。

### 3.8 GitHub MCP Activity Data Source

GitHub MCP Activity Data Source 通过 AgentArts MCP Gateway 访问 GitHub remote MCP，
为 Report internal orchestration 和两个 Agent-facing GitHub activity tools 提供
`commit`、`pull_request`、`issue`、`review`、`comment` 五类工程活动数据。

- **Gateway**：`gateway-github-mcp`，入站 IAM 认证。
- **Target**：`target-github-mcp`，Streamable HTTP，指向 GitHub MCP read-only
  endpoint。
- **平台身份**：使用 Target 中托管的 GitHub PAT，表示 platform GitHub account；
  不代表当前 Web Chat 用户。
- **Service 认证**：Service 使用 WAT → AgentArts Identity STS provider →
  `github-mcp-gateway` 临时 IAM 凭据 → HuaweiCloud API signing 调用 MCP Gateway。
- **内部契约**：输出 `GitHubActivityEvent`。`review` 的 `parent_external_id` 是
  Pull Request number；`comment` 的 `parent_external_id` 是 Issue 或 Pull Request
  number。Service 保留 `github_mcp_resolve_identity`、
  `github_mcp_list_repositories`、`github_mcp_search_activity` 和
  `github_mcp_get_detail` 四个 internal source functions；它们不注册为 Agent Tool。
- **Agent-facing 契约**：Agent 只看到 `github_search_activity` 和
  `github_get_activity_detail`。两个 Tool 的所有返回结果均明确包含
  `identity_scope="platform"`；该字段表示 MCP 数据访问身份，默认查询不强制按平台
  账号过滤 actor，因此结果可包含平台凭据可见仓库中的其他作者活动。
- **Report 调用约束**：Feature 18 Report 会先通过 GitHub OAuth 确认报表主体
  `subject_login=A`，再把 A 可访问的仓库 allowlist 和 `actor=A` 传给该 internal
  source。此时 MCP 仍是 platform data access channel，但不得使用 platform actor
  或 platform repository discovery 作为 Report 的身份 / 范围回退。
- **详情查询**：`github_mcp_get_detail` 支持全部五类事件。聚合
  `pull_request_read` 时固定传入 `method="get"`；聚合 `issue_read` 时根据 Target
  schema 依次读取 `get`、`get_comments`、`get_sub_issues`、`get_parent`、
  `get_labels`，并写入事件的 `details`。
- **安全边界**：不暴露 raw MCP passthrough；GitHub MCP source 自身不注册
  `generate_report`，也不把 GitHub MCP 原子工具作为 root capability 暴露给 Agent。
  Feature 18 的独立 Report root tool 通过 typed internal source contract 消费该数据源。
- **开关边界**：`GITHUB_MCP_ENABLED` 是 internal data source 的 master switch；
  `GITHUB_ACTIVITY_TOOLS_ENABLED` 控制两个业务 Tool 是否对 Agent 可见。
  `build_tools()` 仅在两者同时为 `true` 时注册 `GITHUB_ACTIVITY_TOOLS`；关闭
  exposure switch 可只保留 internal data source。该入口始终使用 platform GitHub
  account，不代表当前用户授权。

### 3.9 Report Root Capability

Report 是用户可见的高层能力。用户请求日报、周报、月报、工作总结或研发进展总结时，
Agent 优先调用 `generate_report`，由该 tool 确定性完成时间窗口解析、数据采集、证据
归一化、warning 聚合和 Markdown 渲染，而不是临时串联多个 low-level tools。

- **Report type**：支持 `daily`、`weekly`、`monthly`、`custom`；前三者按用户或系统
  timezone 推导自然日、自然周、自然月。用户给出单个日期时通过 `reference_date`
  锚定该日期对应的自然周期；给出起止日期时严格使用显式 `start_at` / `end_at`，
  不得替换为当前日期或当前周期。`custom` 必须使用显式范围。
- **默认 sources**：未传 `sources` 时固定启用 `github`、`email`、`calendar`；用户
  显式传入时仅采集指定 source。
- **授权先于采集**：Report 对已选 source 先按 `GitHub -> Email -> Calendar` 顺序完成
  OAuth preflight；所有授权尝试结束前不读取任何 GitHub、Email 或 Calendar 业务数据。
  单项授权失败不阻断后续 provider，采集阶段只处理已授权 source。
- **并行采集**：全部授权尝试结束后，已授权 source 可并行采集以缩短总等待时间；完成
  顺序不影响输出，evidence、warning、coverage 与 context 仍按用户选择的 source 顺序
  确定性合并。
- **Email 范围**：默认读取 `inbox` 与 `sentitems`，并在 Report 层按规范化时间窗口
  过滤邮件证据，不改变 Email public tool schema。
- **GitHub 身份与范围**：Report 先通过当前 Web Chat 用户的 GitHub OAuth
  `/user` 确认报表主体账号 A，再全分页枚举 `/user/repos` 得到 A 可访问的全部仓库
  allowlist。尚未授权时先触发 `auth_required` Auth Card 并等待用户完成授权；只有
  授权失败或超时才将 GitHub source 降级为 warning。随后 Report 直接调用 Feature 17 internal source，传入
  `repositories=allowlist` 和 `actor=A`，只保留 A 自己的工程活动；不调用
  Agent-facing GitHub activity tool，不从 platform actor 或 platform repository
  discovery 回退扩展范围。MCP credential 只表示 `data_access_identity=platform_mcp`
  的读取通道。
- **GitHub 上限与详情**：Report 会跟随 GitHub MCP cursor 直到耗尽或出现 typed
  warning，再按全局最多 100 条活动截断，并为选中活动尽量调用
  `github_mcp_get_detail` 补充结构化详情；截断或权限 / 限流问题通过 warning 和
  coverage 降级呈现。
- **确定性输出**：首期 `format` 固定为 `markdown`，正文由 deterministic renderer
  根据规范化 evidence、source coverage 和 warnings 生成；tool 内不发起额外 LLM 调用。
- **部分失败**：各 source 独立降级。任一 source 不可用时，结果保留其他 source 的
  内容，同时追加脱敏 warning，并将对应 coverage 标记为 `partial`、`unavailable` 或
  `skipped`。
- **结果契约**：`ReportResult` 包含 `report_type`、`window`、`content`、
  `ReportEvidence[]`、`warnings`、`source_coverage` 和可选 `source_context`。
- **授权界面**：同一次 Report 响应产生的 GitHub、Email、Calendar Auth Card 在原
  assistant message 内按到达顺序并存；后续授权状态和 Report Download Card 不覆盖先前 UI。
- **实时进度**：授权检查完成后，Web Chat 持续显示 GitHub context、活动检索、详情补充、
  Email、Calendar 与 Markdown rendering 的结构化进度。已知总量显示真实
  `current / total`，未知总量只显示 indeterminate 状态和已发现数量。进度面板位于同一
  assistant message 的 Auth Card 下方，不覆盖既有 UI；`report_ready` 或 stream 终止后
  面板消失，进度内容不进入对话正文或 Conversation history。
- **安全边界**：public tool schema、warning、SSE、日志和 tool result 均不得包含
  access token、PAT、API key、AK/SK、STS credential 或签名 header。

---

## 4. 认证与授权

### 4.1 用户登录（Inbound）

当前 Web Chat 的 Inbound contract 固定为 Microsoft Entra ID + AgentArts Gateway `CUSTOM_JWT`：

| 认证方式 | 当前状态 | 说明 |
|----------|----------|------|
| **CUSTOM_JWT / Microsoft Entra ID** | 已实现 | Gateway 校验 JWT，Service 从已验证 token 的 `sub` 派生 Conversation owner |
| **IAM** | 未接入当前 Web Chat contract | 平台支持，但 Service 当前 ownership contract 要求 Bearer JWT `sub` |
| **API Key** | 非当前 Service 调用路径 | AgentArts 配置保留开发 key，但 `/invocations` 仍要求 Bearer JWT |

### 4.2 服务委托（Outbound）

用户可授权 Agent 以自身身份访问外部服务：

| 委托模式 | 说明 | 典型场景 |
|----------|------|----------|
| **User Federation** | Agent 以用户身份调用外部 API | 查询 Outlook 邮件、发送邮件 |

用户凭证始终由 Identity Service 管理，Agent 代码不会接触原始凭证（如密码或长期 Token）。

### 4.3 认证矩阵

| 用户身份 | Inbound 方式 | Outbound 目标 | Outbound 方式 | Auth Flow |
|----------|-------------|---------------|---------------|-----------|
| Microsoft 用户 | Gateway-validated Entra ID JWT | Microsoft Graph Mail / Calendar | OAuth 2.0 | USER_FEDERATION |
| Microsoft 用户 | Gateway-validated Entra ID JWT | GitHub / Gitee | OAuth 2.0 | USER_FEDERATION |
| Microsoft 用户 | Gateway-validated Entra ID JWT | Huawei Cloud IAM | STS temporary credential | STS Provider |

---

## 5. 对话交互

### 5.1 对话流程

图类型：**Sequence Diagram（时序图）**。用于说明 Conversation-aware Invocation、持久化、Agent Tool loop 与 SSE 完成顺序。

```mermaid
sequenceDiagram
    actor User as 用户
    participant Web as Web Chat
    participant BFF as Cloudflare Pages BFF
    participant API as FastAPI / InvocationService
    participant DB as PostgreSQL
    participant Agent as deepagents / LangGraph
    participant Tool as Registered Tool

    User->>Web: 发送消息
    opt 本地 draft 尚无 conversation_id
        Web->>BFF: POST /api/conversations
        BFF->>API: 经 Gateway 转发
        API->>DB: 创建 user-owned Conversation
        DB-->>API: conversation_id
        API-->>BFF: Conversation response
        BFF-->>Web: conversation_id
    end
    Web->>BFF: POST /invocations<br/>conversation_id + client_message_id + stream=true
    BFF->>API: 经 Gateway 转发 JWT + Runtime Session
    API->>DB: ownership check + lock + persist user message
    API->>Agent: thread_id=user_id:conversation_id
    loop 模型需要调用 Tool
        Agent->>Tool: business arguments
        Tool-->>Agent: authorized result / Auth Card event
    end
    Agent-->>API: token / custom events / final response
    API-->>BFF: SSE token / custom events
    BFF-->>Web: 流式透传
    API->>DB: persist assistant message + commit
    API-->>BFF: done=true
    BFF-->>Web: done=true
    Web-->>User: 展示最终答复
```

### 5.2 典型对话示例

**场景一：收件箱摘要**

```
用户: 帮我看看最近有什么重要邮件
Agent: 你最近有 3 封未读邮件：
      1. 张三 — "项目进度同步"（标记为重要）
      2. HR — "年中绩效评估通知"
      3. 李四 — "周五午餐"
      需要我帮你查看哪一封的详细内容？
```

**场景二：草拟回复**

```
用户: 帮张三回一封邮件，告诉他项目 demo 安排在 7 月 10 号下午
Agent: 草拟如下：

      收件人：张三
      主题：Re: 项目进度同步
      正文：Hi 张三，项目 demo 安排在 7 月 10 日下午，具体时间我再确认后同步你。
      
      需要修改或直接发送吗？
```

---

## 6. LLM Provider 管理

系统通过 typed `Settings` 和 internal Provider catalog 解析 LLM 配置。`.env.example` 是唯一面向使用者的配置目录；LLM API Key 由 AgentArts Identity API Key Credential Provider 注入，不写入 `.env` 或镜像。当前 catalog 只注册 `deepseek`。

### 6.1 Provider 切换场景

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | `deepseek` | 必须存在于 internal Provider catalog |
| `LLM_MODEL` | `deepseek-v4-pro` | 传给 OpenAI-compatible model adapter 的模型名 |
| `LLM_BASE_URL` | Provider catalog endpoint | 可选 endpoint override |
| `LLM_CREDENTIAL_PROVIDER` | `DEEPSEEK_API_KEY` | AgentArts Identity Provider 引用，不是 Secret 本身 |

### 6.2 配置方式

详见 [ADR-011](../architecture/ADR/ADR-011-multi-llm-provider.md)、
[`app/settings.py`](../../personal-assistant-service/app/settings.py) 和
[`app/provider_catalog.py`](../../personal-assistant-service/app/provider_catalog.py)。

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-pro
LLM_CREDENTIAL_PROVIDER=DEEPSEEK_API_KEY
```

---

## 7. 核心验证点

| 验证项 | 说明 |
|--------|------|
| **Inbound Auth** | AgentArts Gateway 校验 Microsoft Entra ID `CUSTOM_JWT`，Service 从已验证 token 的 `sub` 派生用户 |
| **Conversation Isolation** | 同一用户同一 Conversation 多轮连续；不同用户或不同 Conversation 不串扰；Runtime Session 不参与 ownership |
| **Outbound Auth (User Federation)** | Agent 以用户委托身份调用 Microsoft 365、GitHub、Gitee 等外部 API |
| **Calendar OAuth2 Full Flow** | Calendar 授权 callback 由 Service 完成 `complete_resource_token_auth` |
| **STS 云凭证** | Agent 使用 `iam-users-readonly` STS Provider 只读查询华为云 IAM 用户 |
| **Report Root Capability** | 未传 `sources` 时聚合 GitHub、Email、Calendar；单个 source 失败仍返回 deterministic Markdown 与 warning |
| **Chat Loop** | 多轮对话 + 工具调用 + 流式响应 |
| **Guard** | 发送邮件、回复邮件、GitHub star 等写操作需用户确认 |

---

## 8. 开发计划

| Phase | 内容 | 验证点 |
|-------|------|--------|
| **Phase 1** | 搭建 Agent 骨架：LangGraph chat loop + 本地开发环境 | 本地对话通 |
| **Phase 2** | 配置 Inbound Identity：Microsoft Entra ID `CUSTOM_JWT` | Gateway 校验 JWT，Service 使用 `sub` 作为 canonical user identity |
| **Phase 3** | 实现 Conversation Checkpoint | `thread_id=user_id:conversation_id`，跨用户和跨 Conversation 隔离 |
| **Phase 4** | 实现 Outbound OAuth2 User Federation Tools | 邮件、日历、GitHub、Gitee 以用户身份访问 |
| **Phase 5** | 实现 STS 云资源只读 Tool | 使用短期 STS 查询华为云 IAM 用户 |
| **Phase 6** | Web Chat 前端：Vite + React + SSE 流式对话 + OAuth 登录 | 浏览器完整对话体验 |
| **Phase 7** | 部署上线 + 全链路可观测 | 生产可用 |
| **Roadmap** | AgentArts Memory、飞书直连、OfficeClaw | 跨 Session 长期记忆与更多客户端渠道 |
