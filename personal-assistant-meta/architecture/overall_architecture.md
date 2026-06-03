# Personal Assistant — 总体架构设计

> 版本：v0.3 | 状态：Draft | 基于 AgentArts 平台

---

## 1. 架构总览

### 1.1 整体架构

```mermaid
flowchart TB
    subgraph Frontends["🖥️ 前端（详见 frontend_architecture.md）"]
        direction LR
        WebChat["Web Chat<br/>浏览器"]
        Feishu["飞书直连<br/>自定义 Bot"]
        OC["OfficeClaw<br/>桌面客户端"]
    end

    subgraph Backend["☁️ 后端 — FastAPI（详见 backend_architecture.md）"]
        direction LR
        Routes["路由层<br/>/ping /invocations<br/>/feishu/webhook<br/>/auth/callback<br/>/chat/stream"]
        Handler["Agent 处理逻辑<br/>LangGraph 编排"]
        SDK["agentarts-sdk<br/>Memory / Identity / Sandbox"]
    end

    subgraph AgentArts["AgentArts 平台 (cn-southwest-2)"]
        MemorySvc["Memory Service"]
        IdentitySvc["Identity Service"]
        SandboxSvc["Sandbox Service"]
        MCPGW["MCP Gateway"]
    end

    subgraph External["外部服务"]
        GoogleAPI["Google APIs"]
        GitHubAPI["GitHub API"]
        InternalAPI["企业内部 API"]
    end

    WebChat -->|"SSE + OAuth"| Routes
    Feishu -->|"Webhook"| Routes
    OC -->|"AgentArts 转发"| Routes
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
| **前端** | 消息通道、用户交互界面 | `frontend_architecture.md` |
| **后端** | FastAPI 路由 + Agent 处理逻辑 | `backend_architecture.md` |
| **平台** | AgentArts Memory / Identity / Sandbox / MCP Gateway | `cloud-service/agentarts.md` |

### 1.2 技术选型

| 层级 | 选型 | 说明 |
|------|------|------|
| **Web 框架** | FastAPI | 统一管理所有路由，替代 AgentArtsRuntimeApp |
| **Agent 编排** | LangGraph (Python) | 有状态图编排，支持条件路由和工具调用循环 |
| **LLM** | DeepSeek-V3.2 (via MaaS) | OpenAI-compatible API，部署在华为云 |
| **Runtime** | AgentArts Runtime | 容器化部署，ARM64 架构，cn-southwest-2 区域 |
| **Memory** | AgentArts Memory SDK | 短期+长期记忆，语义/偏好/情景三种策略 |
| **Identity** | AgentArts Identity SDK | Inbound JWT/API Key + Outbound OAuth2/M2M/STS |
| **Gateway** | AgentArts MCP Gateway | API 定义 → MCP Tool 自动转换 |
| **可观测** | OTEL (AgentArts 内置) | Tracing + Logging + Metrics |
| **Container** | Docker (linux/arm64) | Python 3.10+ |

---

## 2. 前端与后端

架构采用**前后端分离**设计。详细设计见独立文档：

| 文档 | 内容 |
|------|------|
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

    WebChat -->|"SSE + OAuth"| Routes
    Feishu -->|"Webhook 事件"| Routes
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
        discovery_url: https://accounts.google.com/.well-known/openid-configuration
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
| **Custom JWT** | 自有 IdP 用户登录（Google / Okta / Auth0） | `authorizer_type: CUSTOM_JWT` + `discovery_url` |
| **API Key** | 开发调试 / 机器对机器调用 | `authorizer_type: KEY_AUTH` + `api_keys[]` |

> 推荐生产环境使用 **Custom JWT** 方式，通过 Google OAuth 或自有 OIDC IdP 提供用户认证。

### 4.2 Outbound — Agent 代表用户调用外部服务

AgentArts Identity SDK 提供三种 Outbound 认证模式：

| 模式 | Auth Flow | 用途 | 典型场景 |
|------|-----------|------|----------|
| **User Federation** | `USER_FEDERATION` | Agent 以用户身份调用外部 API | 查 GitHub Issues、发 Gmail、读 Google Calendar |
| **M2M** | `M2M` | Agent 以自身服务身份调用 API | 调用企业内部 CRM、OA 系统 |
| **STS Token** | — | Agent 获取云资源访问凭证 | 操作 OBS 对象存储、访问 RDS |

#### 4.2.1 Credential Provider 创建

通过 AgentArts SDK 创建各类 Credential Provider：

```python
from agentarts.sdk.services.identity import IdentityClient

client = IdentityClient(region="cn-southwest-2")

# 1. 创建 Workload Identity（Agent 的工作负载身份）
workload = client.create_workload_identity(
    name="personal-assistant-workload",
    description="Personal Assistant Agent 工作负载身份"
)

# 2. OAuth2 Provider — GitHub（User Federation）
github_provider = client.create_oauth2_credential_provider(
    name="github-provider",
    vendor="github",
    client_id="your-github-oauth-app-client-id",
    client_secret="your-github-oauth-app-client-secret"
)

# 3. OAuth2 Provider — Google（User Federation）
google_provider = client.create_oauth2_credential_provider(
    name="google-provider",
    vendor="google",
    client_id="your-google-oauth-client-id",
    client_secret="your-google-oauth-client-secret"
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
from agentarts.sdk.identity.types import StsCredentials
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

# === User Federation: 以用户身份调用 Google Calendar ===
@require_access_token(
    provider_name="google-provider",
    scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    auth_flow="USER_FEDERATION"
)
async def get_google_calendar_events(access_token: Optional[str] = None):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
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

### 5.1 LangGraph 编排

Agent 使用 LangGraph StateGraph 实现有状态的对话编排：

```mermaid
stateDiagram-v2
    [*] --> agent: entry_point
    agent --> tools: has tool_calls
    agent --> finalize: no tool_calls
    tools --> agent: tool results
    finalize --> [*]
```

核心节点：

- **agent** — LLM 推理节点：决定是调用工具还是直接回答，注入 Memory 上下文
- **tools** — ToolNode：执行工具调用，返回结果
- **finalize** — 终止节点：保存 Memory，构建最终响应

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

不再使用 `AgentArtsRuntimeApp` 和 `@app.entrypoint`，改用标准 FastAPI 路由。平台层面完全兼容，只要容器在 8080 提供 `/ping` + `/invocations` 即可。

### 5.3 Agent State 数据流

```mermaid
flowchart LR
    Entry["entrypoint<br/>handler(payload, context)"] --> State["AgentState<br/>messages / query / response / context"]
    State --> AgentNode["agent_node<br/>注入 Memory → LLM 推理"]
    AgentNode -->|"tool_calls"| ToolNode["tool_node<br/>执行工具调用"]
    AgentNode -->|"无 tool_calls"| Finalize["finalize_node<br/>保存 Memory → 返回"]
    ToolNode -->|"tool results"| AgentNode
    Finalize --> Response["Dict[str, Any]<br/>{response: '...'}"]
```

---

## 6. Memory 集成

### 6.1 Memory 模型

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

### 6.2 SDK 集成代码

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

## 7. 部署配置

### 7.1 `agentarts_config.yaml`

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
      base_image: python:3.10-slim
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
        # === Inbound: Custom JWT (Google OAuth) ===
        authorizer_type: CUSTOM_JWT
        authorizer_configuration:
          custom_jwt:
            discovery_url: https://accounts.google.com/.well-known/openid-configuration
            allowed_audience:
              - "<your-google-oauth-client-id>"
            allowed_clients:
              - "<your-google-oauth-client-id>"
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
        - key: MODEL_API_KEY
          value: "<MaaS API Key>"
        - key: MODEL_NAME
          value: "deepseek-v3.2"
        - key: MODEL_URL
          value: "https://api.modelarts-maas.com/openai/v1"
        - key: MEMORY_SPACE_ID
          value: "<Memory Space ID>"

      tags:
        - key: app
          value: personal-assistant
        - key: env
          value: dev
```

### 7.2 部署命令

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
  -H "Authorization: Bearer <Google_ID_Token>" \
  -d '{"message": "查一下我的日程"}'
```

---

## 8. 项目文件结构

```
personal-assistant/
├── .agentarts_config.yaml          # AgentArts 部署配置
├── Dockerfile                       # ARM64 镜像
├── requirements.txt                 # Python 依赖
├── app/
│   ├── main.py                      # FastAPI 应用入口 + 路由定义
│   ├── agent_handler.py             # 共享 Agent 处理逻辑
│   ├── graph.py                     # LangGraph 编排定义
│   ├── memory.py                    # Memory 集成
│   ├── feishu_adapter.py            # 飞书消息解析 + 回复
│   ├── oauth.py                     # Google OAuth 流程
│   └── tools/
│       ├── github_tools.py          # GitHub 工具 (OAuth2 User Federation)
│       ├── google_tools.py          # Google 工具 (OAuth2 User Federation)
│       ├── internal_tools.py        # 内部 API 工具 (API Key M2M)
│       └── cloud_tools.py           # 云资源工具 (STS M2M)
├── web/                              # Web Chat 前端（独立项目）
│   └── ...
└── README.md
```

> 前端不再作为 `adapters/` 目录放在同一仓库。Web Chat 前端为独立项目，飞书和 OfficeClaw 走各自平台的配置。

---

## 9. Inbound / Outbound 认证矩阵

| 用户身份 | Inbound 方式 | Outbound 目标 | Outbound 方式 | Auth Flow |
|----------|-------------|---------------|---------------|-----------|
| Google 用户 | JWT (Google OAuth) | GitHub API | OAuth 2.0 | USER_FEDERATION |
| Google 用户 | JWT (Google OAuth) | Google Calendar | OAuth 2.0 | USER_FEDERATION |
| 企业员工 | JWT (Okta/Entra ID) | 内部 CRM | API Key | M2M |
| 运维人员 | JWT (Okta/Entra ID) | 云资源 | STS Token | M2M |
| 开发者 | API Key | _(全部)_ | _(开发调试)_ | — |

---

## 10. 参考文档

| 文档 | 路径 |
|------|------|
| **前端架构** | `architecture/frontend_architecture.md` |
| **后端架构** | `architecture/backend_architecture.md` |
| AgentArts 平台参考 | `architecture/cloud-service/agentarts.md` |
| AgentCore 对比参考 | `architecture/cloud-service/agentcore.md` |
| Identity SDK 文档 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_044.html` |
| Runtime 部署文档 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_028.html` |
| 认证鉴权 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_047.html` |
| Memory SDK 文档 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_043.html` |
| SDK 快速开始 | `https://support.huaweicloud.com/highcode-agentarts/agentarts_10_040.html` |
