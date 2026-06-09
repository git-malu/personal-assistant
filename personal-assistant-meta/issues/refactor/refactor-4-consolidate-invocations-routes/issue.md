---
status: backlog
---

# Refactor 4: 路由收敛至 `/invocations` 前缀

AgentArts Gateway 仅转发 `/invocations`（`ACCURATE_MATCH`）或其子路径（`PREFIX_MATCH`）。当前 App 的路由散落在根路径（`/playground`、`/api/chat/stream`），导致 Gateway 返回 `No matching policy found` 404。将全部面向外部的路由收敛到 `/invocations/*` 下，同时启用 `PREFIX_MATCH`。

---

## 背景

AgentArts 部署后发现以下现象：

| 路径 | 预期 | 实际 |
|------|------|------|
| `POST /invocations` | AI 回复 | ✅ `agentarts invoke` 正常 |
| `GET /playground` | Chainlit UI | ❌ `404 No matching policy found` |
| `GET /api/chat/stream?q=...` | SSE 流式响应 | ❌ `404 No matching policy found` |
| `GET /ping` | `{"status":"ok"}` | ❌ `404 No matching policy found` |

根因：AgentArts Gateway 默认 `url_match_type: ACCURATE_MATCH`，仅将精确路径 `/invocations` 转发到容器。其他所有路径在 Gateway 层即被拒绝，不经过 IAM 签名认证也无法通过。

### 约束

1. AgentArts Gateway 只支持两种 URL 匹配模式（`ACCURATE_MATCH` / `PREFIX_MATCH`），无法配置 wildcard 或自定义路由表
2. `/ping` 是 AgentArts 平台内部健康检查端点，不走 Gateway，必须保留在根路径
3. `POST /invocations` 是 AgentArts SDK 的 invoke 入口，必须保留在根路径

### Gateway URL 匹配模式详解

AgentArts API Gateway 是部署在容器前面的唯一入口，所有外部请求（浏览器、`agentarts invoke`、InvokeRuntime API）都经过它。Gateway 决定了**哪些 URL 路径能被转发到容器**——不匹配的请求直接在 Gateway 层被拒绝（`404 No matching policy found`），连容器都到达不了。

#### `ACCURATE_MATCH`（默认值）

精确匹配，仅转发路径**严格等于** `/invocations` 的请求：

```
✅ POST /invocations              → 转发到容器 :8080/invocations
❌ GET  /invocations/             → 404（多了个斜杠）
❌ GET  /invocations/stream       → 404（子路径）
❌ GET  /invocations/playground   → 404（子路径）
❌ GET  /api/chat/stream          → 404（不同路径）
❌ GET  /playground               → 404（不同路径）
```

> `/ping` 不受影响——它是 AgentArts 控制面直接调容器做健康检查的，不走 Gateway。

**适用场景**：纯 SDK Agent（`AgentArtsRuntimeApp`），只有 `/invocations` 一个入口，通过 `agentarts invoke` 或 OfficeClaw 调用。

#### `PREFIX_MATCH`

前缀匹配，转发所有以 `/invocations/` 开头的请求：

```
✅ POST /invocations              → 转发到容器 :8080/invocations
✅ GET  /invocations/stream       → 转发到容器 :8080/invocations/stream
✅ GET  /invocations/stream?q=hi  → 转发（query 不影响路径匹配）
✅ GET  /invocations/playground   → 转发到容器 :8080/invocations/playground
✅ GET  /invocations/anything     → 转发到容器 :8080/invocations/anything
❌ GET  /playground               → 404（不以 /invocations/ 开头）
❌ GET  /api/chat/stream          → 404（不以 /invocations/ 开头）
```

**适用场景**：Custom Container 模式（自己写 FastAPI），需要在 Gateway 后暴露多个自定义路由。

#### 本项目的影响

| 路由 | 用途 | `ACCURATE_MATCH` | `PREFIX_MATCH` |
|------|------|:---:|:---:|
| `POST /invocations` | AgentArts SDK invoke 入口 | ✅ | ✅ |
| `GET /invocations/stream` | SSE 流式对话（Web Chat 前端） | ❌ | ✅ |
| `GET /invocations/playground` | Chainlit 调试 UI | ❌ | ✅ |

用 `ACCURATE_MATCH` 时，3 条路由只有 1 条能通。**必须用 `PREFIX_MATCH`** 并把所有面向外部的路由收敛到 `/invocations/*` 前缀下。

#### Gateway 不支持的能力

```
❌ Wildcard:      /invocations/*/detail
❌ 正则匹配:       /invocations/\d+
❌ 自定义路由表:   多条规则（如同时转发 /api/* 和 /webhook/*）
❌ 多前缀:        同时转发 /invocations/* 和 /playground/*
```

只有两个枚举值，没有中间地带。这意味着 `/auth/callback`（OAuth 回调）、`/feishu/webhook`（飞书事件）等需要独立 URL 的路由无法通过 Gateway 暴露——这类功能必须在浏览器侧处理（前端发起 OAuth），或通过 OfficeClaw 长连接模式绕过公网 URL 需求。

---

## 范围

### 路由迁移

| 当前路由 | 变更 | 目标路由 | 说明 |
|----------|------|----------|------|
| `GET /ping` | 不变 | `GET /ping` | 平台内部健康检查，不走 Gateway |
| `POST /invocations` | 不变 | `POST /invocations` | AgentArts SDK invoke 入口 |
| `GET /api/chat/stream` | 迁移 | `GET /invocations/stream` | SSE 流式对话，加 q query param |
| `GET /playground` | 迁移 | `GET /invocations/playground` | Chainlit redirect（→ `/invocations/playground/`） |
| Chainlit mount `/playground` | 迁移 | mount `/invocations/playground` | Chainlit UI |

### 配置变更

- [ ] `.agentarts_config.yaml`：`invoke_config` 加 `url_match_type: PREFIX_MATCH`
- [ ] `.agentarts_config.yaml`：`runtime.arch` 确保为 `arm64`（不得为 `x86_64`）

```yaml
# .agentarts_config.yaml — 变更部分
runtime:
  invoke_config:
    protocol: HTTP
    port: 8080
    url_match_type: PREFIX_MATCH   # ← 新增
  arch: arm64                       # ← 修正（原为 x86_64）
```

---

## API 设计

### 新 API 路由表

```
┌─────────────────────────────────────────────────────────┐
│ AgentArts Gateway (PREFIX_MATCH)                        │
│   /invocations/*  ──────────────────→  容器 :8080       │
│   其他路径         ───→  404                            │
└─────────────────────────────────────────────────────────┘

容器内 FastAPI 路由：

  GET  /ping                        → 平台内部健康检查
  POST /invocations                 → 同步对话
  GET  /invocations/stream?q=...    → SSE 流式对话
  GET  /invocations/playground      → 302 → /invocations/playground/
  GET  /invocations/playground/     → Chainlit UI
```

### `/invocations` — 同步对话

- **方法**: `POST`
- **Content-Type**: `application/json`
- **Request Body**:
  ```json
  {"message": "用户输入文本"}
  ```
- **Response**:
  ```json
  {"response": "AI 回复文本"}
  ```
- **调用方式**: `agentarts invoke '{"message":"..."}'`（SDK 自动签名），或用 HTTP 客户端 + IAM HMAC-SHA256 签名

### `/invocations/stream` — SSE 流式对话

- **方法**: `GET`
- **Query**: `q=<用户输入>`
- **Header**: `Accept: text/event-stream`
- **Response**: SSE 事件流
  ```
  data: {"content": "你"}
  data: {"content": "好"}
  ...
  data: [DONE]
  ```
- **调用方式**: `agentarts runtime invoke '{"message":"..."}' --custom-path stream`（需 SDK 支持 streaming 响应格式）

### `/invocations/playground` — Chainlit 调试 UI

- **方法**: `GET`
- **Response**: `302` → `/invocations/playground/`
- **说明**: 浏览器访问需带 IAM 签名（SDK invoke 不支持 browser redirect）。建议通过 Web Chat 前端替代，Chainlit 仅保留用于 `agentarts dev` 本地调试。

---

## 不涉及

- 前端 Web Chat 的路由适配 — Web Chat 通过 `agentarts invoke` API 调用，不直接依赖 HTTP 路由
- `/ping` 的 Gateway 可达性 — 平台内部端点，设计上不走 Gateway
- MCP / WebSocket 协议路由 — 本次仅涉及 HTTP 路由
- Gateway 自定义路由表配置 — AgentArts 平台不支持

---

## 影响

### 修改文件

| 文件 | 改动 |
|------|------|
| `personal-assistant-service/.agentarts_config.yaml` | 加 `url_match_type: PREFIX_MATCH`；修正 `arch: arm64` |
| `personal-assistant-service/app/main.py` | 迁移 `/api/chat/stream` → `/invocations/stream`；Chainlit mount 路径改为 `/invocations/playground` |
| `personal-assistant-meta/architecture/devops/agentarts-deploy-runbook.md` | 更新 Step 5 冒烟验证的 curl 命令，适配新路由；更新 PREFIX_MATCH 配置说明 |

### 不修改文件

| 文件 | 原因 |
|------|------|
| `app/agent_handler.py` | 路由变更不涉及 handler 逻辑 |
| `app/llm_config.py` | 无关 |
| `config.yaml` | 无关 |

### 下游影响

- **Web Chat 前端**：需更新 API 请求路径（`/api/chat/stream` → `/invocations/stream`），如前端通过 Vite proxy 本地开发，proxy 配置也需对应调整
- **CI/CD 冒烟测试**：`curl` 验证命令需改为 `agentarts invoke` + `--custom-path stream`（Gateway 要求签名认证，裸 curl 不可用）

---

## 任务拆解

### 4.1 配置更新
- [ ] `.agentarts_config.yaml`：加 `url_match_type: PREFIX_MATCH`
- [ ] `.agentarts_config.yaml`：`runtime.arch` 设为 `arm64`

### 4.2 路由迁移 (`app/main.py`)
- [ ] `GET /api/chat/stream` → `GET /invocations/stream`
- [ ] `GET /playground` redirect → `GET /invocations/playground` redirect
- [ ] `mount_chainlit(path="/playground")` → `mount_chainlit(path="/invocations/playground")`
- [ ] 确认 `GET /ping` 和 `POST /invocations` 保持不变

### 4.3 文档更新
- [ ] `agentarts-deploy-runbook.md` Step 5 更新验证命令
- [ ] `backend_architecture.md` API 路由表更新

### 4.4 验证
- [ ] `agentarts launch` 重新部署，确认 Gateway 路由生效
- [ ] `agentarts invoke '{"message":"你好"}'` → 同步对话正常
- [ ] `agentarts runtime invoke '{"message":"你好"}' --custom-path stream` → SSE 流正常
- [ ] Web Chat 前端（更新 API 路径后）对话正常

---

## 依赖

- chore-1-agentarts-deploy（AgentArts 部署 runbook）
- 当前 `app/main.py` 路由结构

---

## 参考

- [AgentArts SDK config.py `UrlMatchType`](https://github.com/huaweicloud/agentarts-sdk-python) — `ACCURATE_MATCH` vs `PREFIX_MATCH`
- [AgentArts 部署 runbook](../../architecture/devops/agentarts-deploy-runbook.md) §15.12 `runtime.arch` pitfall
- [backend_architecture.md](../../architecture/backend_architecture.md)
