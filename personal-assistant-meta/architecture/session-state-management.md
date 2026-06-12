# Personal Assistant — Session 状态管理架构

> 版本：v1.0 | 状态：Implemented | 关联 issue：[feature-session-checkpoint](../issues/features/feature-session-checkpoint/issue.md)

---

## 1. 问题域

Personal Assistant 的 Session 状态管理涉及两个正交维度：

| 维度 | 问题 | 时间跨度 | 典型场景 |
|------|------|----------|----------|
| **Q1: 单 Session 多轮** | 同一对话中 Agent 如何记住前序消息？ | 秒～分钟 | 用户说"我叫小明"，紧接着问"我叫什么名字？" |
| **Q2: 跨 Session 恢复** | 用户关闭浏览器后重新打开，如何继续昨天的对话？ | 小时～天 | 用户昨天讨论了项目方案，今天想接着聊 |

两个问题共享同一个底层机制——**LangGraph Checkpoint**——但解决的层次不同。Q1 是核心能力，Q2 是 Q1 + 持久化 + Session 发现/路由的组合。

---

## 2. 两阶段状态模型

系统采用 **Checkpoint（短期） + Memory（长期）** 两阶段状态分层：

```mermaid
flowchart TB
    subgraph ShortTerm["短期状态 — LangGraph Checkpoint"]
        CP[("Checkpointer<br/>keyed by thread_id")]
        CP --> State["AgentState<br/>├── messages[] 完整对话历史<br/>├── node 位置 / 中断点<br/>└── tool_call 状态"]
    end

    subgraph LongTerm["长期状态 — AgentArts Memory"]
        MEM[("Memory Service<br/>keyed by actor_id")]
        MEM --> Semantic["Semantic Memory<br/>语义记忆 — 知识/事实"]
        MEM --> Preference["Preference Memory<br/>偏好记忆 — 用户习惯"]
        MEM --> Episodic["Episodic Memory<br/>情景记忆 — 历史对话摘要"]
    end

    CP -.->|"对话结束 → 语义抽取"| MEM
    MEM -.->|"新 Session 建立 → 上下文注入"| CP
```

### 职责分界线

```
Checkpoint: "这一轮对话进行到哪了？上次 tool call 返回了什么？"
Memory:     "用户偏好简洁回答（从 3 周前的对话中学到的）"
```

| 维度 | Checkpoint（短期） | Memory（长期） |
|------|-------------------|---------------|
| **存储内容** | AgentState — messages, node 位置, 中断点 | 语义/偏好/情景记忆（自然语言摘要） |
| **作用域** | 同一 `thread_id`（session）内 | 跨 session，跨用户 |
| **生命周期** | Session 级别（小时～天） | 长期持久化（月～年） |
| **恢复方式** | 自动——Checkpointer 按 `thread_id` 恢复 | 搜索——按 query 检索 top-k |
| **实现机制** | LangGraph Checkpoint API | AgentArts Memory SDK |
| **数据粒度** | 原始消息（完整对话历史） | 摘要/embedding（压缩后的语义） |
| **访问模式** | exact key lookup（`thread_id`） | semantic search（相似度检索） |

---

## 3. Q1: 单 Session 多轮上下文保持

### 3.1 问题本质

`session_id` 从 header 提取后**未传递给 Agent**：

```python
# 修复前代码（有缺陷）
result = await self.agent.ainvoke(
    {"messages": [{"role": "user", "content": message}]}
    # ❌ 没有 config={"configurable": {"thread_id": ...}}
)
```

每次请求都是全新调用，Agent 不记得上一轮说了什么。多轮对话完全不工作。

### 3.2 解决方案：LangGraph Checkpointer

LangGraph 原生提供 **Checkpointer** 机制：将 AgentState 按 `thread_id` 持久化，每次调用自动恢复前序状态。

```mermaid
sequenceDiagram
    actor User as 用户
    participant GW as Gateway
    participant API as FastAPI /invocations
    participant AH as AgentHandler
    participant CP as Checkpointer
    participant LLM

    Note over User,LLM: === 第 1 轮：建立 Session ===
    User->>GW: "我叫小明"
    GW->>API: x-hw-agentarts-session-id: sess_abc
    GW->>API: X-HW-AgentGateway-User-Id: user_x
    API->>AH: handle(message, user_id="user_x", session_id="sess_abc")
    AH->>CP: get_state(thread_id="user_x:sess_abc")
    CP-->>AH: null（新 session）
    AH->>LLM: messages=[{role:"user", content:"我叫小明"}]
    LLM-->>AH: "好的，记住了，你叫小明"
    AH->>CP: put_state(messages=[user:"我叫小明", assistant:"好的..."])
    AH-->>User: "好的，记住了，你叫小明"

    Note over User,LLM: === 第 2 轮：同一 Session ===
    User->>GW: "我叫什么名字？"
    GW->>API: x-hw-agentarts-session-id: sess_abc
    GW->>API: X-HW-AgentGateway-User-Id: user_x
    API->>AH: handle(message, user_id="user_x", session_id="sess_abc")
    AH->>CP: get_state(thread_id="user_x:sess_abc")
    CP-->>AH: AgentState(messages=[user:"我叫小明", assistant:"好的..."])
    AH->>LLM: messages=[user:"我叫小明", assistant:"好的...", user:"我叫什么名字？"]
    LLM-->>AH: "你叫小明"
    AH->>CP: put_state(追加新消息)
    AH-->>User: "你叫小明"
```

### 3.3 核心代码改动

```python
# === 改动 1: create_deep_agent() 注入 Checkpointer ===

from langgraph.checkpoint.memory import InMemorySaver

class AgentHandler:
    def __init__(self):
        self.model = get_model()
        self.checkpointer = self._init_checkpointer()  # 新增
        self.agent = create_deep_agent(
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            tools=[],
            checkpointer=self.checkpointer,  # ✅ 新增
        )

    def _init_checkpointer(self):
        """按环境变量选择 Checkpointer 后端（异步安全）。"""
        if os.environ.get("POSTGRES_DSN"):
            from langgraph.checkpoint.postgres import PostgresSaver
            return PostgresSaver.from_conn_string(os.environ["POSTGRES_DSN"])
        if os.environ.get("SQLITE_DB_PATH"):
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            return AsyncSqliteSaver.from_conn_string(os.environ["SQLITE_DB_PATH"])
        return InMemorySaver()  # 默认：进程内存（开发调试）

# === 改动 2: handle() 传递 config ===

    async def handle(self, message: str, user_id: str = "anonymous",
                     session_id: str | None = None) -> str:
        config = self._build_config(user_id, session_id)  # ✅ 新增
        result = await self.agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config=config,  # ✅ 新增
        )
        return result["messages"][-1].content

# === 改动 3: handle_stream() 签名 + config ===

    async def handle_stream(self, message: str, user_id: str = "anonymous",
                            session_id: str | None = None) -> AsyncGenerator[str, None]:
        config = self._build_config(user_id, session_id)  # ✅ 新增
        async for event in self.agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            version="v2",
            config=config,  # ✅ 新增
        ):
            ...

# === 改动 4: user-scoped thread_id ===

    @staticmethod
    def _build_config(user_id: str, session_id: str | None) -> dict:
        """构造 LangGraph config，thread_id = {user_id}:{session_id}。

        user-scoped 设计从源头杜绝跨用户 session 泄露：
        - 用户 A 的 session_abc → thread_id = "user_a:sess_abc"
        - 用户 B 伪造 header session_abc → thread_id = "user_b:sess_abc"
        - 两个 thread_id 不同，Checkpointer 返回不同状态
        """
        sid = session_id or "default"
        return {"configurable": {"thread_id": f"{user_id}:{sid}"}}
```

### 3.4 AgentArts Gateway Header 规范

生产环境中，AgentArts Gateway 传递以下 header 给后端容器：

| Header | 示例值 | 说明 |
|--------|--------|------|
| `x-hw-agentarts-session-id` | `sess_abc` | 会话 ID，由客户端生成并传递（必选） |
| `X-HW-AgentGateway-User-Id` | `user_x` | 用户 ID，由 Gateway 认证后注入 |

后端 `main.py` 读取方式：

```python
user_id = request.headers.get("X-HW-AgentGateway-User-Id", "anonymous")
session_id = request.headers.get("x-hw-agentarts-session-id")
if not session_id:
    raise HTTPException(status_code=400, detail="x-hw-agentarts-session-id header is required")
```

> **强校验**：`x-hw-agentarts-session-id` 在**所有环境**（本地开发 + 生产）均为强制必选参数。生产环境由 AgentArts Gateway 校验（缺失返回 400），本地开发由后端 FastAPI 校验（缺失返回 400）。两端行为完全一致，实现 Dev-Prod Parity。

### 3.5 客户端 Session ID 持久化

AgentArts Gateway 将 `x-hw-agentarts-session-id` 标记为**必选**——客户端必须自行生成并携带。若缺失，Gateway 直接返回 400。

`chat-adapter.ts` 通过 `localStorage` 持久化 session ID：

```typescript
function getSessionId(): string {
  const key = "agentarts-session-id";
  try {
    const stored = localStorage.getItem(key);
    if (stored) return stored;
    const id = crypto.randomUUID();
    localStorage.setItem(key, id);
    return id;
  } catch {
    return crypto.randomUUID(); // localStorage 不可用时降级
  }
}

// 每轮请求自动附带
const headers = {
  "x-hw-agentarts-session-id": getSessionId(),
  // ...
};
```

**行为说明**：
- 首次加载 → `crypto.randomUUID()` → 存入 `localStorage`
- 后续请求 → 自动附带持久化的 session ID
- 同一浏览器同一设备内，关闭重开页面后 session 保持不变
- `localStorage` 不可用时（私密模式/禁用），回退为每次生成新 UUID

### 3.6 thread_id 安全模型

```mermaid
flowchart LR
    subgraph UserA["用户 A"]
        ReqA["请求<br/>User-Id: user_a<br/>Session-Id: sess_abc"]
    end
    subgraph UserB["用户 B（攻击者）"]
        ReqB["伪造请求<br/>User-Id: user_b<br/>Session-Id: sess_abc"]
    end

    ReqA -->|"thread_id=user_a:sess_abc"| CPA[("Checkpoint State A")]
    ReqB -->|"thread_id=user_b:sess_abc"| CPB[("Checkpoint State B<br/>（与 A 隔离）")]

    CPA -.- CPA
    CPB -.- CPB
```

**关键安全属性**：`thread_id` 由 `{user_id}:{session_id}` 拼接而成，而非直接用 `X-AgentArts-Session-Id` header 值。即使攻击者伪造 header 中的 `session_id`，`user_id`（来自认证层，不可伪造）会使其访问到不同的 checkpoint 存储键。

---

## 4. Q2: 跨 Session 恢复（重启历史会话）

### 4.1 问题分解

"重启历史会话"包含三个子问题：

| 子问题 | 技术挑战 | 解决方案 |
|--------|----------|----------|
| **持久化** | Checkpoint 进程重启后必须存活 | Checkpointer 后端渐进：MemorySaver → SqliteSaver → PostgresSaver |
| **发现** | 用户如何找到昨天的会话？ | Session 列表 API（后续 Feature） |
| **路由** | 多种渠道（Web Chat / 飞书 / OfficeClaw）如何映射到同一个 Session？ | Session 映射表（后续 Feature） |

### 4.2 持久化：Checkpointer 后端选择

```mermaid
flowchart LR
    Dev["开发/调试"] -->|"InMemorySaver<br/>进程内存"| DevNote["❌ 重启丢失<br/>✅ 零配置<br/>✅ 最快"]
    Local["本地持久化"] -->|"AsyncSqliteSaver<br/>磁盘文件"| LocalNote["✅ 重启保留<br/>✅ 单文件<br/>⚠️ 单进程"]
    Prod["生产环境"] -->|"PostgresSaver<br/>RDS PostgreSQL"| ProdNote["✅ 多副本共享<br/>✅ 高可用<br/>⚠️ 需要 DB 基础设施"]
```

> **异步安全**：服务使用 `ainvoke()` / `astream_events()` 异步调用，必须使用异步 Checkpointer 变体（`AsyncSqliteSaver`、`AsyncPostgresSaver`）。`InMemorySaver` 本身 async-safe。同步版本（`SqliteSaver`）会阻塞 event loop。

环境变量驱动切换：

```bash
# 本地开发（默认，重启丢失）
# 无需设置

# 本地持久化
export SQLITE_DB_PATH=/data/checkpoints.db

# 生产环境
export POSTGRES_DSN=postgresql://user:pass@rds-host:5432/checkpoints
```

### 4.3 Session 发现与路由（架构预留）

当前 scope（feature-session-checkpoint）聚焦 Checkpoint 注入和单 Session 多轮，以下为架构预留设计：

#### Session 列表 API（预留）

```python
# GET /sessions?user_id={user_id}
# 返回用户的历史 session 列表
#
# 实现：查询 Checkpointer 中所有 thread_id 前缀为 {user_id}: 的状态
# 或通过独立的 sessions 表管理元数据（创建时间、最后活跃时间、标题摘要）
```

#### 渠道 → Session 映射（预留）

```mermaid
flowchart TB
    subgraph Channels["接入渠道"]
        WC["Web Chat<br/>session 由 Gateway 注入"]
        FS["飞书<br/>session = chat_id"]
        OC["OfficeClaw<br/>session 由 Gateway 注入"]
    end

    subgraph Mapping["Session 映射层（后续 Feature）"]
        Map["channel:channel_id → thread_id"]
    end

    subgraph State["Checkpoint"]
        CP[("AgentState")]
    end

    WC --> Map
    FS --> Map
    OC --> Map
    Map --> CP
```

**设计原则**：每种渠道的"对话标识"（Web Chat 的 Gateway session_id / 飞书的 chat_id / OfficeClaw 的 Gateway session_id）映射为统一的 `thread_id`。映射表由后续 Feature 独立实现，Checkpoint 层不感知渠道差异。

### 4.4 客户端视角：Session ID 生命周期

```mermaid
sequenceDiagram
    actor User as 用户
    participant Client as Web Chat
    participant LS as localStorage
    participant GW as AgentArts Gateway
    participant API as Backend
    participant CP as Checkpointer

    Note over User,CP: === 场景：首次打开 Web Chat ===
    User->>Client: 打开页面
    Client->>LS: getItem("agentarts-session-id")
    LS-->>Client: null（首次访问）
    Client->>Client: crypto.randomUUID() → sess_new
    Client->>LS: setItem("agentarts-session-id", sess_new)

    User->>Client: "我叫小明"
    Client->>GW: POST /invocations<br/>x-hw-agentarts-session-id: sess_new
    GW->>API: x-hw-agentarts-session-id: sess_new<br/>X-HW-AgentGateway-User-Id: user_x
    API->>CP: get_state(thread_id="user_x:sess_new")
    CP-->>API: null（新 session）
    API-->>Client: "好的，记住了，你叫小明"

    Note over User,CP: === 场景：关闭浏览器后重新打开 ===
    User->>Client: 重新打开页面
    Client->>LS: getItem("agentarts-session-id")
    LS-->>Client: sess_new（已持久化）

    User->>Client: "我叫什么名字？"
    Client->>GW: POST /invocations<br/>x-hw-agentarts-session-id: sess_new
    GW->>API: x-hw-agentarts-session-id: sess_new<br/>X-HW-AgentGateway-User-Id: user_x
    API->>CP: get_state(thread_id="user_x:sess_new")
    CP-->>API: AgentState（前序对话历史）
    API-->>Client: "你叫小明"

    Note over User,CP: === 场景：换浏览器/换设备 ===
    User->>Client: 新设备打开 Web Chat
    Client->>LS: getItem("agentarts-session-id")
    LS-->>Client: null（新环境）
    Client->>Client: crypto.randomUUID() → sess_alt
    Note over Client,CP: 全新的 session_id，Checkpoint 从零开始<br/>跨设备 session 恢复需后续 Feature 的 Session 列表 API
```

**关键点**：
- Session ID 由**客户端生成**（`crypto.randomUUID()`），存于 `localStorage`
- AgentArts Gateway **不自动注入** session ID——客户端必须自行携带（必选参数）
- 同一浏览器同一设备内，关闭重开页面后 session 保持不变（localStorage 持久化）
- 跨设备/跨浏览器的 session 恢复需后续 Feature 的 Session 列表 API 支持

---

## 5. 两层状态如何协同

```mermaid
flowchart TB
    subgraph SessionFlow["单次 Session 生命周期"]
        Start["用户发起对话"] --> LoadCP["1. Checkpointer 恢复<br/>AgentState（完整消息历史）"]
        LoadCP --> LoadMem["2. Memory 注入<br/>偏好/知识/历史摘要（语义上下文）"]
        LoadMem --> Merge["3. 合并上下文 → LLM<br/>messages + memory_context"]
        Merge --> Run["4. Agent 执行<br/>ReAct loop + tool calls"]
        Run --> SaveCP["5. Checkpointer 持久化<br/>完整 AgentState"]
        SaveCP --> SaveMem["6. Memory 抽取<br/>语义摘要 → 长期记忆"]
        SaveMem --> End["返回响应"]
    end

    Start -.->|"同一 session（秒级）"| LoadCP
    Start -.->|"跨 session（天级）"| LoadMem
    SaveCP -.->|"短期闭环"| LoadCP
    SaveMem -.->|"长期闭环"| LoadMem
```

**协同关系**：

1. **Checkpoint 是 Memory 的输入源**：只有当前 Session 的对话是连贯的（Checkpoint 保障），从中提取的语义记忆才有质量
2. **Memory 是 Checkpoint 的上下文增强**：新 Session 开始时，Checkpoint 为空，Memory 注入的偏好/知识让 Agent 不至于"完全失忆"
3. **时间尺度互补**：Checkpoint 管秒～天，Memory 管天～年
4. **数据粒度互补**：Checkpoint 保持原始消息（精确），Memory 存储摘要（压缩）

**与 Feature 2（Memory）的依赖关系**：

```
Feature Session-Checkpoint（本 Feature）
    ↓ 前置依赖
Feature 2: Memory 集成
    只有当 Session 本身是连贯的（Checkpoint），
    跨 Session 的语义记忆提取才有意义。
```

---

## 6. 四问闸门（Four-Question Gate）

### 6.1 Checkpoint 方案（Q1 的答案）

| 问题 | 答案 | 说明 |
|------|:----:|------|
| **Is it best practice?** | **Yes** | **Separation of Concerns**：Checkpointer 将状态存储（基础设施层）与 Agent 逻辑（业务层）解耦。**SOLID DIP**：Agent 依赖 `BaseCheckpointSaver` 抽象接口而非具体存储实现。**Defense in Depth**：user-scoped `thread_id` 在框架层面防范跨用户数据泄露。 |
| **Is it industry standard?** | **Yes** | LangGraph Checkpoint 是 LangChain 生态构建生产级 Agent 的核心能力。LangSmith 等可观测平台原生支持 Checkpoint 追踪。AWS multi-agent 参考架构、LangChain 官方 production 指南均推荐此模式。 |
| **Is it conventional?** | **Yes** | 对于任何基于 LangGraph 的 Agent 应用，注入 `checkpointer` + 传 `thread_id` 是最标准、文档最完善的模式。`create_deep_agent()` API 显式暴露 `checkpointer=` 参数，框架设计者预期了这种用法。熟悉 LangChain 生态的开发者对此不会感到意外。 |
| **Is it modern?** | **Yes** | LangGraph 1.0（2025）将 checkpoint 强化为一等公民，支持 durable execution 和 graph-state recovery。Checkpoint 比传统扁平消息存储更 modern——不仅存消息历史，还存 graph node 执行位置，支持中断恢复和 Human-in-the-loop。 |

### 6.2 两阶段状态模型（Q1 + Q2 的架构答案）

| 问题 | 答案 | 说明 |
|------|:----:|------|
| **Is it best practice?** | **Yes** | **Single Responsibility**：Checkpoint 管短期会话连贯性，Memory 管长期知识积累——两个独立关注点分离到两个独立组件。每个组件的接口和使用模式都针对各自的访问模式优化（exact key lookup vs semantic search）。 |
| **Is it industry standard?** | **Yes** | Agent 系统的标准化分层：LangChain/LangGraph 生态中，Short-term Memory（Checkpoint）+ Long-term Memory（Vector Store）是公认模式。OpenAI Assistants API 同样区分 Thread（会话级消息存储）和 Vector Store（跨会话知识检索）。Google Vertex AI Agent Builder、Amazon Bedrock Agents 均采用类似分层。 |
| **Is it conventional?** | **Yes** | 任何生产级 Agent 应用都需要区分"这轮对话到哪了"和"关于这个用户我知道什么"。一个新成员看到 Checkpoint + Memory 两层设计，应该能立刻理解这是会话管理 + 用户建模的标准拆分。 |
| **Is it modern?** | **Yes** | 2025-2026 年 Agent 系统的前沿方向正是 durable execution（Checkpoint）+ persistent memory（RAG over conversation history）。LangGraph 的 checkpoint 机制是这一方向的代表性实现。AgentArts Memory 的多策略记忆抽取（Semantic/Preference/Episodic）也代表了 Agent memory 的最佳实践。 |

---

## 7. 风险与约束

| 风险 | 严重度 | 缓解 |
|------|:------:|------|
| **InMemorySaver 重启丢失** | Medium | 短期（开发阶段）可接受。`SQLITE_DB_PATH` 环境变量提供本地持久化。生产强制使用 PostgresSaver。 |
| **并发写入冲突** | Medium | 相同 `thread_id` 的并发写入可能触发 Checkpointer 乐观锁冲突。缓解：AgentHandler 入口对相同 `thread_id` 加 `asyncio.Lock`。当前低并发阶段可控。 |
| **Checkpoint 存储膨胀** | Low | 默认全量保留，无 TTL。短期数据量极小（开发阶段）。生产引入定期清理 Cron。 |
| **localStorage 不可用** | Low | 私密浏览模式或企业策略可能禁用 localStorage。`getSessionId()` 内置 `try/catch` 降级：每次生成新 UUID（不持久），会话在单次浏览器会话内仍连续。 |

---

## 8. 实施路线

```mermaid
gantt
    title Session 状态管理实施路线
    dateFormat  YYYY-MM-DD
    axisFormat  %m/%d

    section 短期（已完成）
    InMemorySaver + config 传递      :done,    s1, 2026-06-01, 3d
    handle_stream 签名改造            :done,    s2, after s1, 2d
    user-scoped thread_id             :done,    s3, after s1, 1d
    AsyncSqliteSaver 本地持久化        :done,    s4, after s3, 2d
     Header 强校验（本地 + 生产统一）    :done,    s5, after s4, 1d
    客户端 session ID 持久化          :done,    s6, after s5, 1d

    section 中期（Feature 2 之后）
    PostgresSaver 生产部署            :         m1, after s6, 3d
    Session 列表 API                  :         m2, after m1, 3d
    渠道→Session 映射表               :         m3, after m2, 2d

    section 长期
    Session TTL + 自动清理            :         l1, after m3, 2d
    客户端 Session 选择 UI            :         l2, after l1, 2d
```

---

## 9. 受影响的文档

| 文档 | 变更 |
|------|------|
| `architecture/backend_architecture.md` §3 | 更新 AgentHandler 代码示例，增加 Checkpointer 初始化 + config 传递 |
| `architecture/overall_architecture.md` §1.2 | 技术选型表新增一行：`Session State \| LangGraph Checkpoint \| 短期会话状态持久化` |
| `architecture/session-state-management.md` | **本文档**，实现后更新至 v1.0 |
| `ADR-009: deepagents` | 引用确认 `create_deep_agent(checkpointer=...)` 是框架原生能力 |

---

## 10. 参考

- [LangGraph Persistence Docs](https://langchain-ai.github.io/langgraph/how-tos/persistence/)
- [deepagents Customization](https://docs.langchain.com/oss/python/deepagents/customization)
- `feature-session-checkpoint/issue.md` — 本设计的 issue 来源
- `ADR-009: deepagents` — Agent 编排框架选型
- `architecture/backend_architecture.md` — 当前 Agent 处理逻辑
- `architecture/overall_architecture.md` §7 — Memory 集成设计
