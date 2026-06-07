---
status: backlog
related: feature-1-agent-skeleton
---

# Bug 1: MaaS API Rate Limit 导致多轮对话失败

ModelArts MaaS API（`api.modelarts-maas.com`）的硬限流为 **3 RPM**，当前 Agent 在无防护的情况下触发并发/连续调用时频繁返回 `429 RateLimitError`，导致多轮对话中断。

## 现象

```
openai.RateLimitError: Error code: 429 - Too many requests, the rate limit is 3 times per minute.
```

Feature 1 的 7 个验证用例在 ~1 分钟内触发了 5 次 API 调用（测试 2、4、加上 3 条多轮消息），其中第 2、3 条消息命中限流，返回 429。

## 根因

| 层面 | 问题 |
|------|------|
| **平台约束** | MaaS API 硬限流 3 RPM，无法在客户端突破 |
| **调用侧无防护** | `ChatOpenAI` 直接裸调 API，没有限流器或重试逻辑 |
| **测试无协调** | 7 个测试并发/快速连续执行，无视速率上限 |

## 解决方案：三层防护

```
┌──────────────────────────────────────────┐
│  ① 限流器（prevention）                     │
│     Token Bucket: 3 tokens/60s            │
│                  ↓ 放行 或 等待            │
│  ② 重试器（recovery）                       │
│     tenacity: 429 → exp backoff            │
│     (2s → 6s → 18s, max 3 retries)        │
│                  ↓ 仍失败                  │
│  ③ 降级（graceful）                         │
│     返回友好错误 + 建议稍后重试              │
└──────────────────────────────────────────┘
```

### 详细设计

#### ① Token Bucket 限流器

- 新建 `app/rate_limiter.py`
- `TokenBucketRateLimiter(rate=3, period=60.0)`
- 全局单例，所有 LLM 调用前 acquire token
- 超限时 asyncio.sleep 等待下一个 token 生成（20s/token）

#### ② Retry with Exponential Backoff

- 依赖 `tenacity`（加入 `requirements.txt`）
- 仅对 `openai.RateLimitError` 重试
- backoff：`multiplier=2, min=2s, max=30s`，最多 3 次
- `ChatOpenAI(max_retries=0)` — 关闭 LangChain 自带的无退避重试

#### ③ 集成点

`app/agent_handler.py` → `_call_llm()`：

```python
@with_retry_on_rate_limit
async def _call_llm(self, messages):
    await self._limiter.wait_and_acquire()
    return await self._model.ainvoke(messages)
```

### 测试层面

- pytest `autouse fixture` 在测试间插入 22s 延迟（60s/3 + 2s buffer）
- 或使用 `pytest-order` + `pytest.mark.order(n)` 控制执行顺序

## 实施任务

- [ ] 新建 `app/rate_limiter.py`：TokenBucketRateLimiter + tenacity retry decorator + 单例
- [ ] 修改 `app/agent_handler.py`：`_call_llm()` 集成限流器 + 重试装饰器；`ChatOpenAI(max_retries=0)`
- [ ] `requirements.txt` 添加 `tenacity>=8.0`
- [ ] 测试文件添加 `rate_limit_pause` autouse fixture（22s 间隔）
- [ ] 验证：连续 10 次调用无 429 报错

## 其他考量

- **提工单调高配额**：若测试环境需要更高并发，联系华为云客服申请提升 MaaS RPM 配额（如 3 → 30）
- **不适用连接池/并发优化**：3 RPM 是 API 侧硬约束，客户端任何并发优化都会加剧限流
- **不适用 `ChatOpenAI(max_retries=N)`**：LangChain 默认重试无退避，对 rate limit 无效

## 参考

- Feature 1 Issue: `../features/feature-1-agent-skeleton/issue.md`
- ADR-005: MaaS
- ADR-009: deepagents
- AgentArts 文档: `../../architecture/cloud-service/agentarts.md`
