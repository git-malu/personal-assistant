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
│   ├── llm_config.py        # LLM 多模型配置管理
│   ├── auth.py              # Gateway 注入身份 header 提取
│   ├── identity.py          # Outbound Identity provider 配置与辅助函数
│   ├── logging_config.py    # 日志配置
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
├── config.yaml              # LLM Provider 配置（多 provider 声明式管理）
├── openapi.json             # OpenAPI 规范（自动生成）
├── pyproject.toml           # 项目元数据 + 依赖 (uv)
├── uv.lock                  # 确定性依赖锁定
├── Dockerfile               # ARM64 容器镜像
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

### 2. 配置 LLM 凭据

DeepSeek API key 不再通过环境变量注入 Runtime。请在 AgentArts Identity 中创建 API key credential provider：

| 字段 | 值 |
|------|----|
| Provider name | `DEEPSEEK_API_KEY` |
| Secret value | DeepSeek API key |

`config.yaml` 保存默认模型元数据，`app.llm_config.get_model()` 会通过 AgentArts SDK `@require_api_key(provider_name="DEEPSEEK_API_KEY")` 获取密钥。`MODEL_NAME` / `MODEL_URL` 不是密钥，可作为部署期环境变量覆盖默认模型名和 API 地址。

### 3. 启动服务

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

### 4. 打开浏览器

访问 `http://localhost:8080/invocations/playground` 进入 Chainlit 调试界面。API 端点见下方。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/ping` | 健康检查，返回 `{"status":"ok"}` |
| `POST` | `/invocations` | 统一对话入口；不传 `stream` 或 `stream:false` 返回 JSON，`stream:true` 返回 SSE |

`/invocations` 需要可信用户身份和会话 ID。生产环境由 AgentArts Gateway 注入；本地直连时需要显式传入 `X-HW-AgentGateway-User-Id` 和 `x-hw-agentarts-session-id`。

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
# 模板
agentarts invoke '<payload>' --agent <agent> --user-id <user-id> --bearer-token '<bearer-token>'

# 示例
agentarts invoke '{"message":"hello world"}' --agent personal-assistant --user-id dev-user --bearer-token 'eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6IndoMDZzRWt6TEhKNXNOTmFVeVJZMl82TzhLMCJ9...'
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
