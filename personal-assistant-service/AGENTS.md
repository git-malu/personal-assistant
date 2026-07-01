# personal-assistant-service

> 本文件是 `personal-assistant-service/` 目录的专用 instructions，仅适用于该目录下的相关工作。开始前先阅读项目根目录的 [`AGENTS.md`](../AGENTS.md)。

## Directory Guide

`personal-assistant-service/` 是运行在 AgentArts Runtime 上的 Agent Identity 后端服务。服务通过 FastAPI + deepagents 处理对话逻辑，并通过 AgentArts Identity SDK 获取 LLM API Key、OAuth2 用户委托 token 和 STS 临时凭证，支持 JSON 非流式与 SSE 流式两种对话模式。

## Tech Stack

- **核心语言与框架**: Python 3.12+, FastAPI, Uvicorn
- **Agent/LLM**: deepagents, LangChain (`langchain-core`, `langchain-openai`), LangGraph checkpointers
- **Identity 与云服务**: `agentarts-sdk`, HuaweiCloud IAM SDK, AgentArts Runtime
- **持久化**: PostgreSQL checkpointer for production, SQLite checkpointer for local/test
- **开发工具链**: uv, Ruff, pytest, pytest-asyncio, Chainlit playground

## Directory Structure

```text
personal-assistant-service/
├── app/
│   ├── main.py              # FastAPI app 与 HTTP routes
│   ├── agent_handler.py     # deepagents Agent 编排
│   ├── auth.py              # Gateway 身份 header 提取
│   ├── identity.py          # AgentArts Identity helpers
│   ├── llm_config.py        # LLM provider/credential 解析
│   ├── logging_config.py    # structured logging
│   ├── playground.py        # Chainlit playground mount
│   ├── settings.py          # typed runtime settings
│   └── tools/               # Calendar/Email/GitHub/Gitee/IAM 等外部工具
├── tests/                   # pytest unit/integration tests
├── scripts/
│   └── generate_openapi.py  # OpenAPI artifact 生成脚本
├── config/                  # logging.dev.yaml / logging.prod.yaml
├── .agentarts_config.yaml   # AgentArts deployment config
├── Dockerfile
├── openapi.json             # versioned generated artifact
├── pyproject.toml
└── AGENTS.md
```

## Build and Test Commands

- **安装依赖**: `uv sync`
- **本地启动**: `uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload --log-config config/logging.dev.yaml`
- **代码检查**: `uv run ruff check .`
- **格式化检查**: `uv run ruff format --check .`
- **自动格式化**: `uv run ruff format .`
- **运行测试**: `uv run pytest tests/`
- **覆盖率测试**: `uv run pytest tests/ -v --cov=app --cov-report=term-missing`
- **生成 OpenAPI**: `uv run python scripts/generate_openapi.py`

## Code Style Guidelines

- 遵循 PEP8；Ruff 规则以 `pyproject.toml` 为准。
- FastAPI route 只负责 HTTP 层 request/response 转换、状态码和内容协商；Agent 编排和业务逻辑保持在 `AgentHandler`、tools 或独立 helper 中。
- 外部云服务、LLM、OAuth2 和 Identity SDK 调用必须可 mock；不要在 import time 发起网络请求。
- 敏感信息不得写入代码、测试快照或 `openapi.json`。LLM API Key 通过 AgentArts Identity Credential Provider 获取。
- 修改 route、request schema 或 response schema 后，必须重新生成并检查 `openapi.json`。

## Testing Instructions

- 单元测试和集成测试统一放在 `tests/`。
- 使用 pytest + pytest-asyncio；异步方法优先写 async tests。
- 测试必须 mock 外部依赖，尤其是 AgentArts SDK、HuaweiCloud SDK、Microsoft Graph、GitHub/Gitee API 和 LLM。
- 修改 auth/session/checkpointer/streaming 行为时，必须覆盖 sync 与 SSE 两种调用路径。
- 提交前运行 `uv run ruff check .`、`uv run ruff format --check .` 和相关 `uv run pytest ...`。

## Local Invocation Notes

`/invocations` 在 production 依赖 AgentArts Gateway 注入可信身份。本地直连测试需显式传入：

- `X-HW-AgentGateway-User-Id`
- `x-hw-agentarts-session-id`

```bash
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "X-HW-AgentGateway-User-Id: dev-user" \
  -H "x-hw-agentarts-session-id: dev-session" \
  -d '{"message":"你好"}'
```
