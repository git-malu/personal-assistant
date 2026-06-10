---
status: done
---

# Refactor 7: 统一 `/invocations` 为单一路由 — POST body 区分 sync/stream

AgentArts Gateway 的 `PREFIX_MATCH` 功能尚未上线，Gateway 实际仅做 `ACCURATE_MATCH`，只转发 `/invocations` 精确路径。当前 `GET /invocations/stream?q=...` 在生产环境返回 404，Web Chat 流式对话不可用。

将 SSE 流式逻辑与同步调用逻辑合并到同一个 `POST /invocations` 路由，通过 body 中 `stream: true` 标志做区分。

---

## 背景

### 问题根因

| 路由 | 现状 | 生产环境 |
|------|------|---------|
| `POST /invocations` | 同步调用 | ✅ Gateway 转发 |
| `GET /invocations/stream?q=...` | SSE 流式 | ❌ `404 No matching policy found` |
| `GET /invocations/playground` | Chainlit 调试 UI | ❌ 同上 |

AgentArts Gateway 的 `url_match_type` 只有两种模式：

- `ACCURATE_MATCH`（当前）：仅转发 `/invocations` 精确路径
- `PREFIX_MATCH`：转发 `/invocations/*` 前缀（**尚未上线**，`agentarts launch` 后 Gateway 实际仍为 `ACCURATE_MATCH`）

`agentarts_config.yaml` 中 `url_match_type: ACCURATE_MATCH` 是唯一可用的生产配置。任何子路径路由（`/invocations/stream`、`/invocations/playground`）都无法通过 Gateway。

### 为什么不用 GET /invocations?q=... 做流式

初步讨论的方案是 `GET /invocations?q=...` 做 SSE，`POST /invocations` 做同步。三位顾问评估后一致否定，主要理由：

1. **URL 长度限制（致命）**：GET query 在 Gateway / Vite proxy / Uvicorn 各层有严格长度限制（通常 2-8KB）。用户粘贴代码/长文档时必然触发 `414 URI Too Long`，导致流式对话崩溃。
2. **HTTP 语义违规**：GET 应为 safe/idempotent 操作（RFC 7231）。流式 LLM 调用产生 token 消耗、Memory 写入等副作用，违反 HTTP 规范。
3. **非行业惯例**：OpenAI、Anthropic、Google Gemini 等所有主流 LLM Provider 均使用 `POST + stream: true` 模式。
4. **查询参数泄露**：用户消息出现在 URL query 中，会被浏览器历史、代理日志、CDN 日志记录。

### 推荐方案：统一 `POST /invocations` + `stream: true`

```
POST /invocations
Content-Type: application/json

{"message": "你好", "stream": false}  → 同步，返回 JSON
{"message": "你好", "stream": true}   → 流式，返回 text/event-stream
```

优势：
- 单一路由，`ACCURATE_MATCH` 完全兼容
- 与 OpenAI/Anthropic API 设计一致，新成员立刻理解
- 无 URL 长度风险，支持任意长度 prompt
- Body 传参可扩展（未来可加 `model`、`tools` 等配置）
- 向后兼容：不传 `stream` 或 `stream: false` 时，行为与当前 `POST /invocations` 完全一致

### 相关 Issue

- [Bug-9: AgentArts Gateway 404 on `/invocations/stream`](../bugs/bug-9-agentarts-gateway-404-stream/issue.md) — 本 issue 是该 bug 的根因修复
- [Refactor-4: 路由收敛至 `/invocations` 前缀](../resolved/refactor-4-consolidate-invocations-routes/issue.md) — 当时依赖 `PREFIX_MATCH` 方案，本 refactor 用单路径 `POST` 替代

---

## 范围

### 纳入

| 改动 | 文件 | 说明 |
|------|------|------|
| 合并 SSE handler 到 `POST /invocations` | `personal-assistant-service/app/main.py` | 删除 `@app.get("/invocations/stream")`；在 `invocations()` 中读取 `stream` 字段做分支 |
| 更新 client 请求 | `personal-assistant-client/src/lib/chat-adapter.ts` | `fetch` 从 `GET /invocations/stream` 改为 `POST /invocations`，body 带 `{"message": query, "stream": true}`，header 加 `Content-Type: application/json` |
| 更新 client 测试 | `personal-assistant-client/src/lib/chat-adapter.test.ts` | 所有 `/invocations/stream` 路径断言更新为 `/invocations` + POST body |
| 更新架构文档 | `personal-assistant-meta/architecture/backend_architecture.md` | §2.2 路由表：删除 `GET /invocations/stream`，文档化 `POST /invocations` 的双模式行为；§2.1 Gateway 约束：补充 `ACCURATE_MATCH` 的限制说明 |
| 部署 smoke test 指引 | 本 issue 正文 | 生产环境验证 checklist |

### 不纳入

- **Chainlit Playground 生产化** — `/invocations/playground` 仍受限于 `ACCURATE_MATCH`，仅在本地调试可用（符合设计意图：Playground 是调试工具，非用户面功能）
- **Vite proxy 修改** — 当前 proxy 已配置 `/invocations`，无需改动
- **`agentarts_config.yaml` 修改** — `url_match_type` 保持 `ACCURATE_MATCH` 不变
- **同步 `POST /invocations` 行为变更** — 不传 `stream` 或 `stream: false` 时完全保持现有行为

---

## 验收条件

### Backend

- [x] `POST /invocations` 接收 `{"message": "hello"}` → 返回 `{"response": "..."}`（同步，行为不变）
- [x] `POST /invocations` 接收 `{"message": "hello", "stream": false}` → 同上
- [x] `POST /invocations` 接收 `{"message": "hello", "stream": true}` → 返回 `text/event-stream`，逐 token SSE 推送
- [x] `POST /invocations` 不传 `message` → 返回 400
- [x] `POST /invocations` JSON 格式错误 → 返回 400
- [x] 旧路由 `GET /invocations/stream` 已删除 → 返回 404 或 405
- [x] FastAPI `/docs` 自动生成的双模式文档正确

### Client

- [x] `chatAdapter.run()` 发送 `POST` 到 `/invocations`，body 含 `{"message": "...", "stream": true}`
- [x] 请求包含 `Content-Type: application/json` 和 `Accept: text/event-stream`
- [x] SSE token 解析行为与变更前一致（增量 token 累积、completion status、错误处理）
- [x] abort signal 正确传递

### 部署验证

- [ ] `POST /invocations`（`agentarts invoke`）→ 正常返回 JSON
- [ ] `POST /invocations`（带 `stream: true`）→ 正常返回 SSE stream
- [ ] `GET /invocations/stream` → 返回 404（Gateway 层或 FastAPI 层）

---

## Four-Question Gate

> 评估对象：**统一 `POST /invocations` + body `stream: true`** 方案

| Question | Answer | Notes |
|----------|--------|-------|
| Is it best practice? | **Yes** | `POST` 用于有副作用的 LLM 调用完全符合 HTTP 语义（RFC 7231 §4.3.3）。单一 handler 通过 body 字段控制行为模式，遵循单一职责原则——路由负责请求分发，body 负责模式选择 |
| Is it industry standard? | **Yes** | OpenAI（`POST /chat/completions` + `stream: true`）、Anthropic（`POST /messages` + `stream: true`）、Google Gemini 均采用此模式。Vercel AI SDK、LangChain 等框架也原生支持 `POST` streaming |
| Is it conventional? | **Yes** | 任何熟悉现代 AI API 的开发者看到 `POST /invocations` + `{"stream": true}` 会立刻理解。FastAPI `/docs` 自动生成清晰的 schema 文档 |
| Is it modern? | **Yes** | `fetch`-based `ReadableStream`（client 已使用）是现代 streaming 方案，不依赖旧版 `EventSource` API。Body 传参支持未来扩展（model 选择、tools 配置等），不污染 URL query space |

**对比**：被否决的 `GET /invocations?q=...` 方案在 Four-Question Gate 评估中仅 **1/4 Yes**（Conventional 勉强通过），在 Best Practice / Industry Standard / Modern 三项均为 No。

---

## 影响

### 修改文件

| 文件 | 改动 |
|------|------|
| `personal-assistant-service/app/main.py` | 删除 `@app.get("/invocations/stream")`；在 `invocations()` 中根据 `stream` 字段分支返回 JSON 或 `StreamingResponse` |
| `personal-assistant-client/src/lib/chat-adapter.ts` | 第 32-38 行：fetch URL 改为 `POST /invocations`，body 带 `{"message": query, "stream": true}` |
| `personal-assistant-client/src/lib/chat-adapter.test.ts` | 更新 URL 构造测试、header 断言、body 断言 |
| `personal-assistant-meta/architecture/backend_architecture.md` | §2.2 路由表更新，§2.1 Gateway 约束补充 `ACCURATE_MATCH` 限制 |

### 测试影响

| 测试文件 | 影响 |
|----------|------|
| `personal-assistant-client/src/lib/chat-adapter.test.ts` | URL 路径从 `/invocations/stream` → `/invocations`；增加 `method: "POST"` 和 JSON body 断言 |
| `personal-assistant-service` 后端测试 | 需新增 `stream: true` 测试 case（SSE 逐 token 返回 + completion status） |

---

## 任务拆解

### 7.1 Backend — 合并路由

- [x] `app/main.py`：删除 `@app.get("/invocations/stream")` handler（第 87-107 行）
- [x] `app/main.py`：扩展 `invocations()` handler，读取 `stream` 字段
  - `stream` 为 `false` 或不传 → 保持现有同步行为
  - `stream` 为 `true` → 返回 `StreamingResponse`（复用原 SSE handler 逻辑）
  - JSON 解析失败 → 返回 400
- [x] 后端单测：覆盖 `stream: true` SSE 流式输出、`stream: false` 同步输出、无 `stream` 字段向后兼容

### 7.2 Client — 适配新接口

- [x] `chat-adapter.ts`：fetch 改为 `POST /invocations`，`Content-Type: application/json`，body `{"message": query, "stream": true}`
- [x] `chat-adapter.test.ts`：更新所有测试 case
  - URL 断言：`/invocations`（非 `/invocations/stream`）
  - Method 断言：`POST`
  - Body 断言：`{"message": "...", "stream": true}`
  - SSE 解析、错误处理、abort signal 测试保持不变

### 7.3 文档更新

- [x] `backend_architecture.md` §2.2 路由表：移除 `GET /invocations/stream`；更新 `POST /invocations` 描述为双模式
- [x] `backend_architecture.md` §2.1 Gateway 约束：明确 `url_match_type: ACCURATE_MATCH` 仅转发 `/invocations` 精确路径，子路径不可用

### 7.4 部署 Smoke Test

- [ ] `curl -X POST <runtime-domain>/invocations -d '{"message":"你好"}'` → JSON 响应
- [ ] `curl -X POST <runtime-domain>/invocations -d '{"message":"你好","stream":true}'` → SSE stream
- [ ] 旧 `GET /invocations/stream` 返回 404

---

## 依赖

- Bug-9（AgentArts Gateway 404）— 已确认根因为 `ACCURATE_MATCH`
- Refactor-4（路由收敛）— 已 resolved，本次是其技术方案的修正

## 参考

- [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat/create) — `POST` + `stream: true` 标准模式
- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages-streaming) — 单 `POST` 路由流式
- [HTTP Semantics (RFC 7231 §4.3.3)](https://datatracker.ietf.org/doc/html/rfc7231#section-4.3.3) — POST method 语义
- [MDN Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- [ADR-004: FastAPI over AgentArtsRuntimeApp](../../architecture/ADR/ADR-004-fastapi-over-agentarts-runtime-app.md)
