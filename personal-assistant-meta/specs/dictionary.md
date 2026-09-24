# Personal Assistant — 领域词典

> 版本：v0.2 | 最后核对：2026-09-24 | 用途：项目业务术语统一，避免歧义或重复查询
>
> 本文不解释通用技术概念（如 HTTP、JSON），仅收录本项目语境下有特定含义的术语。

---

## 1. 项目与产品

| 术语 | 定义 |
|------|------|
| **Personal Assistant (PA)** | 本项目的代号。一个基于 AgentArts 平台的对话式 AI 助手，通过自然语言管理邮件、日历、代码仓库并生成工作报表；当前具备持久化 Conversation、LangGraph Checkpoint 和用户委托能力，跨 Conversation 长期 Memory 属于 roadmap |

---

## 2. AgentArts 平台术语

| 术语 | 定义 | 别称 / 易混淆点 |
|------|------|-----------------|
| **AgentArts** | 华为云智能体开发平台（智果）。提供 Runtime（部署）、Memory（记忆）、Identity（认证）、Sandbox（代码执行）、MCP Gateway（工具网关）等 Agent 基础设施 | 原名 "华为云高代码智能体开发平台" |
| **AgentArts Runtime** | AgentArts 的容器化部署服务。把你的代码打包成 ARM64 Docker 镜像并运行在 cn-southwest-2 区域 | **≠ Sandbox**。Runtime 是常驻容器，里面跑你的业务代码 |
| **AgentArts Runtime 容器** | 指 Runtime 服务为你启动的那个容器实例。对外暴露 `:8080`，需要提供 `/ping` 和 `/invocations` | 架构图上写的 "AgentArts 容器" 就是指这个 |
| **AgentArts Sandbox** | 平台提供的隔离代码执行服务；当前 PA 未接入 | **≠ Runtime 容器**。Sandbox 是可选平台能力，Runtime 是当前业务宿主 |
| **AgentArts Memory** | 平台的记忆管理服务；当前 PA 未接入，不能与 Conversation Message 或 LangGraph Checkpoint 混用 | "Memory Service"；当前为 roadmap |
| **AgentArts Identity** | 平台的身份认证服务。管理 Inbound（用户→Agent）和 Outbound（Agent→外部服务）的认证凭据 | "Identity Service" |
| **AgentArts MCP Gateway** | 平台的工具网关服务。将 OpenAPI 定义自动转换为 MCP Tool，供 Agent 的 LLM 调用 | "MCP Gateway" |

### 2.1 Memory 子概念（平台能力 / Roadmap）

| 术语 | 定义 |
|------|------|
| **Memory Space** | AgentArts Memory 的租户级记忆隔离单元；当前 PA 未创建或使用 |
| **Memory Session** | AgentArts Memory 的会话概念；不等同于 BFF Runtime Session 或 PA Conversation |
| **Semantic Memory（语义记忆）** | 知识/事实类长期记忆。如"Python 3.12 支持 PEP 695" |
| **Preference Memory（偏好记忆）** | 用户习惯类长期记忆。如"用户喜欢简洁的回答风格" |
| **Episodic Memory（情景记忆）** | 历史对话摘要类长期记忆。如"上次讨论过 GitHub Actions 配置问题" |
| **Actor** | AgentArts Memory 中的身份概念；当前 PA 尚未建立 actor_id contract |

### 2.2 Identity 子概念

| 术语 | 定义 |
|------|------|
| **Inbound 认证** | 用户 → Agent 的身份验证。平台支持 Custom JWT、IAM 和 API Key；当前 PA production contract 只使用 Microsoft Entra ID `CUSTOM_JWT`，Service 从 Gateway 已验证 token 的 `sub` 派生用户 |
| **Outbound 认证** | Agent → 外部服务的身份验证。Agent 拿到凭据后代表用户（或自身）调用外部 API |
| **User Federation** | Outbound 模式之一。Agent 以**用户身份**调用外部 API（如查 GitHub Issues）。底层走 OAuth2，用户需完成一次授权 |
| **M2M (Machine-to-Machine)** | Outbound 模式之一。Agent 以**自身服务身份**调用 API（如企业内部 CRM）。底层走 API Key |
| **STS Token** | Outbound 模式之一。Agent 获取**云资源临时凭证**；当前 `iam-users-readonly` Provider 为 HuaweiCloud IAM 只读 Tool 提供 STS 凭据 |
| **Credential Provider** | Identity Service 中配置的凭据提供方。当前包括 `github-provider`、`gitee-provider`、`m365-email-provider`、`m365-calendar-provider`、`DEEPSEEK_API_KEY`、`iam-users-readonly` 和 `github-mcp-gateway` |
| **Microsoft 365 Provider** | 邮件和日历使用独立的 OAuth2 Provider：`m365-email-provider` 与 `m365-calendar-provider`；两者均以 User Federation 模式调用 Microsoft Graph |
| **Workload Identity** | Agent 在 Identity Service 中的工作负载身份标识 |
| **Workload Access Token** | AgentArts Gateway 在 production 转发请求时注入的短期凭证（header: `X-HW-AgentGateway-Workload-Access-Token`）。容器提取后存入 `AgentArtsRuntimeContext`，供 Identity SDK 使用；本地 Calendar full flow 可用已验证 JWT 通过专用 Workload Identity 交换 WAT |<!-- updated by issue: chore-8-sync-spec-diagrams-with-implementation -->
| **GitHub MCP Activity Data Source** | Service 工程活动数据源。通过 AgentArts MCP Gateway 调用 GitHub remote MCP，查询 `commit`、`pull_request`、`issue`、`review`、`comment` 五类活动。四个 `github_mcp_*` internal source 供 Report 等内部编排直接复用且不注册为 Agent Tool；Agent 只调用 `github_search_activity` 和 `github_get_activity_detail`，不能调用 raw MCP passthrough。Agent-facing activity tools 的 `identity_scope` 固定为 `platform`；Report 使用该 source 时会显式传入 OAuth `subject_login=A` 和仓库 allowlist，MCP 仅作为 `data_access_identity=platform_mcp` 读取通道 |
| **GitHubActivityEvent** | GitHub MCP Activity Data Source 输出的统一活动事件模型。字段包括 `provider`、`event_type`、`repository`、`external_id`、`title`、`parent_external_id`、`url`、`actor`、`state`、`created_at`、`updated_at`、`summary`、`metrics`、`details`。其中 review/comment 使用 `parent_external_id` 记录所属 PR 或 Issue number，`details` 保存详情查询得到的结构化扩展数据 |
| **Guard 机制** | 敏感操作（如发送邮件）的二次确认机制，防止 LLM 幻觉导致误操作。**当前实现（Feature 10a）**：Text-based Conversation Guard — Agent 先在对话中生成操作预览（收件人、主题、正文），仅在用户给出明确的肯定回复（如"发送"、"确认"）后，才在后续 ReAct loop 中调用 `send_email` 或 `reply_to_email` 工具执行写操作。`send_email` 和 `reply_to_email` 工具直接调用 Microsoft Graph API 执行实际操作。**Planned Enhancement**：Tool-level interrupt — `requires_confirmation=True` 标记，由 LangGraph `interrupt()` 暂停 graph 执行等待用户确认后 resume，提供更强的安全保证和更少的 token 消耗 |
| **system_message (SSE Event)** | SSE 流中的带外系统消息事件类型。由 tool callback（如 `handle_auth_url`）通过 LangGraph `get_stream_writer()` 写入 custom stream，再由后端转成 named SSE event。用于在 LLM token stream 之外向用户呈现 OAuth2 鉴权 URL 等系统消息，不经过 LLM 转述。SSE payload: `{"system_message": "...", "auth_url": "...", "auth_required": true}` |
| **LangGraph Custom Stream（带外消息投递）** | Tool callback 通过 `get_stream_writer()` 写入 custom event，`handle_stream` 将其转为 `auth_card` SSE event。用于解决 `on_auth_url` callback 运行在 tool/SDK 控制流内、需要直接向用户推送 AuthCard 的架构约束。详见 [backend_architecture.md §5.2.1](../architecture/backend_architecture.md#521-oauth2-鉴权-url-呈现out-of-band-消息投递) |

---

## 3. 客户端渠道

| 术语 | 定义 |
|------|------|
| **Web Chat** | 当前唯一 production 产品入口。React SPA 通过 Cloudflare Pages Functions BFF、AgentArts Gateway 调用 FastAPI，使用 SSE 流式对话和 Microsoft Entra ID 登录 |
| **飞书直连** | Roadmap channel；当前仓库没有 `/feishu/webhook` route 或 Bot adapter |
| **OfficeClaw** | Roadmap channel；当前仓库没有可用 OfficeClaw client 或 Service adapter |

---

## 4. LLM 相关

| 术语 | 定义 |
|------|------|
| **LLM Provider** | LLM 推理服务提供方。当前通过 typed `Settings` 的 `LLM_PROVIDER` 选择 internal Provider catalog entry |
| **Provider Catalog** | `app/provider_catalog.py` 中受代码 review 的 endpoint / protocol metadata；当前只注册 `deepseek` |
| **DeepSeek 官方** | 当前 catalog 中的 OpenAI-compatible endpoint `https://api.deepseek.com` |
| **DeepSeek-V4-Pro** | 当前 `LLM_MODEL` 默认值；模型可用性由所选 Provider endpoint 决定 |
| **Provider 配置** | `.env.example` 是唯一使用者配置目录，使用 `LLM_PROVIDER`、`LLM_MODEL`、可选 `LLM_BASE_URL` 和 `LLM_CREDENTIAL_PROVIDER` |
| **LLM Credential Provider** | `LLM_CREDENTIAL_PROVIDER` 是 AgentArts Identity API Key Provider 引用；真实 API Key 不写入 `.env`、代码或镜像 |

---

## 5. Agent 编排

| 术语 | 定义 |
|------|------|
| **ReAct Loop** | Agent 的核心推理模式：LLM 推理 → 决定调工具 or 直接回答 → 执行工具 → 结果喂回 LLM → 继续推理，直到不需要工具 |
| **deepagents** | 当前 Agent factory。`create_deep_agent` 负责模型 / Tool loop，并使用 LangGraph Checkpointer 保存 thread state |
| **LangGraph** | deepagents 底层编排与 Checkpoint framework；当前没有项目自定义的 `AgentState` 或 `finalize` node |
| **LangGraph Checkpoint** | Conversation 内的短期 Agent thread state，key 为 `user_id:conversation_id`；不等同于 AgentArts Memory |

---

## 6. 工具与集成

| 术语 | 定义 |
|------|------|
| **Email Tools** | Agent 以 User Federation 模式调用 Microsoft Graph API 处理邮件。包含列表、详情、搜索、发送和回复，通过 `m365-email-provider` 注入凭据；写操作受 Conversation Guard 保护 |
| **Calendar Tools** | Agent 通过 `m365-calendar-provider` 以 User Federation 模式只读访问 Microsoft 365 Calendar，支持列表、详情和搜索，并实现 Service-owned OAuth2 full flow |
| **GitHub Tools** | Agent 以 User Federation 模式调用 GitHub API，支持仓库列表、目录、文件、代码搜索和带确认的 star |
| **GitHub MCP Activity Source** | Service internal data source，使用 AgentArts MCP Gateway + GitHub remote MCP 读取 GitHub 工程活动。与 GitHub Tools 不同，它不直接使用当前用户 OAuth token 访问 remote MCP。Agent-facing surface 仅包含 `github_search_activity` 和 `github_get_activity_detail`，所有返回结果固定包含 `identity_scope="platform"`；只有 `GITHUB_MCP_ENABLED` 与 `GITHUB_ACTIVITY_TOOLS_ENABLED` 同时为 `true` 时才注册这两个 Tool。Report 作为特殊内部消费者，会先用 GitHub OAuth 确认 `subject_login=A` 和 `repository_scope=oauth_accessible`，再以 `actor=A` 调用该 source |
| **Report Root Capability** | 面向日报、周报、月报、工作总结和研发进展总结的 Agent root capability，对外入口为 `generate_report`。用户给出单个日期时通过 `reference_date` 锚定对应自然周期，给出范围时严格使用 `start_at` / `end_at`；显式日期优先于当前日期。未传 `sources` 时默认编排 GitHub、Email、Calendar；Email 默认覆盖 `inbox` 与 `sentitems`。GitHub 默认先通过 OAuth `/user` 确认主体账号 A 并枚举 A 可访问仓库，再通过 Feature 17 MCP source 以 `actor=A` 读取 A 自己的工程活动，不回退到 platform actor / repository discovery。该能力负责时间窗口解析、证据归一化、partial failure 降级和 deterministic Markdown 渲染，不依赖 Agent 临时串联 low-level tools |
| **ReportEvidence** | Report 的统一证据模型。字段包括 `source`、`source_id`、`title`、`occurred_at`、`summary`、可选 `url` 和 source-specific `metadata`。Email、Calendar、GitHub 原始数据必须先归一化为该模型后才能进入报表正文 |
| **ReportResult** | `generate_report` 的结构化结果。包含 `report_type`、规范化 `window`、deterministic Markdown `content`、`ReportEvidence[]`、脱敏 `warnings`、`source_coverage` 与可选 `source_context`。coverage 按 source 使用 `ok`、`partial`、`unavailable`、`skipped`，单个 source 失败不等于整个 Report 失败 |
| **Internal Tools** | 平台级能力分类：Agent 可通过 M2M 模式调用企业内部 API；当前 PA 尚未实现 CRM/OA 等 Internal Tool |
| **Cloud Tools** | Agent 以 STS 模式访问华为云资源；当前实现仅包含通过 `iam-users-readonly` Provider 查询 IAM 用户的只读 Tool |
| **Guard Check** | 敏感操作二次确认机制。当前为 Text-based Conversation Guard（Agent 展示草稿 → 用户回复确认 → Agent 执行），详见 §2.2 `Guard 机制` |

---

## 7. 部署与运维

| 术语 | 定义 |
|------|------|
| **agentarts launch** | AgentArts CLI 命令。一键构建 ARM64 镜像、推送到 SWR、部署到 Runtime |
| **agentarts dev** | AgentArts CLI 本地开发命令 |
| **SWR** | 华为云容器镜像服务。AgentArts 用它存储构建好的镜像 |
| **cn-southwest-2** | 部署 Region。AgentArts 当前唯一支持的 Region（西南贵阳一） |
| **ARM64** | AgentArts Runtime 唯一支持的 CPU 架构。Docker 镜像必须构建为 `linux/arm64` |
