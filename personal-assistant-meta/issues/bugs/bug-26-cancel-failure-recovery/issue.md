---
status: in_progress
related: ["bug-23-cancelled-chat-keeps-conversation-busy", "feature-14-multi-session-runtime-prewarm"]
---

# Bug 26: Cancel 失败后 Conversation 无法恢复发送

## 现象

部署 `e734768d22b7212053c8a0bd3e98cae08b9e2b71` 后，用户在 Web Chat 中点击
Stop，再次发送消息时，Client 调用：

```text
POST /api/conversations/{conversation_id}/invocations/{client_message_id}/cancel
```

请求返回 `404 Not Found`。Client 在下一次 Invocation 前继续等待或重试同一
cancellation barrier，并将裸 `Not Found` 渲染为聊天错误；用户无法在该
Conversation 中继续发送。

现网观测显示 Frontend 与 Service 独立部署期间存在短暂版本错配：Frontend 已开始
调用新增 cancel endpoint，而部分 AgentArts Runtime 实例尚未提供该 route。现有
Client 没有把 cancellation failure 映射为可恢复的 Composer 状态。

## 预期行为

- Frontend 与 Service 流水线继续解耦，不建立永久部署依赖。
- cancel 未确认成功时，同一 Conversation 不显示或启用 Send，避免并发 Invocation。
- cancel 请求进行中时显示 `cancelling` 状态；有限自动重试仍失败后显示可操作的
  `Retry stop` 控件。
- Composer 输入框保持可编辑并保留草稿；New conversation 不受当前
  Conversation cancellation 状态影响。
- cancel 返回 `204` 后解除 barrier 并恢复 Send。
- `404`、timeout 或 `5xx` 不以裸错误文本写入聊天消息，也不会触发无限重试。

## 根因

Bug 23 引入的 cancellation barrier 正确保证了“上一轮取消完成后才能开始下一轮”，
但 Client 仅区分 cancellation 成功或失败，没有独立表达 `cancelling` 与
`cancel_failed` UI 状态。assistant-ui 的本地 `AbortSignal` 结束后，
`thread.isRunning` 已不足以表示 Service 端 Invocation 是否终止。

独立流水线本身不是缺陷；缺陷在于新增跨端 API 没有按兼容发布顺序先提供 Service
能力，同时 Client 无法从部署期间的 endpoint 404 中恢复。

## 修复范围

### In Scope

- 在 Client 中增加最小 Invocation lifecycle：
  `idle | running | cancelling | cancel_failed`。
- cancel 失败后保持停止类控件，将其变为 `Retry stop`；同一 Conversation 的 Send
  保持不可用。
- 对 cancellation 使用最多 1-2 次有限自动重试；之后仅由用户显式重试。
- cancel 成功后清理 pending cancellation 并恢复 Send。
- 将 cancellation transport/API error 与聊天消息错误分离，禁止渲染裸
  `Not Found`。
- 补充 Client regression tests，并记录跨端 API 的兼容发布顺序：Service additive
  change 验证完成后，再独立发布 Frontend consumer。

### Out of Scope

- 合并或永久串联 Frontend、Service deployment workflows。
- 新增 capability negotiation endpoint。
- 新增 Invocation status 查询 API。
- 将 Client cancellation 状态持久化到数据库或浏览器存储。
- 修改现有 Service cancellation registry、tombstone、Conversation lock 或幂等
  `204` 语义。
- 重构 assistant-ui Runtime 或 Composer 组件体系。

## 验收标准

- [ ] `running` 状态显示 Stop；点击后进入 `cancelling`。
- [ ] `cancelling` 状态不显示 Send，自动重试次数有明确上限。
- [ ] cancel 最终失败后显示可点击的 `Retry stop`，不显示 Send。
- [ ] cancellation 失败期间输入框可编辑，已有草稿不会丢失。
- [ ] `404`、timeout 和 `5xx` 不会作为裸聊天错误消息显示。
- [ ] 用户点击 `Retry stop` 时复用原 `client_message_id`；收到 `204` 后恢复 Send。
- [ ] New conversation 在当前 Conversation cancel 失败时仍可使用。
- [ ] Service 的幂等 cancel endpoint 与 Conversation lock 行为保持不变。
- [ ] Frontend 与 Service workflows 保持独立，发布文档明确 additive Service-first
      rollout。
- [ ] Client tests 和 production build 通过；相关 E2E regression test 通过。

## Affected Specs / Architecture Docs

| 文档 | 影响 |
|------|------|
| `architecture/frontend_architecture.md` | 补充 cancellation lifecycle 与 Composer 控件映射 |
| `architecture/session-state-management.md` | 区分本地 Abort、cancellation barrier 与 cancel failure recovery |
| `architecture/devops/cicd.md` | 明确解耦流水线下的 additive Service-first 兼容发布 |
| `architecture/devops/test/test-strategy.md` | 增加 cancel failure/retry 与跨版本回归测试 |

## 参考实现

| 文件 | 关联点 |
|------|--------|
| `personal-assistant-client/src/lib/chat-adapter.ts` | pending cancellation sequencing 与 retry |
| `personal-assistant-client/src/lib/chat/chat-api-client.ts` | cancel API error 分类与 timeout |
| `personal-assistant-client/src/components/assistant-ui/thread.tsx` | Stop、Retry stop、Send 控件状态 |
| `personal-assistant-client/src/lib/chat-adapter.test.ts` | cancellation lifecycle regression tests |
| `personal-assistant-client/src/lib/chat/chat-api-client.test.ts` | cancel 404/timeout/retry tests |
