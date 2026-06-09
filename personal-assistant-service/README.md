# Personal Assistant Service

基于 [AgentArts](https://www.huaweicloud.com/product/agentarts.html) 平台的 AI Agent 后端服务。处理对话逻辑、日程/邮件/笔记/任务管理，支持非流式与 SSE 流式两种对话模式。

当前为 **Feature 1**（Agent 骨架 + Web Chat 渠道）——最小可运行骨架。

## 目录结构

```
personal-assistant-service/
├── app/
│   ├── __init__.py          # Python 包标记
│   ├── main.py              # FastAPI 应用入口 + 路由定义
│   └── agent_handler.py     # deepagents Agent 编排 + MaaS 模型连接
├── web/
│   └── index.html           # Web Chat 前端（SSE 流式客户端）
├── tests/
│   ├── __init__.py
│   ├── test_main.py         # FastAPI 端点集成测试
│   └── test_agent_handler.py # AgentHandler 单元测试
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

### 2. 设置环境变量

```bash
export MODEL_API_KEY="<your-maas-api-key>"
```

可选变量（已提供默认值）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MODEL_API_KEY` | **必需** | MaaS API Key |
| `MODEL_NAME` | `deepseek-v4-pro` | 模型名称 |
| `MODEL_URL` | `https://api.modelarts-maas.com/openai/v1` | MaaS API 地址 |

### 3. 启动服务

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### 4. 打开浏览器

访问 `http://localhost:8080/invocations/playground` 进入 Chainlit 调试界面。API 端点见下方。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/ping` | 健康检查，返回 `{"status":"ok"}` |
| `POST` | `/invocations` | 非流式对话，供 AgentArts / OfficeClaw 调用 |
| `GET` | `/invocations/stream?q=...` | SSE 流式对话，供 Web Chat 前端使用 |

### 示例

```bash
# 健康检查
curl http://localhost:8080/ping

# 非流式对话
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"message":"你好"}'

# SSE 流式对话
curl -N "http://localhost:8080/invocations/stream?q=你好"
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
docker run --rm -p 8080:8080 -e MODEL_API_KEY="<your-key>" personal-assistant:dev
```

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
| LLM 连接 | langchain-openai → MaaS (DeepSeek-V4-Pro) |
| 包管理 | uv |
| 代码质量 | ruff |
| 测试 | pytest + pytest-asyncio |

## 架构

```
Browser ──GET /invocations/stream?q=...──→ StreamingResponse
  │
  │  SSE 响应
  │
  │  AgentHandler.handle_stream()
  │
  │  deepagents agent.astream_events(v2)
  │
  │  MaaS LLM (DeepSeek-V4-Pro)
  │
  └── POST /invocations ──→ AgentHandler.handle() → agent.ainvoke()
```

## 后续 Feature

| Feature | 内容 |
|---------|------|
| Feature 2 | Memory 集成（跨 Session 记忆） |
| Feature 3 | OfficeClaw 渠道 |
| Feature 4 | 用户认证 / OAuth |
| Feature 5 | 飞书渠道 + Vite/React 前端 |
| Feature 6-8 | 外部工具集成 |
