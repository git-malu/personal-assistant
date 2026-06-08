---
status: backlog
---

# Feature 1: Agent 骨架 + Web Chat 渠道

本 Phase 搭建 Personal Assistant 的最小可运行骨架并以 Web Chat 作为第一条接入渠道。完成后可在浏览器中完成流式对话。

---

## 背景

Web Chat 是最直观的验证渠道——打开浏览器就能聊，不需要创建飞书应用、配置公网回调、处理 Webhook 签名等外部依赖。先跑通 Agent 核心逻辑，后续渠道复用同一套 Agent 处理代码。本 Phase 不做登录认证，任何人打开页面即可对话。

## 范围

- FastAPI 应用入口（`app/main.py`）+ `/ping`、`/invocations`、`/chat/stream`
- `web/` 前端页面（单页 HTML，文本输入 + SSE 流式渲染）
- Agent 处理逻辑（`app/agent_handler.py`）— 非流式 + 流式
- LangGraph 编排（`app/graph.py`）— 由 deepagents 内置 ReAct loop 替代，无需手写 StateGraph
- MaaS 模型连接
- `agentarts_config.yaml` 基础配置
- Dockerfile（ARM64）

## 不涉及

- Memory 集成（Feature 2）
- OfficeClaw（Feature 3）
- 用户认证 / OAuth（Feature 4）
- 飞书渠道（Feature 5）
- 任何外部工具（Feature 6-8）
- 多 LLM Provider 可配置（Feature 1.3）

## 任务拆解

### 1.1 项目初始化

- [ ] 创建项目目录结构
- `requirements.txt`（fastapi、uvicorn、deepagents、langchain、agentarts-sdk、httpx）
- [ ] `Dockerfile`（`FROM python:3.12-slim`、linux/arm64）
- [ ] `.agentarts_config.yaml` 基础配置
- [ ] 本地开发环境变量

### 1.2 FastAPI 入口

- [ ] `app/main.py` — FastAPI 应用
  - `GET /ping` → `{"status": "ok"}`
  - `POST /invocations` → 调 AgentHandler（非流式，供 AgentArts / OfficeClaw 调用）
  - `GET /chat/stream?q=...` → SSE 流式对话
  - 前端静态文件 serve（`StaticFiles` mount `web/`）

### 1.3 Web Chat 前端

- [ ] `web/index.html` — 单页应用
  - 对话输入框 + 消息列表
  - 连接 SSE，逐 token 渲染消息
  - 无需登录（Feature 4 再加 OAuth）
- [ ] 同容器 serve：FastAPI `StaticFiles` mount `web/`

### 1.4 Agent 处理逻辑

- [ ] `app/agent_handler.py` — AgentHandler 类
  - `handle(message, user_id)` → 非流式，供 `/invocations` 使用
  - `handle_stream(message, user_id)` → 异步生成器，逐 token yield，供 `/chat/stream` 使用
  - 构造初始 State + 调 graph（非流式用 `ainvoke()`，流式用 `astream()`）

### 1.5 deepagents 编排

- [ ] `app/agent_handler.py` 中通过 `create_deep_agent()` 创建 agent
  - model：`init_chat_model("openai:deepseek-v4-pro", base_url=..., api_key=...)`
  - tools：Identity SDK 装饰的工具函数
  - system_prompt：角色定义 + 基本行为规范
- [ ] system prompt 设计（角色定义 + 基本行为规范）

### 1.6 MaaS 模型连接

- [ ] `init_chat_model()` 连接 MaaS
  - base_url: `https://api.modelarts-maas.com/openai/v1`
  - model: 环境变量 `MODEL_NAME`
- [ ] 验证 LLM 调用成功

### 1.7 SSE 流式对话

- [ ] `GET /chat/stream?q=...`
  - 调用 `agent_handler.handle_stream()`
  - 返回 `StreamingResponse`，media_type=`text/event-stream`
  - 格式：`data: {"token":"...","done":false}\n\n`

### 1.8 验证

- [ ] `curl /ping` → 200
- [ ] `curl /invocations -d '{"message":"你好"}'` → Agent 响应
- [ ] 浏览器打开 `localhost:8080` → 看到对话界面
- [ ] 输入消息 → 逐 token 流式渲染
- [ ] 多轮对话不崩溃

## 依赖

无。

## 参考

- ADR-001: Python 3.12
- ADR-002: LangGraph（Superseded by ADR-009）
- ADR-009: deepagents
- ADR-004: FastAPI
- ADR-005: MaaS
- ADR-008: Web Chat 前端框架选型
- `architecture/frontend_architecture.md` #2.1 Web Chat
- `architecture/devops/local-development.md`
