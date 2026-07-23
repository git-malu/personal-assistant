# Feature 14 Spike: Runtime Session、Cookie 与提前唤醒

> 日期：2026-07-14
> 状态：设计所需静态验证完成；只剩 Gateway method probe 和 latency measurement

## 结论摘要

1. AgentArts 官方 API 文档没有定义独立的 pre-warm/warm-up API。
2. `sessions-start` 不接收调用者提供的 Session ID，而是返回平台生成的另一个 ID。
3. 合法的 application-generated Session ID 可直接用于 Invocation。
4. 底层 Runtime instance 被平台回收后，相同 Session ID 可继续使用并触发隐式重建。
5. 因此选择 BFF random HttpOnly Cookie，不建立 Runtime lease。
6. 进入 Chat 的 Conversation list 是必要业务请求，也可提前触发 Runtime。
7. Conversation API 放在现有 FastAPI Service；BFF 不访问数据库。
8. Gateway 验证 JWT，FastAPI 从已验证 token 派生 `user_id`；BFF 不需要校验 JWT。
9. 不建立 `invocation_runs`，不自动 retry Agent Invocation。
10. Conversation 数据和并发测试统一使用 PostgreSQL；in-memory 只用于纯 Unit Test。
11. Invocation 与 Delete 使用 PostgreSQL session-level Advisory Lock。
12. Delete 使用 Checkpointer public API 和外键 cascade，不设计 soft delete。

## Spike 问题

1. AgentArts 是否存在有 contract 的预热 API？
2. `sessions-start` 是否允许指定已有 Session ID？
3. 自生成 Session ID 能否直接调用并在回收后复用？
4. 是否需要持久化 Runtime lease？
5. BFF 是否需要校验 JWT或访问数据库？
6. Conversation API 应部署在哪里？
7. 是否需要 Invocation Run ledger 和自动 retry？
8. 本地与集成测试应使用 SQLite、PostgreSQL 还是 in-memory？
9. Delete 是否需要 retention/后台 purge？
10. 如何跨 Runtime instance 互斥同一 Conversation？

## AgentArts API Evidence

来源：
`personal-assistant-meta/architecture/cloud-service/agentarts-api-pdf.pdf`
（文档版本 03，2026-06-11）。

### `StartRuntimeSession`

- Section：4.7.1.1
- URI：`POST /runtimes/{runtime_name}/sessions-start`
- request 没有 body，也没有 caller-supplied Session ID 参数
- 200 response 包含 `data.session_id`
- ID 允许英文字母、数字、`-`、`_`，最长 64 字符

文档没有定义：

- `ready` flag 或 readiness query；
- `expires_at`、TTL 或 session timeout；
- first-invocation latency guarantee；
- repeated start idempotency；
- “pre-warm”或“warm-up”语义。

因此不能用 `sessions-start` 预先启动 BFF 已生成的 Cookie ID，也不能把它描述为平台
保证的 ready API。

### `ExecuteRuntimeWithPrefix`

- Section：4.7.1.2
- URI：`POST /runtimes/{runtime_name}/invocations/{custom_path}`
- 需要 `url_match_type=PREFIX_MATCH`
- required headers 包含 Session ID 和 Authorization
- `X-Hw-Agentgateway-User-Id` 在平台文档中为 optional

PDF 以 POST 描述接口；项目已使用 GET callback/custom path，但 Feature 14 还需要 PATCH
和 DELETE。实现前用部署环境做一个窄 method probe，不从 FastAPI 能力反推 Gateway 行为。

### `ExecuteRuntime`

- Section：4.7.1.3
- URI：`POST /runtimes/{runtime_name}/invocations`
- required headers：Session ID、Authorization
- 当前 Web Chat 已使用该入口

### `StopRuntimeSession`

- Section：4.7.1.7
- URI：`POST /runtimes/{runtime_name}/sessions-stop`
- required headers：Session ID、Authorization
- 用途是销毁 Session 对应的 instance

Feature 14 不依赖该 API。logout 只删除 Cookie；平台负责临时 instance 的自动回收。

### 固定结论

> AgentArts 提供 Runtime Session lifecycle API；Personal Assistant 使用必要的业务初始化
> 请求实现 application-level warm-up。性能收益必须实测，不属于平台 API 保证。

## Runtime Session Reuse

已知条件：

- UUID v4 满足 AgentArts Session ID 字符和长度限制；
- application-generated ID 可直接用于 Invocation；
- Runtime instance 自动回收不使逻辑 Session ID 失效；
- 相同 ID 的下一次 Invocation 可隐式创建新 instance；
- 应用无需因为自动回收主动生成 replacement ID；
- 相同 ID 不代表物理 instance identity。

这个条件只说明正常自动回收后的复用。Feature 14 不依赖显式
`sessions-stop` 后再次复用同一 ID 的行为。

## Current Code Gaps

### Runtime ID ownership

当前：

```text
Browser localStorage generates agentarts-session-id
  -> Client sends x-hw-agentarts-session-id
  -> BFF forwards caller value
```

目标：

```text
Pages Function reads/generates pa_runtime_session HttpOnly Cookie
  -> BFF drops caller header
  -> BFF injects controlled Cookie value
  -> Client no longer sees or sends Runtime ID
```

### User identity

当前 Client 从 JWT payload 读取 user ID 并发送
`X-HW-AgentGateway-User-Id`；BFF 原样转发。Payload decode 不是签名验证，因此该 header
不能保护 Conversation ownership。

目标：

```text
Browser sends Authorization
  -> BFF forwards it without authorization decisions
  -> Gateway validates JWT
  -> FastAPI derives user_id from validated sub
```

2026-07-14 probe 已确认 Gateway 转发 Authorization 且部署入口没有 auth bypass，所以 BFF
不需要再实现一套 JWT validator。

### OAuth callback context

`functions/_shared/callback-context.js` 当前从 browser request 的 Session header 创建
`pa_oauth2_callback_session`。新 Client 停止发送 header 后，该 snapshot 会丢失。

目标是让 BFF Cookie resolver 把已解析的 Runtime ID 显式传给 callback helper。授权发起
后即使主 Cookie 轮换，callback 仍使用发起时 snapshot。用户身份继续由 Gateway JWT 和
signed state 决定。

### Invocation transport ownership

当前 `AgentHandler.handle_stream()` 会直接编码 SSE、发送 terminal `done=true`、把异常
转换成 error event，并在尚未输出 token 时对部分 Checkpointer error 重跑 graph；sync
`handle()` 也可能重跑。Feature 14 的 commit-before-done 与 no-retry contract 要求把
这些职责移到 Invocation Service：

- `AgentHandler` 只产生结构化非 terminal event；
- 异常向上传播；
- Agent execution 开始后不自动重跑；
- Invocation Service 在 assistant Message commit 后才生成 success terminal；
- sync 与 stream 使用同一个持久化 core。

### assistant-ui thread runtime

当前 `RuntimeProvider` 只有一个 `useLocalRuntime(chatAdapter)`，不能表达 Service-owned
Conversation list 和 per-thread history。已安装的 `@assistant-ui/react 0.14.x` 提供
`useRemoteThreadListRuntime`、`RemoteThreadListAdapter` 和 `ThreadHistoryAdapter`。
Feature 14 使用这些稳定边界：

- `remoteId=conversation_id`；
- remote list adapter 对接 Conversation CRUD；
- per-thread history adapter 只负责 load，`append` 不写库；
- Invocation Service 保持唯一 Message writer。

## Alternatives

| 方案 | 结论 | 原因 |
|------|------|------|
| Browser localStorage Runtime ID | Reject | JS-readable、caller-controlled，并与 Conversation 混合 |
| 从 user ID 确定性派生 Runtime ID | Reject | BFF 需要可信身份，且稳定标识增加关联性 |
| Service 保存 Runtime lease | Reject | 没有续租、抢占、后台 stop 或 ready/TTL contract |
| BFF 直连 PostgreSQL | Reject | 把业务授权和 DB 逻辑放到 edge |
| `sessions-start` 后保存返回 ID | Defer | 增加 lifecycle call，但没有文档化 warm-up 收益 |
| Random HttpOnly Cookie + implicit Invocation | **Choose** | 满足 routing reuse，状态最少 |
| `invocation_runs` + auto replay | Reject | 当前产品不要求透明重试，会引入 attempt/replay 状态机 |
| Stable `client_message_id` + no retry | **Choose** | 重复请求返回 409，用户明确重发表示新操作 |
| SQLite Store | Reject | 无法验证 JSONB、Advisory Lock 和 PostgreSQL concurrency |
| In-memory Store everywhere | Reject | 不持久、不能跨 Runtime |
| PostgreSQL Store + unit-test fake | **Choose** | 生产语义只有一套，纯规则测试仍然快 |
| Soft delete + purge worker | Reject | 没有 Trash/retention requirement |
| Immediate Checkpoint + cascade delete | **Choose** | 与用户点击永久删除的语义一致 |
| `asyncio.Lock` | Reject | 不能跨 Runtime instance |
| 长 `SELECT FOR UPDATE` transaction | Reject | 会在 LLM/SSE 全程占有 transaction |
| PostgreSQL session Advisory Lock | **Choose** | 跨进程互斥，无长 transaction，连接关闭自动释放 |

## PostgreSQL Spike

### Why no `invocation_runs`

固定行为：

- user message 在 Agent 调用前写入；
- `client_message_id` 在 Conversation 内唯一；
- duplicate 返回 409，不再次执行 Agent；
- assistant message commit 后才发送 terminal `done=true`；
- Browser、BFF、Service 都不自动 retry；
- 用户主动重发时创建新 ID。

进程在 partial SSE 与 assistant commit 之间退出时，刷新只恢复已提交的 user message。该
故障窗口对展示项目可接受，因此不增加 Run ledger、reconciliation API 或后台 worker。

### Advisory Lock

内部 `conversations.pk` 是 bigint，可直接用作 Advisory Lock key：

- 不需要 hash，也没有 hash collision；
- `pg_try_advisory_lock(pk)` 不阻塞；
- Invocation 和 Delete 使用同一 key；
- busy 返回 409；
- LLM stream 期间不保持数据库 transaction；
- `finally` unlock，connection close 也会释放 lock。

### Delete

当前锁定的 `AsyncPostgresSaver` 提供 `adelete_thread(thread_id)`。业务 Message 使用
`ON DELETE CASCADE`。Delete 在同一 Conversation lock 内先删除 business row，再调用
public API 清理 Checkpoint；清理失败时重复 Delete 可按已知 `thread_id` 重试。它不需要
解析 LangGraph 内部表，也不需要后台 purge。

## Why No Lease Store

持久 lease 适用于多个 worker 必须协调资源 owner、renewal、takeover 或 cleanup 的场景。
Feature 14 不需要这些能力：

- Cookie 已提供 Runtime routing-key reuse；
- Gateway JWT + FastAPI ownership 保护业务数据；
- Runtime 自动回收后可按相同 ID 重建；
- 没有后台 stop worker；
- 平台没有可镜像的 ready/TTL contract。

保存 lease 会产生一套应用必须维护、却无法从平台可靠校准的状态，所以删除该设计。

## Remaining Verification

### Blocking for implementation

| Probe | Expected |
|-------|----------|
| custom GET/POST/PATCH/DELETE | 到达预期 FastAPI route |
| Session header on custom path | FastAPI request 使用同一 ID routing |
| forged/expired JWT | Gateway 在 FastAPI 前拒绝 |
| forged user header | Service ownership 仍取 token `sub` |

其中 identity 部分 G0 已通过；method/header 的 G1 仍需执行。

### Non-blocking measurement

比较：

1. fresh Cookie -> direct Invocation；
2. fresh Cookie -> Conversation list -> same-Cookie Invocation。

记录 p50/p95 first SSE byte 和 first token。结果只决定是否可以声称 latency improvement，
不改变 Conversation list 和 Cookie architecture。

## Design Consequences

- Runtime Session ID 不再是业务主键。
- Runtime 被回收不会影响 Conversation 恢复。
- BFF 保持无数据库、无业务授权。
- 数据库只增加两张业务表和一个 OAuth nullable compatibility change。
- 不增加 Session lifecycle、lease、Run ledger、reconciliation、soft delete 或新部署组件。
- 实现验证范围收敛为 G1 Gateway route probe、G2 PostgreSQL integration tests 和 warm-up
  measurement。
