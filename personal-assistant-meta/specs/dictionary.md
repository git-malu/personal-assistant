# Personal Assistant — 领域词典

> 版本：v0.1 | 用途：项目业务术语统一，避免歧义或重复查询
>
> 本文不解释通用技术概念（如 HTTP、JSON），仅收录本项目语境下有特定含义的术语。

---

## 1. 项目与产品

| 术语 | 定义 |
|------|------|
| **Personal Assistant (PA)** | 本项目的代号。一个基于 AgentArts 平台的对话式 AI 助手，通过自然语言帮用户管理日程、邮件、笔记、任务，具备跨 Session 记忆和用户委托能力 |

---

## 2. AgentArts 平台术语

| 术语 | 定义 | 别称 / 易混淆点 |
|------|------|-----------------|
| **AgentArts** | 华为云智能体开发平台（智果）。提供 Runtime（部署）、Memory（记忆）、Identity（认证）、Sandbox（代码执行）、MCP Gateway（工具网关）等 Agent 基础设施 | 原名 "华为云高代码智能体开发平台" |
| **AgentArts Runtime** | AgentArts 的容器化部署服务。把你的代码打包成 ARM64 Docker 镜像并运行在 cn-southwest-2 区域 | **≠ Sandbox**。Runtime 是常驻容器，里面跑你的业务代码 |
| **AgentArts Runtime 容器** | 指 Runtime 服务为你启动的那个容器实例。对外暴露 `:8080`，需要提供 `/ping` 和 `/invocations` | 架构图上写的 "AgentArts 容器" 就是指这个 |
| **AgentArts Sandbox** | 平台提供的**隔离代码执行服务**。Agent 需要执行不受信任的代码时，发给 Sandbox 临时执行后销毁。每次调用是一次性的 | **≠ Runtime 容器**。Sandbox 是工具（用完就扔），Runtime 是宿主（常驻运行）。不是容器，是云 API |
| **AgentArts Memory** | 平台的记忆管理服务。提供短期对话记忆 + 长期语义/偏好/情景记忆的自动抽取和检索 | "Memory Service" |
| **AgentArts Identity** | 平台的身份认证服务。管理 Inbound（用户→Agent）和 Outbound（Agent→外部服务）的认证凭据 | "Identity Service" |
| **AgentArts MCP Gateway** | 平台的工具网关服务。将 OpenAPI 定义自动转换为 MCP Tool，供 Agent 的 LLM 调用 | "MCP Gateway" |

### 2.1 Memory 子概念

| 术语 | 定义 |
|------|------|
| **Memory Space** | 租户级记忆隔离单元。一个 PA 实例对应一个 Space。创建 Space 后获得 Space ID |
| **Memory Session** | 一次对话会话。关联特定用户（actor_id）和助手（assistant_id） |
| **Semantic Memory（语义记忆）** | 知识/事实类长期记忆。如"Python 3.12 支持 PEP 695" |
| **Preference Memory（偏好记忆）** | 用户习惯类长期记忆。如"用户喜欢简洁的回答风格" |
| **Episodic Memory（情景记忆）** | 历史对话摘要类长期记忆。如"上次讨论过 GitHub Actions 配置问题" |
| **Actor** | Memory 中的身份概念。actor_id=pa-user-{user_id}，区分不同用户 |

### 2.2 Identity 子概念

| 术语 | 定义 |
|------|------|
| **Inbound 认证** | 用户 → Agent 的身份验证。支持三种：Custom JWT（Microsoft Entra ID / Okta）、IAM（华为云账号）、API Key（开发调试） |
| **Outbound 认证** | Agent → 外部服务的身份验证。Agent 拿到凭据后代表用户（或自身）调用外部 API |
| **User Federation** | Outbound 模式之一。Agent 以**用户身份**调用外部 API（如查 GitHub Issues）。底层走 OAuth2，用户需完成一次授权 |
| **M2M (Machine-to-Machine)** | Outbound 模式之一。Agent 以**自身服务身份**调用 API（如企业内部 CRM）。底层走 API Key |
| **STS Token** | Outbound 模式之一。Agent 获取**云资源临时凭证**（如访问 OBS）。底层走华为云 STS |
| **Credential Provider** | Identity Service 中配置的凭据提供方。如 `github-provider`（OAuth2）、`internal-api-provider`（API Key） |
| **Workload Identity** | Agent 在 Identity Service 中的工作负载身份标识 |

---

## 3. 客户端渠道

| 术语 | 定义 |
|------|------|
| **Web Chat** | 浏览器直连的聊天界面。通过 SSE 实现流式对话，通过 Microsoft Entra ID 登录 |
| **飞书直连** | 自行创建飞书 Bot，飞书服务器通过 Webhook 回调到 PA 后端的 `/feishu/webhook` |
| **OfficeClaw** | 运行在 Windows PC 上的桌面客户端，桥接飞书/微信。通过 AgentArts 平台转发调用 PA 的 `/invocations` |

---

## 4. LLM 相关

| 术语 | 定义 |
|------|------|
| **LLM Provider** | LLM 推理服务提供方。本项目通过 `config.yaml` 管理多个 provider，运行时按名称选取 |
| **MaaS** | 华为云 ModelArts as a Service。大模型即服务平台，提供模型广场、一键部署、API 调用。本项目默认 provider |
| **DeepSeek 官方** | DeepSeek 官方 API（`api.deepseek.com`）。本项目备选 provider，公网可达，用于无 VPN 开发或低成本任务 |
| **DeepSeek-V4-Pro** | MaaS 上的默认模型。1.6T 参数 / 49B 激活 / 1M 上下文 |
| **DeepSeek-Chat** | DeepSeek 官方 API 的通用对话模型 |
| **Provider 配置** | 通过 `config.yaml` 的 `llm.providers` 段管理，每个 provider 包含 `base_url`、`api_key_env`（环境变量引用）、`model` |
| **Provider 切换** | 修改 `config.yaml` 的 `llm.default` 字段值，重启后生效。不需要改代码 |
| **`api_key_env`** | Provider 配置中的密钥引用字段。存储环境变量名而非密钥明文，由 `app/llm_config.py` 在运行时通过 `os.environ` 读取 |

---

## 5. Agent 编排

| 术语 | 定义 |
|------|------|
| **ReAct Loop** | Agent 的核心推理模式：LLM 推理 → 决定调工具 or 直接回答 → 执行工具 → 结果喂回 LLM → 继续推理，直到不需要工具 |
| **LangGraph** | 本项目的 Agent 编排框架。用 StateGraph 定义 agent → tools → finalize 的状态流转 |
| **AgentState** | LangGraph 中的状态对象，包含 `messages`（对话历史）、`query`（当前请求）、`context`（Memory 上下文） |
| **ToolNode** | LangGraph 中执行工具调用的节点。收到 LLM 的 tool_calls 后依次执行并返回结果 |
| **Finalize Node** | LangGraph 中的终止节点。保存 Memory 并构建最终响应 |

---

## 6. 工具与集成

| 术语 | 定义 |
|------|------|
| **GitHub Tools** | Agent 以 User Federation 模式调用 GitHub API（查 Issues/PR） |
| **Microsoft 365 Tools** | Agent 以 User Federation 模式调用 Microsoft 365 API（Outlook/Calendar） |
| **Internal Tools** | Agent 以 M2M 模式调用企业内部 API（CRM/OA 等） |
| **Cloud Tools** | Agent 以 STS 模式访问华为云资源（OBS/RDS 等） |
| **Guard Check** | 敏感操作（如发送邮件）的二次确认机制，防止 Agent 误操作 |

---

## 7. 部署与运维

| 术语 | 定义 |
|------|------|
| **agentarts launch** | AgentArts CLI 命令。一键构建 ARM64 镜像、推送到 SWR、部署到 Runtime |
| **agentarts dev** | AgentArts CLI 本地开发命令 |
| **SWR** | 华为云容器镜像服务。AgentArts 用它存储构建好的镜像 |
| **cn-southwest-2** | 部署 Region。AgentArts 当前唯一支持的 Region（西南贵阳一） |
| **ARM64** | AgentArts Runtime 唯一支持的 CPU 架构。Docker 镜像必须构建为 `linux/arm64` |
