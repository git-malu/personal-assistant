---
status: backlog
---

# Feature: 基于 LangGraph Checkpoint 的 Session 内多轮上下文持久化

本 Feature 通过 LangGraph 框架原生的 Checkpointer 机制，使 Agent 在同一 Session 内具备多轮对话上下文连续能力。Fix 当前 `session_id` 已提取但未使用的缺陷，为 Feature 2（Memory）提供前置的连贯 session 状态基础。

---

## 背景

当前系统存在一个**基础功能缺陷**：AgentArts Gateway 注入的 `X-AgentArts-Session-Id` header 在 FastAPI 层已被提取（`app/main.py:97`），但在调用 deepagents Agent 时完全未传递——`agent.ainvoke()` 和 `agent.astream_events()` 均无 `config` 参数，导致底层每次请求都是一个全新的无状态调用。

**影响**：多轮对话完全不工作。用户说"我叫小明"后，紧接着问"我叫什么名字？"，Agent 无法回忆上一条消息。

本 Feature 采用 LangGraph 框架原生的 **Checkpointer** 机制解决此问题。以下三种方案经过四问闸门评估，方案 C 为唯一全部通过的选择：

### 方案对比

| 维度 | A: 客户端驱动 | B: 服务端 Store | C: LangGraph Checkpoint |
|------|:---:|:---:|:---:|
| 代码量 | 最少 | 中 | **最小**（框架已就绪） |
| 基础设施 | 无 | Redis/PG | MemorySaver→SqliteSaver→PostgresSaver 渐进 |
| 多轮上下文 | ✅ | ✅ | ✅ |
| 跨 Session 记忆 | ❌ | 需叠加 Memory 层 | 需叠加 Memory 层 |
| 中断恢复 | ❌ | ❌ | ✅（graph node 位置） |
| Token 效率（不重传历史） | ❌ | ✅ | ✅ |
| 并发扩展 | ✅ Trivial | 中等 | 取决于 checkpointer 后端 |
| 防御客户端篡改 | ❌ | ✅ | ✅ |
| 与现有 deepagents 集成 | — | — | 一行 config 改动 |
| **四问闸门** | ❌ 3 项未通过 | ⚠️ 部分通过 | ✅ **全部通过** |

**方案 A（客户端驱动）**：Client 每轮请求带完整 `messages[]` 历史。问题：客户端不可信（无 Defense in Depth）、请求体膨胀、token 浪费、不支持 graph 状态恢复。

**方案 B（服务端 Session Store）**：后端 Redis/PG 自建消息存储。问题：在 LangGraph 技术栈下重复造轮子，只存扁平消息丢失 graph state（node 位置、中断点、tool call 状态）。

**方案 C（LangGraph Checkpoint）✅**：框架原生持久化，`checkpointer` + `config={"configurable": {"thread_id": session_id}}`。改动量最小（~5 行），存完整 AgentState。

### Checkpoint vs Memory 职责分界线

```
Checkpoint (本 Feature): "这一轮对话进行到哪了？上次 tool call 返回了什么？"
Memory   (Feature 2):    "用户偏好简洁回答（从 3 周前的对话中学到的）"
```

| 维度 | Checkpoint（本 Feature） | Memory（Feature 2） |
|------|-------------------------|---------------------|
| **存储内容** | AgentState — messages, node 位置, 中断点 | 语义/偏好/情景记忆（自然语言摘要） |
| **作用域** | 同一 thread_id（session）内 | 跨 session，跨用户 |
| **生命周期** | session 级别（短期） | 长期持久化 |
| **恢复方式** | 自动——checkpointer 按 thread_id 恢复 | 搜索——按 query 检索 top-k |
| **实现机制** | LangGraph Checkpoint API | AgentArts Memory SDK |

---

## 范围

### 涉及

- 在 `create_deep_agent()` 中注入 LangGraph Checkpointer（渐进式后端：`MemorySaver` → `SqliteSaver`）
- 在 `AgentHandler.handle()` 中构造并传递 `config={"configurable": {"thread_id": session_id}}` 给 `agent.ainvoke()`
- 在 `AgentHandler.handle_stream()` 中：
  - 添加 `session_id` 参数（当前签名缺少）
  - 传递相同 config 给 `agent.astream_events()`
- 在 `app/main.py` 流式路由中将 `X-AgentArts-Session-Id` header 透传给 `handle_stream()`
- 使用 user-scoped thread_id 格式：`"{user_id}:{session_id}"`，从源头杜绝跨用户 session 泄露
- 当 `session_id` 缺失时（本地开发/非 Gateway 场景），通过 **cookie 持久化降级**：首次请求设置 `Set-Cookie: x-anonymous-session-id=<uuid4>`，后续请求自动携带，实现本地多轮对话
- 验证多轮对话：同一 session 内 Agent 能回忆前序对话、不同 session 间隔离
- 更新 `backend_architecture.md` 和 `overall_architecture.md` 反映 Checkpointer 组件

### Checkpointer 后端渐进路线

| 阶段 | 后端 | 场景 | 持久化 |
|------|------|------|:---:|
| **开发/调试** | `MemorySaver` | 本地开发、单元测试 | ❌ 进程重启丢失 |
| **本地持久化** | `SqliteSaver` | 本地开发需保留 session | ✅ 磁盘文件 |
| **生产环境** | `PostgresSaver` | 多副本共享、云端部署 | ✅ RDS PostgreSQL |

通过环境变量切换：默认 `MemorySaver`，设置 `SQLITE_DB_PATH` 则用 `SqliteSaver`，设置 `POSTGRES_DSN` 则用 `PostgresSaver`。

### 实施路线

```
短期（本 Feature）──→ 中期（Feature 2）──→ 长期（脱离 AgentArts）
─────────────────    ─────────────────    ────────────────────────
注入 MemorySaver     叠加 AgentArts        Checkpoint 接管 Session State
传 config+thread_id   Memory 层           自建 auth middleware
修复 handle_stream    Checkpoint 管短期    渠道映射接管路由
Cookie 降级本地开发    Memory 管长期        三层解耦，独立替换
```

### 不涉及

- 跨 Session 语义记忆提取/搜索（Feature 2）
- 自建 Auth Middleware 或 JWT 身份校验（Feature 4）
- Session 生命周期管理：TTL 过期、超时清理、显式结束
- 多渠道路由映射（Web Chat / 飞书 / OfficeClaw 到 session 的映射表）
- PostgresSaver 生产部署（短期用 MemorySaver/SqliteSaver，PostgresSaver 留到后续独立改进）
- **客户端改动**：生产环境 Gateway 自动注入 session header，客户端无需任何改动。本地开发通过后端 cookie 降级方案闭环，无需前端配合。页面刷新后 UI 历史恢复属后续增强，不在本 Feature 范围。

---

## 验收标准

### AC1：非流式多轮对话上下文保持

- [ ] 发送 `POST /invocations`，同一 `X-AgentArts-Session-Id`，第一轮消息："我叫小明"
- [ ] 同一 session 第二轮消息："我叫什么名字？"
- [ ] Agent 回答包含"小明"（而非"我不知道"）

### AC2：流式多轮对话上下文保持

- [ ] 发送 `POST /invocations`，`{"stream": true}`，同一 `X-AgentArts-Session-Id`，第一轮消息设定事实
- [ ] 同一 session 第二轮流式请求确认 Agent 记住前序上下文
- [ ] SSE 流式渲染正常，无协议错误

### AC3：不同 Session 间上下文隔离

- [ ] Session A 第一轮："我叫小红"
- [ ] Session B（不同 `X-AgentArts-Session-Id`）第一轮："我叫什么名字？"
- [ ] Session B 的回答不包含 Session A 的信息（"小红"）

### AC4：跨用户 Session 隔离（user-scoped thread_id）

- [ ] 用户 A（`X-AgentArts-User-Id: user_a`）Session X 发送敏感信息
- [ ] 用户 B（`X-AgentArts-User-Id: user_b`）伪造请求，将 Header 中 `X-AgentArts-Session-Id` 设为 Session X 的值
- [ ] 用户 B 无法读取用户 A 的会话状态（底层 `thread_id` 为 `user_b:session_x` ≠ `user_a:session_x`）

### AC5：缺失 session_id 的降级行为（Cookie 方式）

- [ ] 请求不带 `X-AgentArts-Session-Id` header（模拟本地开发/直连容器场景）
- [ ] 首次请求：后端生成 `uuid4()`，通过 `Set-Cookie: x-anonymous-session-id=<uuid4>` 返回浏览器
- [ ] 同一浏览器后续请求自动携带 cookie → 后端识别为同一 session → 多轮对话正常
- [ ] 不同浏览器（不同 cookie）之间相互隔离

### AC6：handle_stream 接口改造

- [ ] `AgentHandler.handle_stream()` 签名包含 `session_id: str | None = None` 参数
- [ ] `session_id` 经 user-scoped 处理后传入 `agent.astream_events(config=...)`

### AC7：Checkpointer 后端可切换

- [ ] 默认使用 `MemorySaver`（进程内内存，开发/调试用）
- [ ] 设置环境变量 `SQLITE_DB_PATH` 后使用 `SqliteSaver`，本地磁盘持久化
- [ ] 重启 FastAPI 后，SqliteSaver 持久化的 session 上下文仍然可用

### AC8：不影响现有功能

- [ ] `/ping` 健康检查正常
- [ ] 原有单元测试全部通过
- [ ] 非流式和流式可在同一 session 内交替使用

---

## 四问闸门（Four-Question Gate）

> 所有方案必须通过四道闸门。本 Feature 采用方案 C（LangGraph Checkpoint）。

| 问题 | 答案 | 说明 |
|------|:----:|------|
| **Is it best practice?** | **Yes** | Separation of Concerns：Checkpointer 将状态存储（基础设施层）与 Agent 逻辑（业务层）解耦。SOLID DIP：Agent 依赖 `BaseCheckpointSaver` 抽象接口而非具体存储实现。Defense in Depth：user-scoped `thread_id` 在框架层面防范跨用户数据泄露。 |
| **Is it industry standard?** | **Yes** | LangGraph Checkpointer 是 LangChain 生态构建生产级 Agent 的核心能力。LangSmith 等可观测平台原生支持 Checkpoint 追踪。AWS multi-agent 参考架构、LangChain 官方 production 指南均推荐此模式。 |
| **Is it conventional?** | **Yes** | 对于任何基于 LangGraph 的 Agent 应用，注入 checkpointer + 传 `thread_id` 是最标准、文档最完善的模式。deepagents 的 `create_deep_agent()` API 显式暴露 `checkpointer=` 参数，表明框架设计者预期了这种用法。熟悉 LangChain 生态的开发者对此不会感到意外。 |
| **Is it modern?** | **Yes** | LangGraph 1.0（2025）将 checkpoint 强化为一等公民，支持 durable execution 和 graph-state recovery。deepagents 是该方向的最新封装。Checkpoint 比传统扁平消息存储更 modern——不仅存消息历史，还存 graph node 执行位置，支持中断恢复和 Human-in-the-loop。 |

---

## 风险与缓解

| 风险 | 严重度 | 缓解措施 |
|------|:------:|----------|
| **MemorySaver 重启丢失** | Medium | 短期可接受（开发阶段）。提供 `SQLITE_DB_PATH` 环境变量切换到 `SqliteSaver`。生产环境后续切换到 `PostgresSaver`（依赖 Feature 1.2 DB setup）。严禁 `MemorySaver` 流入云端生产配置。 |
| **handle_stream 缺少 session_id** | High | 当前 `handle_stream()` 不接收 `session_id` 参数，流式请求将无法利用 Checkpoint。**本 Feature 必须在 handle_stream 签名中追加 session_id 并透传 config**——这是不可跳过的核心改动。 |
| **同一 session 并发请求导致写冲突** | Medium | 用户快速连续发送消息时，同一 `thread_id` 的并发写入可能触发 Checkpointer 乐观锁冲突。缓解：在 `AgentHandler` 入口对相同 `thread_id` 加协程锁（`asyncio.Lock`），或对飞书 Webhook 做去重幂等。此风险在当前低并发阶段可控，标记为已知需后续关注。 |
| **Checkpoint 存储膨胀** | Low | LangGraph Checkpointer 默认全量保留，无 TTL 过期机制。缓解：短期数据量极小（开发/测试阶段），明确记录需后续引入定期清理 Cron task。在 PostgresSaver 阶段一并处理。 |
| **deepagents/checkpointer API 版本差异** | Low | `MemorySaver` vs `InMemorySaver` 等类名可能随 deepagents/LangGraph 版本变化。缓解：实现前确认已安装版本的实际 import 路径，不硬编码类名。 |

---

## 受影响的架构文档

### 必须更新

| 文档 | 更新内容 |
|------|----------|
| `architecture/backend_architecture.md` §3（Agent 处理逻辑） | 增加 Checkpointer 初始化 + `handle()`/`handle_stream()` 的 `config` 传递说明 |
| `architecture/overall_architecture.md` §1.2（技术选型表） | 新增一行：`Session State \| LangGraph Checkpoint \| 短期会话状态持久化` |

### 应引用

| 文档 | 引用方式 |
|------|----------|
| `ADR-009: deepagents` | 引用确认 `create_deep_agent(checkpointer=...)` 是框架原生能力 |
| `ADR-002: LangGraph`（Superseded） | 引用 §30 "StateGraph + Checkpointer，支持中断恢复" |
| `issues/features/backlog/feature-2-memory/issue.md` | 引用说明 Checkpoint 与 Memory 的互补关系，建议 Feature 2 将本 Feature 追加为前置依赖 |

### 不直接受影响

- `architecture/cloud-service/agentarts.md` — AgentArts Gateway 注入 `X-AgentArts-Session-Id` 的行为不变
- `architecture/devops/agentarts-deploy-runbook.md` — 部署流程不变（Checkpointer 后端切换不涉及容器/部署变更）

---

## 依赖

- Feature 1（Agent 骨架 + Web Chat）— 需要 `app/agent_handler.py` 和 `app/main.py` 存在
- 无外部服务依赖（Checkpointer 在容器内自包含）

## 被依赖

- **Feature 2（Memory 集成）** — 建议将本 Feature 追加为前置依赖：只有当 session 本身是连贯的，跨 session 的语义记忆提取才有意义

---

## 参考

- [LangGraph Persistence Docs](https://langchain-ai.github.io/langgraph/how-tos/persistence/)
- [deepagents Customization Docs](https://docs.langchain.com/oss/python/deepagents/customization) — `create_deep_agent(checkpointer=...)` API
- `ADR-009`: deepagents 替代裸 LangGraph
- `ADR-002`: LangGraph 选型（Superseded，§30 已提及 Checkpointer）
- `architecture/backend_architecture.md` — 当前 Agent 处理逻辑
- `architecture/overall_architecture.md` — 技术选型表
- `issues/features/backlog/feature-2-memory/issue.md` — Memory 集成（建议追加本 Feature 为前置依赖）
