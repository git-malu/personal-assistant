# Personal Assistant — 总体架构设计

> 版本：v0.3 | 状态：Draft | 基于 AgentArts 平台

---

## 1. 架构总览

### 1.1 整体架构

```mermaid
flowchart TB
    subgraph Frontends["🖥️ 前端（详见 frontend_architecture.md）"]
        direction LR
        WebChat["Web Chat<br/>Cloudflare Pages"]
        Feishu["飞书直连<br/>自定义 Bot"]
        OC["OfficeClaw<br/>桌面客户端"]
    end

    PagesFunction["Cloudflare Pages Function<br/>/invocations"]

    subgraph AgentArts["AgentArts 平台 (cn-southwest-2)"]
        APIGW["API Gateway<br/>defaultgw-xxx...<br/>JWT 认证<br/>PREFIX_MATCH: /invocations/*"]
        subgraph Container["容器 :8080"]
            Routes["FastAPI 路由层<br/>/ping /invocations<br/>/invocations/playground（调试）"]
            Handler["Agent 处理逻辑<br/>deepagents 编排"]
            SDK["agentarts-sdk<br/>Memory / Identity / Sandbox"]
        end
        MemorySvc["Memory Service"]
        IdentitySvc["Identity Service"]
        SandboxSvc["Sandbox Service"]
        MCPGW["MCP Gateway<br/>API → MCP Tool 转换"]
    end

    subgraph External["外部服务"]
        Microsoft365API["Microsoft 365 APIs"]
        GitHubAPI["GitHub API"]
        InternalAPI["企业内部 API"]
    end

    WebChat -->|"/invocations"| PagesFunction
    PagesFunction -->|"JWT + SSE<br/>full Runtime path"| APIGW
    Feishu -->|"/invocations"| APIGW
    OC -->|"/invocations"| APIGW
    APIGW -->|"转发"| Routes
    Routes --> Handler
    Handler --> SDK
    SDK --> MemorySvc
    SDK --> IdentitySvc
    SDK --> SandboxSvc
    Handler --> MCPGW --> External
    IdentitySvc --> External
```

**架构层级**：

| 层 | 负责 | 详细文档 |
|----|------|----------|
| **前端** | Cloudflare Pages 静态站点、Pages Function Proxy、消息通道 | `frontend_architecture.md` |
| **API Gateway** | JWT 认证、`PREFIX_MATCH` 路由转发（`/invocations` 及其子路径） | `cloud-service/agentarts.md` §9 |
| **后端（容器）** | FastAPI 路由 + Agent 处理逻辑 | `backend_architecture.md` |
| **Session 状态** | 短期会话状态持久化（Checkpoint）+ 长期记忆（Memory） | `session-state-management.md` |
| **平台服务** | AgentArts Memory / Identity / Sandbox / MCP Gateway | `cloud-service/agentarts.md` |
| **Cloudflare Pages** | Production hosting、Pages Function Proxy、Wrangler CLI | [`cloud-service/cloudflare/pages.md`](cloud-service/cloudflare/pages.md) |

### 1.2 技术选型

| 层级 | 选型 | 说明 |
|------|------|------|
| **Web 框架** | FastAPI | 统一管理所有路由，替代 AgentArtsRuntimeApp。详见 [ADR-004](ADR/ADR-004-fastapi-over-agentarts-runtime-app.md) |
| **Agent 编排** | deepagents (LangChain) | LangGraph 之上的 batteries-included harness，封装 ReAct loop + summarization + skills。详见 [ADR-009](ADR/ADR-009-deepagents.md) |
| **Session State** | LangGraph Checkpoint | 短期会话状态持久化，keyed by `thread_id`，支持单 Session 多轮上下文保持和中断恢复。详见 [session-state-management.md](session-state-management.md) |
| **Conversation** | PostgreSQL + Cloudflare Pages Functions BFF | durable Conversation metadata、UI message read model、user-scoped Runtime lease 与 same-origin API；`conversation_id` 与 LangGraph `thread_id` 1:1 |
| **LLM** | typed Settings + internal Provider catalog | `.env.example` 是唯一配置目录；Pydantic Settings 校验 Runtime 参数，credential 由 AgentArts Identity 提供。详见 ADR-011 |
| **Runtime** | AgentArts Runtime | 容器化部署，ARM64 架构，cn-southwest-2 区域。详见 [ADR-003](ADR/ADR-003-agentarts-platform.md) |
| **Memory** | AgentArts Memory SDK | 长期语义/偏好/情景记忆，跨 Session 持久化用户知识。与 Checkpoint 分工：Checkpoint 管短期会话状态，Memory 管长期用户知识。详见 [session-state-management.md](session-state-management.md) §2 |
| **Identity** | AgentArts Identity SDK | Inbound JWT/API Key + Outbound OAuth2/M2M/STS |
| **Gateway** | AgentArts MCP Gateway | API 定义 → MCP Tool 自动转换 |
| **可观测** | OTEL (AgentArts 内置) + stdout structured logging | Tracing + Metrics；Service 使用统一 Uvicorn log config 输出 JSON 并关联 request/session/trace context，见 [ADR-018](ADR/ADR-018-service-structured-logging.md) |
| **Container** | Docker (linux/arm64) | Python 3.12+ |

---

## 2. 前端与后端

架构采用**前后端分离**设计。详细设计见独立文档：

| 文档 | 内容 |
|------|------|
| [`api.md`](api.md) | Web Chat、Cloudflare Pages Function、AgentArts Gateway 与 FastAPI 的 API path 及映射关系 |
| `frontend_architecture.md` | 三种客户端渠道（Web Chat / 飞书直连 / OfficeClaw）、渠道对比、选择指南、部署拓扑 |
| `backend_architecture.md` | FastAPI 路由设计、Agent 处理逻辑、LangGraph 编排、AgentArts SDK 集成、项目结构 |

### 2.1 前后端关系

```mermaid
flowchart LR
    subgraph Frontends["前端（消息通道）"]
        WebChat["Web Chat"]
        Feishu["飞书直连"]
        OC["OfficeClaw"]
    end

    subgraph Backend["后端（FastAPI :8080）"]
        Routes["路由层"]
        Handler["Agent 处理逻辑"]
    end

    WebChat -->|"POST /invocations"| Routes
    Feishu -->|"POST /invocations"| Routes
    OC -->|"AgentArts /invocations"| Routes
    Routes --> Handler
```

**核心原则**：前端只负责消息通道和协议适配，不做 Agent 逻辑。所有 Agent 推理、Memory、Tool 调用都在后端。

---

## 3. 认证流详解

```mermaid
sequenceDiagram
    actor User as 用户
    participant Client as Chat UI
    participant RT as AgentArts Runtime
    participant ID as Identity Service
    participant Agent as Personal Assistant
    participant Ext as External API (GitHub)

    Note over User,Ext: === Inbound 认证（用户 → Agent） ===

    User->>Client: 打开聊天界面
    Client->>RT: POST /invocations<br/>Authorization: Bearer {OAuth2_Access_Token}
    RT->>ID: 验证 JWT/API Key
    ID-->>RT: 验证通过，注入 RequestContext<br/>(包含 user_id, scopes 等)
    RT->>Agent: handler(payload, context)

    Note over User,Ext: === Outbound 认证（Agent → 外部服务） ===

    User->>Agent: "帮我查 GitHub Issues"

    Agent->>ID: get_resource_oauth2_token(<br/>  provider_name="github",<br/>  scopes=["repo", "read:user"],<br/>  agent_identity_token=context.user_token<br/>)
    ID-->>Agent: GitHub Access Token

    Agent->>Ext: GET /repos/{owner}/{repo}/issues<br/>Authorization: Bearer {GitHub_Token}
    Ext-->>Agent: Issues List

    Agent-->>Client: "你当前有 3 个 open issue: ..."
    Client-->>User: 展示结果
```

---

## 4. Identity 设计

### 4.1 Inbound — 用户认证到 Agent

AgentArts Runtime 通过 `agentarts_config.yaml` 中 `runtime.identity_configuration` 配置三种 Inbound 认证方式：

```yaml
runtime:
  identity_configuration:
    authorizer_type: CUSTOM_JWT          # IAM | CUSTOM_JWT | KEY_AUTH
    authorizer_configuration:
      custom_jwt:
        discovery_url: https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration
        allowed_audience:
          - "personal-assistant-client-id"
        allowed_clients:
          - "personal-assistant-client-id"
        allowed_scopes:
          - "openid"
          - "profile"
          - "email"
      key_auth:
        api_keys:
          - "opencode-2026-api-key-xxxxx"       # 开发调试用
```

| 认证方式 | 适用场景 | 配置 |
|----------|----------|------|
| **IAM** | 华为云内部用户（Console / CLI） | `authorizer_type: IAM` |
| **Custom JWT** | 自有 IdP 用户登录（Microsoft Entra ID / Okta / Auth0） | `authorizer_type: CUSTOM_JWT` + `discovery_url` |
| **API Key** | 开发调试 / 机器对机器调用 | `authorizer_type: KEY_AUTH` + `api_keys[]` |

> 推荐生产环境使用 **Custom JWT** 方式，通过 Microsoft Entra ID 或自有 OIDC IdP 提供用户认证。

**Gateway Header 注入**：除用户身份 header（`X-HW-AgentGateway-User-Id`）外，AgentArts Gateway 在转发请求时还会注入 `X-HW-AgentGateway-Workload-Access-Token`——Agent 容器以 Workload Identity 认证 Identity Service 的短期凭证。后端提取该 token 存入 `AgentArtsRuntimeContext` 后，Outbound 认证装饰器（如 `@require_access_token`）可直接使用，无需容器自行从 `.agent_identity.json` 走本地认证流程。详见 [backend_architecture.md §2.3](backend_architecture.md#23-agentarts-gateway-header-注入)。

**OAuth2 鉴权 URL 呈现**：当 `@require_access_token` 的 `on_auth_url` callback 触发时，tool 通过 LangGraph `get_stream_writer()` 将 `auth_required` custom event 写入 SSE stream，Web Chat 使用 provider-scoped Auth Card 直接呈现，不依赖 LLM 转述。授权凭据可用后发送 `auth_complete`，仅更新匹配的 pending Card。详见 [backend_architecture.md §5.2.1](backend_architecture.md#521-oauth2-鉴权-url-呈现out-of-band-消息投递) 和 [frontend_architecture.md §2.1.4](frontend_architecture.md#214-sse-事件协议)。

### 4.2 Outbound — Agent 代表用户调用外部服务

AgentArts Identity SDK 提供三种 Outbound 认证模式：

| 模式 | Auth Flow | 用途 | 典型场景 |
|------|-----------|------|----------|
| **User Federation** | `USER_FEDERATION` | Agent 以用户身份调用外部 API | 查 GitHub Issues、读 Outlook Calendar、查 Microsoft 365 邮件 |
| **M2M** | `M2M` | Agent 以自身服务身份调用 API | 调用企业内部 CRM、OA 系统 |
| **STS Token** | — | Agent 获取云资源访问凭证 | 操作 OBS 对象存储、访问 RDS |

#### 4.2.1 Credential Provider 创建

通过 AgentArts SDK 创建各类 Credential Provider：

```python
from agentarts.sdk import IdentityClient
from agentarts.sdk.identity import OAuth2Vendor

client = IdentityClient(region="cn-southwest-2")

# 1. 创建 Workload Identity（Agent 的工作负载身份）
workload = client.create_workload_identity(
    name="personal-assistant-workload",
    allowed_resource_oauth2_return_urls=["http://localhost:8000/auth/callback"],
)

# 2. OAuth2 Provider — GitHub（User Federation）
github_provider = client.create_oauth2_credential_provider(
    name="github-provider",
    vendor=OAuth2Vendor.GITHUBOAUTH2,
    client_id="your-github-oauth-app-client-id",
    client_secret="your-github-oauth-app-client-secret",
)

# 3. OAuth2 Provider — Microsoft 365（User Federation）
m365_provider = client.create_oauth2_credential_provider(
    name="m365-provider",
    vendor=OAuth2Vendor.MICROSOFTOAUTH2,
    client_id="your-m365-client-id",
    client_secret="your-m365-client-secret",
    tenant_id="your-azure-tenant-id",
)

# 4. API Key Provider — 企业内部 API（M2M）
api_key_provider = client.create_api_key_credential_provider(
    name="internal-api-provider",
    api_key="sk-internal-api-xxxxx"
)

# 5. STS Provider — 云资源（M2M）
sts_provider = client.create_sts_credential_provider(
    name="huaweicloud-sts-provider",
    agency_urn="urn:agency:your-agency",
    tags=[{"key": "env", "value": "prod"}]
)
```

#### 4.2.2 凭据装饰器使用

```python
from agentarts.sdk import require_access_token, require_api_key, require_sts_token
from agentarts.sdk.identity import StsCredentials
from typing import Optional
import httpx

# === User Federation: 以用户身份调用 GitHub ===
@require_access_token(
    provider_name="github-provider",
    scopes=["repo", "read:user"],
    auth_flow="USER_FEDERATION"
)
async def get_github_issues(owner: str, repo: str, access_token: Optional[str] = None):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/issues",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        return resp.json()

# === User Federation: 以用户身份调用 Outlook Calendar ===
@require_access_token(
    provider_name="m365-provider",
    scopes=["https://graph.microsoft.com/Calendars.Read"],
    auth_flow="USER_FEDERATION"
)
async def get_outlook_calendar_events(access_token: Optional[str] = None):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://graph.microsoft.com/v1.0/me/calendar/events",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        return resp.json()

# === M2M: Agent 以自身身份调用企业内部 API ===
@require_api_key(provider_name="internal-api-provider")
def call_internal_crm(query: str, api_key: Optional[str] = None):
    import requests
    resp = requests.get(
        f"https://crm.internal.example.com/api/search?q={query}",
        headers={"X-API-Key": api_key}
    )
    return resp.json()

# === STS: Agent 获取云资源 Token ===
@require_sts_token(
    provider_name="huaweicloud-sts-provider",
    agency_session_name="personal-assistant-session"
)
async def access_obs_file(bucket: str, key: str, sts_credentials: Optional[StsCredentials] = None):
    from obs import ObsClient
    obs_client = ObsClient(
        access_key_id=sts_credentials.access_key_id,
        secret_access_key=sts_credentials.secret_access_key,
        security_token=sts_credentials.security_token,
        server="https://obs.cn-southwest-2.myhuaweicloud.com"
    )
    return obs_client.getObject(bucket, key)
```

---

## 5. Chat Agent 设计

> 详细实现见 `backend_architecture.md` #3、#4。

### 5.1 deepagents 编排

Agent 使用 deepagents 封装标准 ReAct loop，无需手写 StateGraph：

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=model,
    system_prompt="你是 Personal Assistant，负责管理日程、邮件、笔记和任务...",
    tools=[github_tool, calendar_tool],
)
```

deepagents 底层是 LangGraph，内置 ReAct 循环：

```mermaid
stateDiagram-v2
    [*] --> agent: 入口
    agent --> tools: has tool_calls
    agent --> finalize: no tool_calls
    tools --> agent: tool results
    finalize --> [*]
```

核心能力：

- **ReAct loop** — agent 推理 → 工具调用 → 结果反馈 → 继续推理，由 deepagents 内置
- **conversation summarization** — 长对话自动 compact，控制 token 消耗
- **skills 系统** — SKILL.md 文件驱动，按需加载领域知识和工具使用指南

### 5.2 FastAPI 入口（替代 AgentArtsRuntimeApp）

```python
# app/main.py
from fastapi import FastAPI
from app.agent_handler import AgentHandler

app = FastAPI()
handler = AgentHandler()

@app.get("/ping")
async def ping():
    return {"status": "ok"}

@app.post("/invocations")
async def invoke(request: Request):
    payload = await request.json()
    result = await handler.handle(
        message=payload.get("message", ""),
        user_id=request.headers.get("X-AgentArts-User-Id"),
        session_id=request.headers.get("X-AgentArts-Session-Id"),
    )
    return {"response": result}
```

不再使用 `AgentArtsRuntimeApp` 和 `@app.entrypoint`，改用标准 FastAPI 路由。平台层面完全兼容——只要容器在 8080 提供 `/ping`（平台内部健康检查）和 `/invocations`（Gateway 转发入口），并启用 `url_match_type: PREFIX_MATCH` 以支持 `/invocations/*` 子路径。详见 [backend_architecture.md §2.1](backend_architecture.md#21-agentarts-gateway-路由约束)。

### 5.3 Agent 数据流

```mermaid
flowchart LR
    Entry["entrypoint<br/>handler(payload, context)"] --> Agent["deepagents Agent<br/>内置 ReAct loop"]
    Agent -->|"tool_calls"| Tools["工具调用<br/>执行 Identity SDK 装饰的工具"]
    Agent -->|"无 tool_calls"| Response["Dict[str, Any]<br/>{response: '...'}"]
    Tools -->|"tool results"| Agent
```

AgentHandler 直接调用 deepagents 的 `.invoke()` 或 `.astream()`：

```python
class AgentHandler:
    def __init__(self):
        self.checkpointer = self._init_checkpointer()
        self.tools = build_tools()
        self._bundle = None
        self._bundle_lock = asyncio.Lock()

    def _build_agent(self):
        model = get_model()  # canonical Settings + Identity credential
        return create_deep_agent(
            model=model,
            system_prompt="你是 Personal Assistant...",
            tools=self.tools,  # Identity SDK 装饰的工具
            checkpointer=self.checkpointer,
        )

    async def get_agent(self):
        # TTL fast path → single-flight refresh → atomic Bundle swap
        ...

    async def handle(self, message: str, user_id: str) -> str:
        agent = await self.get_agent()
        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": message}],
        })
        return result["messages"][-1].content
```

Model 和 compiled Agent 组成 process-scoped Agent Bundle，在
`LLM_AGENT_BUNDLE_TTL_SECONDS` 内复用。Bundle refresh 不替换共享 Checkpointer，
因此相同 `user_id + session_id` 的 checkpoint 状态连续。

## 6. LLM Provider 配置

> 详细设计见 [ADR-011](ADR/ADR-011-multi-llm-provider.md)。

### 6.1 唯一用户配置入口

Service 的所有可配置项从 `.env.example` 发现。本地复制为 `.env`，生产环境由
AgentArts Runtime 或 CI/CD 注入同名环境变量。`app/settings.py` 使用 Pydantic
Settings 进行类型转换、约束校验和 fail-fast；它是内部代码，不是第二配置入口。

LLM canonical settings 包括 `LLM_PROVIDER`、`LLM_MODEL`、
`LLM_CREDENTIAL_PROVIDER`、`LLM_AGENT_BUNDLE_TTL_SECONDS`、可选
`LLM_BASE_URL` 和 timeout 参数。

### 6.2 Provider metadata 与 Secret

- `app/provider_catalog.py`：随代码 release 的 typed、非敏感 Provider metadata
- `app/llm_config.py`：组合 Settings 与 catalog，暴露 `get_model()`
- AgentArts Identity：保存并注入真实 API Key

`LLM_CREDENTIAL_PROVIDER` 只是 Identity provider name，不是 Secret value。
Service 不从环境变量读取 LLM API Key。

### 6.3 配置加载逻辑

```mermaid
flowchart TD
    Entry[".env.example<br/>唯一配置目录"] --> Local[".env（本地）"]
    Entry --> Runtime["Runtime env（生产）"]
    Local --> Settings["Pydantic Settings"]
    Runtime --> Settings
    Catalog["typed Provider catalog"] --> Resolve["llm_config.get_model"]
    Settings --> Resolve
    Identity["AgentArts Identity API Key"] --> Resolve
    Resolve --> Model["init_chat_model"]
```

环境变量优先于 `.env`，`.env` 优先于字段默认值。Provider 未知、URL 非法或
Persistence 配置冲突时，Service 在 startup 阶段失败。

---

## 7. Memory 集成

### 7.1 Memory 模型

AgentArts Memory 采用分层存储模型：

```mermaid
flowchart TD
    Space["Space（记忆空间）"] --> Session["Session（会话）"]
    Session --> Messages["Messages（消息记录）"]
    Session --> Memories["Memories（抽取的记忆）"]
    Memories --> Semantic["Semantic<br/>语义记忆 — 知识/事实"]
    Memories --> Preference["Preference<br/>偏好记忆 — 用户习惯"]
    Memories --> Episodic["Episodic<br/>情景记忆 — 历史对话摘要"]
```

- **Space**：租户级隔离单元，一个 Personal Assistant 实例对应一个 Space
- **Session**：每次对话会话，关联特定用户
- **Memory**：从 Session 消息中自动抽取的长短期记忆

### 7.2 SDK 集成代码

```python
# app/personal_assistant/memory.py

import os
from agentarts.sdk.memory import MemoryClient
from agentarts.sdk.memory.session import MemorySession
from agentarts.sdk.memory.inner.config import TextMessage, MemorySearchFilter


class PersonalAssistantMemory:
    def __init__(self):
        self.space_id = os.environ.get("MEMORY_SPACE_ID")
        self.actor_prefix = "pa-user-"
        self.assistant_id = "personal-assistant"

    async def get_context(self, state: dict) -> str:
        """获取当前 Session 的 Memory 上下文"""
        user_id = state.get("context", {}).get("user_id", "anonymous")
        if not self.space_id:
            return ""

        session = MemorySession(
            space_id=self.space_id,
            actor_id=f"{self.actor_prefix}{user_id}",
            assistant_id=self.assistant_id
        )

        # 搜索长期记忆中的用户偏好
        results = session.search_long_term_memories(
            filters=MemorySearchFilter(query="user preferences", top_k=5)
        )

        context_parts = []
        for r in results.results:
            record = r.get("record", {})
            context_parts.append(record.get("content", ""))

        return "\n".join(context_parts) if context_parts else ""

    async def save_interaction(self, state: dict, last_message) -> None:
        """保存对话到 Memory"""
        user_id = state.get("context", {}).get("user_id", "anonymous")
        if not self.space_id or not state.get("messages"):
            return

        session = MemorySession(
            space_id=self.space_id,
            actor_id=f"{self.actor_prefix}{user_id}",
            assistant_id=self.assistant_id
        )

        # 提取最后一轮用户-助手消息
        messages = state["messages"]
        turns = []
        for msg in messages[-2:]:
            role = "user" if msg.type == "human" else "assistant"
            turns.append(TextMessage(role=role, content=str(msg.content)[:2000]))
        if turns:
            session.add_messages(turns)
```

---

> Backend 部署见
> [agentarts-deploy-runbook.md](devops/agentarts-deploy-runbook.md)；Frontend
> Cloudflare deployment 见
> [cloudflare/pages.md](cloud-service/cloudflare/pages.md)。

## 8. 部署配置

### 8.1 `agentarts_config.yaml`

```yaml
default_agent: personal-assistant

agents:
  personal-assistant:
    base:
      name: personal-assistant
      entrypoint: agent:app
      dependency_file: requirements.txt
      platform: linux/arm64
      language: python3
      base_image: python:3.12-slim
      region: cn-southwest-2

    swr_config:
      organization: personal-assistant-org
      repository: agent_personal_assistant
      organization_auto_create: true
      repository_auto_create: true

    runtime:
      invoke_config:
        protocol: HTTP
        port: 8080

      network_config:
        network_mode: PUBLIC
        # 如需 VPC 内访问，改为 PRIVATE 并配置 vpc_config

      identity_configuration:
        # === Inbound: Custom JWT (Microsoft Entra ID) ===
        authorizer_type: CUSTOM_JWT
        authorizer_configuration:
          custom_jwt:
            discovery_url: https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration
            allowed_audience:
              - "<your-entra-id-client-id>"
            allowed_clients:
              - "<your-entra-id-client-id>"
            allowed_scopes:
              - "openid"
              - "profile"
              - "email"
          # === Inbound: API Key (开发调试) ===
          key_auth:
            api_keys:
              - "opencode-dev-api-key-2026"

      observability:
        tracing:
          enabled: true
        metrics:
          enabled: true
        logs:
          enabled: true

      artifact_source:
        url: swr.cn-southwest-2.myhuaweicloud.com/personal-assistant-org/agent_personal_assistant:latest
        commands: []

      environment_variables:
        - key: LOG_LEVEL
          value: "${LOG_LEVEL}"
        - key: LLM_PROVIDER
          value: "${LLM_PROVIDER}"
        - key: LLM_MODEL
          value: "${LLM_MODEL}"
        - key: LLM_CREDENTIAL_PROVIDER
          value: "${LLM_CREDENTIAL_PROVIDER}"

      tags:
        - key: app
          value: personal-assistant
        - key: env
          value: dev
```

### 8.2 部署命令

```bash
# 本地开发
agentarts dev

# 部署到云端
agentarts launch

# 调用（API Key 模式）
agentarts invoke '{"message": "帮我查一下我的 GitHub Issues"}'

# 调用（JWT 模式，通过 HTTPS + Bearer Token）
curl -X POST https://<runtime-domain>/invocations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <Microsoft_ID_Token>" \
  -d '{"message": "查一下我的日程"}'
```

---

## 9. 项目文件结构

```
personal-assistant/
├── .agentarts_config.yaml          # AgentArts 部署配置（位于 personal-assistant-service/）
├── Dockerfile                       # ARM64 镜像（位于 personal-assistant-service/）
├── .env.example                     # 唯一面向使用者的 Service 配置入口
├── pyproject.toml                   # Python 依赖 + ruff 配置（位于 personal-assistant-service/）
├── uv.lock                           # 确定性锁文件
├── app/                              # （位于 personal-assistant-service/）
│   ├── main.py                      # FastAPI 应用入口 + 路由定义 ✅ 已实现
│   ├── agent_handler.py             # Agent 处理逻辑（deepagents + ToolNode）✅ 已实现
│   ├── settings.py                  # typed Runtime Settings ✅ 已实现
│   ├── provider_catalog.py          # 内置 Provider metadata ✅ 已实现
│   ├── llm_config.py                # Settings + Identity → LLM model ✅ 已实现
│   ├── auth.py                      # Inbound 认证中间件 ✅ 已实现
│   ├── playground.py                # Chainlit Playground ✅ 已实现
│   ├── memory.py                    # Memory 集成 [Planned — Feature 2]
│   ├── feishu_adapter.py            # 飞书消息解析 + 回复 [Planned — Feature 5]
│   ├── oauth.py                     # OAuth 流程 (Microsoft Entra ID) [已废弃 — Feature 4 改由前端 PKCE]
│   └── tools/                       # 外部工具集成
│       ├── __init__.py              # 工具目录初始化 + ToolNode 工厂 ✅ Feature 10a
│       ├── email_tools.py           # Microsoft 365 邮件工具 (OAuth2 User Federation) ✅ Feature 10a
│       ├── github_tools.py          # GitHub 工具 (OAuth2 User Federation) [Planned — Feature 6]
│       ├── internal_tools.py        # 内部 API 工具 (API Key M2M) [Planned — Feature 7]
│       └── cloud_tools.py           # 云资源工具 (STS M2M) [Planned — Feature 8]
├── personal-assistant-client/        # Web Chat 前端 ✅ 已实现（独立目录，Vite + React + assistant-ui）
│   └── ...
└── README.md
```

> 注：`personal-assistant-service/` 和 `personal-assistant-client/` 为独立子目录，非服务端子目录。标 `[Planned]` 的文件尚未实现，将在对应 Feature 中交付。

---

## 10. Inbound / Outbound 认证矩阵

| 用户身份 | Inbound 方式 | Outbound 目标 | Outbound 方式 | Auth Flow |
|----------|-------------|---------------|---------------|-----------|
| Microsoft 用户 | JWT (Microsoft Entra ID) | Outlook Mail (Microsoft Graph) | OAuth 2.0 | USER_FEDERATION |
| Microsoft 用户 | JWT (Microsoft Entra ID) | GitHub API | OAuth 2.0 | USER_FEDERATION |
| Microsoft 用户 | JWT (Microsoft Entra ID) | Outlook Calendar | OAuth 2.0 | USER_FEDERATION |
| 企业员工 | JWT (Okta/Entra ID) | 内部 CRM | API Key | M2M |
| 运维人员 | JWT (Okta/Entra ID) | 云资源 | STS Token | M2M |
| 开发者 | API Key | _(全部)_ | _(开发调试)_ | — |

---

## 11. 参考文档

| 文档 | 路径 |
|------|------|
| **Microsoft Entra ID (OIDC) 配置** | `architecture/devops/microsoft-entra-id-setup.md` |
| **前端架构** | `architecture/frontend_architecture.md` |
| **后端架构** | `architecture/backend_architecture.md` |
| **Cloudflare Pages 运维** | `architecture/cloud-service/cloudflare/pages.md` |
| AgentArts 平台参考 | `architecture/cloud-service/agentarts.md` |
| AgentCore 对比参考 | `architecture/cloud-service/agentcore.md` |
| Identity SDK 文档 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_044.html` |
| Runtime 部署文档 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_028.html` |
| 认证鉴权 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_047.html` |
| Memory SDK 文档 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_043.html` |
| SDK 快速开始 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_040.html` |
