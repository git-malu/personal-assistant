---
status: backlog
---

# Chore 5: 从 Request Header 提取 Workload Access Token

AgentArts Gateway 在转发请求到 runtime 容器时，会通过 `X-HW-AgentGateway-Workload-Access-Token` header 注入 workload access token。当前 `personal-assistant-service` 未提取此 header，导致 `@require_access_token` 等装饰器无法利用 Gateway 注入的 token，每次都走本地 fallback（`.agent_identity.json` + Identity Service API 调用）。

---

## 背景

在 `agentarts-sdk` (v0.1.3) 中：

- **`agentarts/sdk/runtime/model.py:12`**：定义了常量 `ACCESS_TOKEN_HEADER = "X-HW-AgentGateway-Workload-Access-Token"`
- **`agentarts/sdk/runtime/app.py:242-246`**：SDK 的 `AgentArtsRuntimeApp._build_request_context()` 从该 header 提取 token 并存入 `AgentArtsRuntimeContext`
- **`agentarts/sdk/identity/auth.py:232-236`**：`_get_workload_access_token()` 优先从 context 读取 token，若有则直接使用，跳过本地 auth setup

当前 `personal-assistant-service` 使用原生 FastAPI，未继承 `AgentArtsRuntimeApp`，因此缺少这个自动提取逻辑。代码中已手动提取 `X-HW-AgentGateway-User-Id` 和 `x-hw-agentarts-session-id`，但遗漏了 workload access token header。

---

## 范围

### Service 层

- 在请求处理入口（`main.py` 或 `app/auth.py`）提取 `X-HW-AgentGateway-Workload-Access-Token` header
- 调用 `AgentArtsRuntimeContext.set_workload_access_token()` 存入 context，使后续 `@require_access_token` 等装饰器可直接使用
- 若 header 不存在（本地开发环境），不报错，让 SDK fallback 到本地 auth

### 不涉及

- 不改变 `email_tools.py` 的 `@require_access_token` 装饰器逻辑
- 不改变 `.agent_identity.json` 的本地 fallback 机制
- 不需要修改 `pyproject.toml`（`agentarts-sdk` 已在依赖中）

---

## 任务拆解

- [ ] 在请求处理中间件（建议放在 `app/auth.py` 或 `main.py` 的 `invocations` 函数开头）添加 workload access token 提取逻辑：

  ```python
  from agentarts.sdk.runtime.context import AgentArtsRuntimeContext

  workload_token = request.headers.get("X-HW-AgentGateway-Workload-Access-Token")
  if workload_token:
      AgentArtsRuntimeContext.set_workload_access_token(workload_token)
  ```

- [ ] 单元测试：验证 header 存在时 context 被正确设置
- [ ] 单元测试：验证 header 不存在时不会报错（fallback 行为不变）

---

## 依赖

- `agentarts-sdk` >= 0.1.3 ✅（已在 `pyproject.toml` 中）

---

## 参考

- SDK 源码 `agentarts/sdk/runtime/model.py` — `ACCESS_TOKEN_HEADER` 常量定义
- SDK 源码 `agentarts/sdk/runtime/app.py:234-267` — `_build_request_context()` 参考实现
- SDK 源码 `agentarts/sdk/runtime/context.py:136-150` — `AgentArtsRuntimeContext` workload_access_token 存取方法
- SDK 源码 `agentarts/sdk/identity/auth.py:232-240` — `_get_workload_access_token()` 读取优先级
- AgentArts API 文档 PDF：`architecture/cloud-service/agentarts-api-pdf.pdf` — pp. 859-868 Runtime 调用 header 参数说明
