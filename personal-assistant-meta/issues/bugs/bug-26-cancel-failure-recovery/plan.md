# Bug 26 Implementation Plan

## 目标

在不耦合 Frontend/Service 流水线、不新增 Service API 的前提下，让 Web Chat 在
显式 cancellation 失败时保持安全且可恢复：同一 Conversation 不发送新
Invocation，用户可以重试停止，成功后恢复发送。

## 设计决策

1. Service 的幂等 cancel endpoint、Invocation registry、tombstone 与 Conversation
   lock 保持不变。
2. Client 增加轻量 cancellation coordinator，按 `conversation_id` 保存原
   `client_message_id` 和 `cancelling | cancel_failed` 状态。
3. 首次 Stop 最多执行两次 cancel 请求；最终失败后停止自动请求，由用户点击
   `Retry stop` 再次尝试。
4. Composer 继续使用 assistant-ui 的 `thread.isRunning` 表示本地 streaming，但
   cancellation 状态优先于 Send/Cancel 默认映射。
5. cancellation 失败不再抛入聊天消息流程；发送入口由 Composer 状态阻止，adapter
   仍保留顺序检查作为防御。

## 实施步骤

1. 新增 Client cancellation coordinator 和独立状态 store。
2. 将 `chat-adapter` 的 pending cancellation 逻辑迁移到 coordinator。
3. 更新 Composer：`cancelling` 显示禁用 spinner，`cancel_failed` 显示
   `Retry stop`，其余状态保留原 Send/Stop 行为。
4. 增加 coordinator、adapter 与 Composer 状态回归测试。
5. 同步 Frontend、Session、CI/CD 与测试策略文档。

## 验证

- `npm run test`
- `npm run build`
- 相关 full-stack E2E regression
- `gitnexus detect-changes`

## 明确排除

- capability negotiation endpoint
- Invocation status API
- cancellation 状态持久化
- Frontend/Service workflow 依赖
- assistant-ui Runtime 重构
