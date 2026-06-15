---
status: todo
related: []
---

# Bug 12: 首次聊天触发 504 Gateway Timeout

每日初次聊天时，请求链路中某个环节耗时超过代理层（Netlify / AgentArts Gateway）的 30s 超时阈值，导致返回 **504 Gateway Timeout**。容器本身有定时 `/ping` 保活，冷启动可能不是唯一原因。

## 现象

```
Chat API error: 504 Gateway Timeout
```

- **触发条件**：每日首次打开聊天界面发送消息
- **频率**：每天初次聊天时几乎必现
- **用户操作**：手动重试一次后通常恢复正常
- **错误展示位置**：`personal-assistant-client/src/lib/chat-adapter.ts:125`（`response.status` 被展示为错误信息）

> **注意**：504 是中间代理/网关返回的 HTTP 状态码，**不是来自聊天客户端本身**。客户端 `fetch()` 收到 504 响应后只是将其展示出来。

## 根因分析

### 完整请求链路

```
Browser (fetch) → Netlify (reverse proxy) → AgentArts Gateway (APIG) → Container (uvicorn :8080) → LLM (MaaS/DeepSeek)
                         30s timeout?              30s backend timeout?
```

### 可能的 504 来源

| 来源 | 组件 | 超时 | 是否可配 |
|------|------|------|:---:|
| **Netlify CDN 代理** | `netlify.toml:14-18` — `status=200` rewrite 反向代理 | ~30s | **否** |
| **AgentArts Gateway** | 华为云 APIG 默认后端超时 | ~30s | **否**（`.agentarts_config.yaml` 无 timeout 字段） |

### 耗时可能来源（容器已通过 /ping 保活的前提下）

| 阶段 | 操作 | 备注 |
|------|------|------|
| ① deep_agent 首次 AstreamEvents | LangGraph graph 编译 / checkpoint 初始化 | 可能有首次调用延迟 |
| ② 首次 LLM API 调用 | MaaS DeepSeek 推理服务可能有预热时间 | 首次推理延迟可能 5–15s |
| ③ LLM 推理本身 | Token 生成 | 每 token 约 50–100ms |
| **合计** | | **可能超过 30s** |

**关键判断**：即使容器通过 `/ping` 保活（进程未退出），首次实际 LLM 调用链路中仍然可能存在预热延迟，导致总耗时超过代理层 30s 超时。`/ping` 只验证容器存活，不触发 deep_agent 或 LLM 调用。

### 现有重试逻辑审计

| 组件 | 场景 | 是否有重试 | 文件:行 |
|------|------|:---:|---------|
| Client | 401/403 token 过期 | **Yes** — silent refresh + 1 retry | `chat-adapter.ts:103-118` |
| Client | **504 / 502 / 503** | **No** — 直接抛异常 | `chat-adapter.ts:125` |
| Client | `fetch()` 网络错误 | **No** — 未显式捕获 | `chat-adapter.ts:95` |
| Service | LLM 调用失败 | **No** | `agent_handler.py` |
| Service | 请求处理超时 | **No** | `main.py` |
| Infra | 容器 keep-alive | **No** — 无定时 ping | — |

## 解决方案

### ① 客户端 504 自动重试（P0，核心修复）

代理层超时我们无法控制（Netlify 和 AgentArts Gateway 均不开放 timeout 配置）。但超时发生时请求**已经成功到达后端**（容器在处理），只是代理层等不及先断了。因此修复思路是：代理超时后等待足够时间，再重试。

用户反馈实际处理最慢约 15 秒，因此重试策略：

```
fetch() → 504（代理超时断开）
  → wait 15s（后台处理完成）
  → retry → 成功（SSE 流正常返回）
```

**涉及文件**：
- `personal-assistant-client/src/lib/chat-adapter.ts` — 在 `chatAdapter.run()` 的 fetch 段增加 retry loop

**设计要点**：
- 仅对 **504 Gateway Timeout** 重试 1 次（这是每日初次聊天的已知场景），等待 **15 秒**后重试
- 502/503 作为保险也纳入重试范围（同为瞬时性基础设施问题），backoff：5s → 15s，max 2 次
- 401/403 的重试逻辑保持独立（token refresh 已在当前代码中处理）
- `AbortSignal` 传递到每次重试的 fetch 调用，用户取消应能中断 wait + retry loop

### ② 平台侧（长期，非可控）

- 确认 504 具体来源（Netlify 还是 AgentArts Gateway）——可在浏览器 DevTools Network 面板中查看 504 响应的 `Server` 头
- 向对应平台提工单：请求增加代理超时配置（或提高默认值至 60–120s）
- 记录至 bug-11 AgentArts 平台级缺陷汇总

## 实施任务

- [ ] 修改 `personal-assistant-client/src/lib/chat-adapter.ts`：对 504 增加 15s 等待 + 1 次重试；对 502/503 增加 5s/15s backoff 重试
- [ ] 确认用户取消（AbortSignal）能正确中断 15s wait + retry
- [ ] 通过浏览器 DevTools Network 面板确认 504 具体来源（Netlify 还是 AgentArts Gateway），记录到本文档
- [ ] 更新 `personal-assistant-meta/issues/bugs/bug-11-agentarts-platform-issues/issue.md`：追加代理超时不可配置的限制

## 四问闸门（Four-Question Gate）

| 维度 | 评估结果 | 说明 |
|------|:---:|------|
| **Is it best practice?** | **Yes** | 客户端对瞬时性网关超时做自动重试是分布式系统中的标准 resilience 模式（Idempotent Retry）。 |
| **Is it industry standard?** | **Yes** | Stripe、GitHub API、AWS SDK 均对 5xx 做 exponential backoff 重试。定时 ping 防止 serverless cold start 也是 AWS Lambda/Cloud Run 社区的通用实践。 |
| **Is it conventional?** | **Yes** | 仅对 502/503/504 重试（非所有 5xx），backoff 参数遵循常见约定。 |
| **Is it modern?** | **Yes** | 利用 `fetch()` + `AbortSignal` 原生能力，无需引入额外依赖。 |

## 参考

- `personal-assistant-client/src/lib/chat-adapter.ts:95-126` — 当前 fetch 调用及错误处理
- `personal-assistant-client/netlify.toml:14-18` — Netlify → AgentArts Gateway redirect
- `personal-assistant-service/Dockerfile:22` — uvicorn 启动命令（无超时配置）
- `personal-assistant-service/app/main.py:93-139` — `/invocations` SSE 流式处理
- `personal-assistant-service/.agentarts_config.yaml` — Runtime 配置（无 timeout 字段）
- Bug 11: `../bug-11-agentarts-platform-issues/issue.md` — AgentArts 平台限制汇总
