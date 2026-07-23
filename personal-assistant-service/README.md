# Personal Assistant Service

Personal Assistant 的 Agent Identity 后端服务，运行在 AgentArts Runtime 上。服务通过 FastAPI + deepagents 处理对话逻辑，并通过 AgentArts Identity SDK 获取 LLM API Key、OAuth2 用户委托 token 和 STS 临时凭证；GitHub MCP data source 使用专用 STS 凭据调用 AgentArts MCP Gateway。服务支持非流式与 SSE 流式两种对话模式。

当前后端重点验证 Agent Identity 的生产落地方式：Inbound 可信用户身份、Outbound Credential Provider、用户委托访问外部 API、Workload Access Token 复用、会话隔离以及敏感写操作二次确认。

## 目录结构

```
personal-assistant-service/
├── app/
│   ├── __init__.py          # Python 包标记
│   ├── main.py              # FastAPI 应用入口 + 路由定义
│   ├── agent_handler.py     # deepagents Agent 编排 + LLM 模型连接
│   ├── settings.py          # typed Runtime Settings（内部读取实现）
│   ├── provider_catalog.py  # 内置 LLM Provider metadata（非用户配置）
│   ├── llm_config.py        # LLM 配置解析 + Identity credential 获取
│   ├── auth.py              # Gateway 注入身份 header 提取
│   ├── identity.py          # Outbound Identity provider 配置与辅助函数
│   ├── logging_config.py    # Structured logging formatter/filter/middleware
│   ├── playground.py        # Chainlit Playground 挂载
│   ├── mcp/
│   │   ├── gateway_client.py # MCP session、STS 交换与 IAM request signing
│   │   └── github_activity_source.py # GitHub MCP internal activity source
│   └── tools/               # Identity SDK 装饰的外部工具
│       ├── __init__.py      # 工具注册工厂
│       ├── email_tools.py   # Microsoft 365 邮件工具
│       ├── github_tools.py  # GitHub 用户 OAuth 工具
│       ├── github_activity_tools.py # 两个 curated Agent-facing activity tools
│       ├── gitee_tools.py   # Gitee 工具
│       └── iam_tools.py     # 华为云 IAM STS 工具
├── tests/
│   ├── __init__.py
│   ├── test_main.py         # FastAPI 端点集成测试
│   ├── test_agent_handler.py # AgentHandler 单元测试
│   ├── test_llm_config.py   # LLM 配置管理测试
│   ├── test_auth.py         # 认证中间件测试
│   ├── test_checkpointer.py # Checkpoint 持久化测试
│   ├── test_email_tools.py  # Microsoft 365 邮件工具测试
│   ├── test_github_tools.py # GitHub OAuth 工具测试
│   ├── test_github_activity_source.py # GitHub MCP internal source 测试
│   ├── test_github_activity_tools.py # Agent-facing activity tools 测试
│   ├── test_mcp_gateway_auth.py # MCP Gateway IAM signing 测试
│   ├── test_gitee_tools.py  # Gitee 工具测试
│   ├── test_iam_tools.py    # IAM STS 工具测试
│   ├── test_identity.py     # Identity 配置辅助函数测试
│   ├── test_tools_init.py   # 工具注册测试
│   └── test_playground.py   # Chainlit Playground 测试
├── scripts/                 # 运维脚本（部署、冒烟测试等）
├── .env.example             # 唯一面向使用者的 Service 配置入口
├── openapi.json             # OpenAPI 规范（自动生成）
├── pyproject.toml           # 项目元数据 + 依赖 (uv)
├── uv.lock                  # 确定性依赖锁定
├── Dockerfile               # ARM64 容器镜像
├── config/
│   ├── logging.dev.yaml     # 本地 UTC console logs
│   └── logging.prod.yaml    # 生产 UTC console logs
├── .agentarts_config.yaml   # AgentArts 平台部署配置
└── .dockerignore
```

## 环境要求

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/)（包管理）
- Docker（可选，容器化部署）

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置 Service

所有 Service 配置从 `.env.example` 开始：

```bash
cp .env.example .env
```

本地开发填写 `.env`；生产环境在 AgentArts Runtime / CI/CD 注入同名环境变量。
`app/settings.py` 是内部读取实现，不是需要修改的配置文件。

### 3. 初始化或升级 PostgreSQL Schema

先在 `.env` 配置 `POSTGRES_DSN`。首次初始化数据库或拉取到新 migration 后，执行
`upgrade head`。

| 用途 | 命令 |
|------|------|
| 查看数据库当前 revision | `uv run --env-file .env alembic current` |
| 查看 migration 历史 | `uv run --env-file .env alembic history` |
| 查看最新 head | `uv run --env-file .env alembic heads` |
| 升级到最新 schema | `uv run --env-file .env alembic upgrade head` |
| 升级到指定 revision | `uv run --env-file .env alembic upgrade <revision>` |
| 创建空 migration | `uv run alembic revision -m "<description>"` |

当前 migration 需手写并审查，不使用 `--autogenerate`，也不支持 downgrade。

### 4. 配置本地 JWT Workload Identity

本地普通对话可以只用 mock header；如果要跑 Calendar OAuth2 full flow，并让
Service 使用真实 Microsoft Entra `Authorization: Bearer <id_token>` 主动
mint JWT-mode WAT，首次本地 setup 需要先创建 customer-owned
`pa-local-jwt-workload`：

```bash
cd ../personal-assistant-infra
uv sync
uv run python scripts/ensure_local_jwt_workload_identity.py --region cn-southwest-2
uv run python scripts/ensure_local_jwt_workload_identity.py --region cn-southwest-2 --apply
```

Service 默认读取
`AGENT_IDENTITY_LOCAL_JWT_WORKLOAD_NAME=pa-local-jwt-workload`。不要把它改成
service-created `agent-personal-assistant`，该 workload 只能被 Gateway 路径使用。

### 5. 配置 LLM 凭据

DeepSeek API key 不再通过环境变量注入 Runtime。请在 AgentArts Identity 中创建 API key credential provider：

| 字段 | 值 |
|------|----|
| Provider name | `DEEPSEEK_API_KEY` |
| Secret value | DeepSeek API key |

`.env` 中的 `LLM_CREDENTIAL_PROVIDER` 只保存 Provider name，不保存 API key。
`app.llm_config.get_model()` 通过 AgentArts SDK 从 Identity 获取真实 credential。
模型、Provider 和可选 endpoint override 分别使用 `LLM_MODEL`、`LLM_PROVIDER` 和
`LLM_BASE_URL`。旧的 `MODEL_*` 环境变量不再支持。

### 6. 启动服务

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload \
  --log-config config/logging.dev.yaml
```

Production container 使用 `config/logging.prod.yaml`，将 Uvicorn lifecycle、
application 和 HTTP completion events 统一输出为常规 stdout console logs。`LOG_LEVEL`
同时控制全部 logger；request ID 会通过 `X-Request-ID` response header 返回。

### 7. 打开浏览器

访问 `http://localhost:8080/invocations/playground` 进入 Chainlit 调试界面。API 端点见下方。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/ping` | 健康检查，返回 `{"status":"ok"}` |
| `POST` | `/invocations` | 统一对话入口；不传 `stream` 或 `stream:false` 返回 JSON，`stream:true` 返回 SSE |

`/invocations` 需要可信用户身份和会话 ID。生产环境由 AgentArts Gateway 注入；本地直连时需要显式传入 `X-HW-AgentGateway-User-Id` 和 `x-hw-agentarts-session-id`。

`message` 必须是非空字符串，`stream` 仅接受 JSON boolean。客户端未发送
`Accept` 或发送 `*/*` 时保持兼容；若明确排除实际响应类型，服务返回 `406`：

- sync：`application/json`
- streaming：`text/event-stream`

invocation 日志包含 `mode`、完成状态和 `duration_ms`，可分别统计 sync/stream
延迟与错误率。

### OpenAPI 规范

`openapi.json` 是从当前 FastAPI app 自动生成并提交到 repository 的
versioned artifact。修改 route 或 request schema 后执行：

```bash
uv run python scripts/generate_openapi.py
```

提交前检查 `openapi.json` diff，确保生成物与 `app.main:app` 一致。不要手工
编辑 `openapi.json`。

### 示例

```bash
# 健康检查
curl http://localhost:8080/ping

# 非流式对话
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "X-HW-AgentGateway-User-Id: dev-user" \
  -H "x-hw-agentarts-session-id: dev-session" \
  -d '{"message":"你好"}'

# SSE 流式对话
curl -N -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-HW-AgentGateway-User-Id: dev-user" \
  -H "x-hw-agentarts-session-id: dev-session" \
  -d '{"message":"你好","stream":true}'
```

### SSE 数据格式

```
data: {"token":"你","done":false}

data: {"token":"好","done":false}

data: {"token":"","done":true}
```

## Docker

### 构建镜像

```bash
docker build --platform linux/arm64 -t personal-assistant:dev .
```

### 运行容器

```bash
docker run --rm -p 8080:8080 personal-assistant:dev
```

## 在线测试

部署到 AgentArts 后，可通过 `agentarts invoke` 命令直接测试线上 Agent：

```bash
# 通过 IAM 签名认证（AgentArts Gateway 自动处理）
agentarts invoke '{"message":"你好，简单介绍一下你自己"}' --agent personal-assistant

# 或者使用 bearer token 认证（API Key 需替换为实际值）
agentarts invoke '{"message":"hello world"}' --bearer-token <your-bearer-token>
```

> **注意**：`agentarts invoke` 自动带 IAM 签名认证，可直接通过 AgentArts Gateway 调用。裸 `curl` 命令在生产环境不可用。

## 测试

```bash
# 运行全部测试 + 覆盖率
uv run pytest tests/ -v --cov=app --cov-report=term-missing

# Lint 检查
uv run ruff check .

# 格式化检查
uv run ruff format --check .
```

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI |
| Agent 编排 | deepagents（内置 ReAct loop） |
| LLM 连接 | langchain-openai + AgentArts Identity API Key provider |
| 包管理 | uv |
| 代码质量 | ruff |
| 测试 | pytest + pytest-asyncio |

## 架构

```
Browser ──POST /invocations {"stream":true}──→ StreamingResponse
  │
  │  SSE 响应
  │
  │  AgentHandler.handle_stream()
  │
  │  deepagents agent.astream_events(v2)
  │
  │  DeepSeek LLM (API key from AgentArts Identity)
  │
  │  GitHub activity tools → internal source → WAT/STS → IAM signed MCP Gateway → read-only Target
  │
  └── POST /invocations {"stream":false} ──→ AgentHandler.handle() → agent.ainvoke()
```

## Feature 状态

| Feature | 内容 | 状态 |
|---------|------|------|
| Feature 2 | Memory 集成（跨 Session 记忆） | [Planned — not yet implemented] |
| Feature 3 | OfficeClaw 渠道 | [Planned — not yet implemented] |
| Feature 4 | 用户认证 / OAuth（Inbound Identity） | 已实现 |
| Feature 5 | 飞书 Client Adapter（飞书 Bot 接入） | [Planned — not yet implemented] |
| Feature 6 | GitHub OAuth2 User Federation 工具 | 已实现 |
| | `app/tools/github_tools.py` — list repositories, list contents, get file, search code, star repository | |
| Feature 7 | Gitee OAuth2 User Federation 工具 | 已实现 |
| | `app/tools/gitee_tools.py` — list repositories | |
| Feature 8 | 华为云 IAM STS 只读工具 | 已实现 |
| | `app/tools/iam_tools.py` — list IAM users via `iam-users-readonly` STS provider | |
| Feature 17 | GitHub MCP Activity Data Source | 已实现 |
| | `app/mcp/github_activity_source.py` — 4 个 internal source，供 Feature 18 等内部编排直接复用且不注册为 Agent Tool | |
| | `app/tools/github_activity_tools.py` — Agent 仅使用 `github_search_activity` 和 `github_get_activity_detail`；所有返回结果固定包含 `identity_scope="platform"` | |
| | 仅当 `GITHUB_MCP_ENABLED=true` 且 `GITHUB_ACTIVITY_TOOLS_ENABLED=true` 时，`build_tools()` 才注册这两个 Tool | |
| | `app/mcp/gateway_client.py` — WAT → `github-mcp-gateway` STS → IAM signed MCP request | |
| **Feature 10a** | **Outbound Email — Microsoft 365 邮件处理** | **已实现** |
| | `app/tools/email_tools.py` — list_emails, get_email, search_emails, send_email, reply_to_email | |
| | AgentArts Identity SDK `@require_access_token` + Microsoft Graph API | |
