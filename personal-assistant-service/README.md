# Personal Assistant Service

Personal Assistant 的 Agent Identity 后端服务，运行在 AgentArts Runtime 上。服务通过 FastAPI + deepagents 处理对话逻辑，并通过 AgentArts Identity SDK 获取 LLM API Key、OAuth2 用户委托 token 和 STS 临时凭证，支持非流式与 SSE 流式两种对话模式。

当前后端重点验证 Agent Identity 的生产落地方式：Inbound 可信用户身份、Outbound Credential Provider、用户委托访问外部 API、Workload Access Token 复用、会话隔离以及敏感写操作二次确认。

## 目录结构

```
personal-assistant-service/
├── app/
│   ├── __init__.py          # Python 包标记
│   ├── main.py              # FastAPI 应用入口 + 路由定义
│   ├── agent_handler.py     # deepagents Agent 编排 + LLM 模型连接
│   ├── settings.py          # typed Runtime Settings（内部读取实现）
│   ├── database.py          # SQLAlchemy psycopg 3 URL normalization
│   ├── db_models.py         # Application-owned SQLAlchemy metadata
│   ├── provider_catalog.py  # 内置 LLM Provider metadata（非用户配置）
│   ├── llm_config.py        # LLM 配置解析 + Identity credential 获取
│   ├── auth.py              # Gateway 注入身份 header 提取
│   ├── conversations.py     # Conversation ownership defense-in-depth
│   ├── identity.py          # Outbound Identity provider 配置与辅助函数
│   ├── logging_config.py    # Structured logging formatter/filter/middleware
│   ├── playground.py        # Chainlit Playground 挂载
│   └── tools/               # Identity SDK 装饰的外部工具
│       ├── __init__.py      # 工具注册工厂
│       ├── email_tools.py   # Microsoft 365 邮件工具
│       ├── github_tools.py  # GitHub 工具
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
│   ├── test_github_tools.py # GitHub 工具测试
│   ├── test_gitee_tools.py  # Gitee 工具测试
│   ├── test_iam_tools.py    # IAM STS 工具测试
│   ├── test_identity.py     # Identity 配置辅助函数测试
│   ├── test_tools_init.py   # 工具注册测试
│   └── test_playground.py   # Chainlit Playground 测试
├── scripts/                 # 运维脚本（部署、冒烟测试等）
├── migrations/              # Alembic revisions and migration environment
├── alembic.ini              # Alembic configuration
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

配置 PostgreSQL 后，使用 Alembic 将 application-owned schema 升级到最新版本：

```bash
uv run alembic upgrade head
uv run alembic current --check-heads
```

Migration 使用 SQLAlchemy 2.x + Alembic + psycopg 3。LangGraph Checkpointer
内部表仍由 `AsyncPostgresSaver.setup()` 管理，不纳入应用 Alembic metadata。
如果数据库曾手工执行旧版 Feature 14 SQL，先核对 schema 完全一致，再执行
`uv run alembic stamp 0001_feature_14`，不得重复创建表。

### 3. 配置 LLM 凭据

DeepSeek API key 不再通过环境变量注入 Runtime。请在 AgentArts Identity 中创建 API key credential provider：

| 字段 | 值 |
|------|----|
| Provider name | `DEEPSEEK_API_KEY` |
| Secret value | DeepSeek API key |

`.env` 中的 `LLM_CREDENTIAL_PROVIDER` 只保存 Provider name，不保存 API key。
`app.llm_config.get_model()` 通过 AgentArts SDK 从 Identity 获取真实 credential。
模型、Provider 和可选 endpoint override 分别使用 `LLM_MODEL`、`LLM_PROVIDER` 和
`LLM_BASE_URL`。旧的 `MODEL_*` 环境变量不再支持。

### 4. 启动服务

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload \
  --log-config config/logging.dev.yaml
```

Production container 使用 `config/logging.prod.yaml`，将 Uvicorn lifecycle、
application 和 HTTP completion events 统一输出为常规 stdout console logs。`LOG_LEVEL`
同时控制全部 logger；request ID 会通过 `X-Request-ID` response header 返回。

### 5. 打开浏览器

访问 `http://localhost:8080/invocations/playground` 进入 Chainlit 调试界面。API 端点见下方。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/ping` | 健康检查，返回 `{"status":"ok"}` |
| `POST` | `/invocations` | 统一对话入口；不传 `stream` 或 `stream:false` 返回 JSON，`stream:true` 返回 SSE |

`/invocations` 需要可信用户身份和 Runtime Session ID。Web Chat body 额外传入
durable `conversation_id`；LangGraph `thread_id` 固定使用
`{user_id}:{conversation_id}`，不再由可替换 Runtime Session 派生。

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
  -d '{"conversation_id":"11111111-1111-4111-8111-111111111111","message":"你好"}'

# SSE 流式对话
curl -N -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-HW-AgentGateway-User-Id: dev-user" \
  -H "x-hw-agentarts-session-id: dev-session" \
  -d '{"conversation_id":"11111111-1111-4111-8111-111111111111","message":"你好","stream":true}'
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
| **Feature 10a** | **Outbound Email — Microsoft 365 邮件处理** | **已实现** |
| | `app/tools/email_tools.py` — list_emails, get_email, search_emails, send_email, reply_to_email | |
| | AgentArts Identity SDK `@require_access_token` + Microsoft Graph API | |
