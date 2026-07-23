# Feature-17 MCP 每次调用新建 Session 导致端到端耗时过长

> 记录时间：2026-07-17
> 区域：`cn-southwest-2`
> 结论：`MCPGatewayClient.list_tools()` 和 `call_tool()` 各自独立创建
> `MultiServerMCPClient` 和 MCP Session，每次调用都是一次全新的 TCP+TLS
> 握手 + MCP 协议会话建立 + IAM 签名。修复方案是将 `MCPGatewayClient`
> 改造为 async context manager，在整个搜索操作期间共享同一个 MCP Session。

## 症状

用户请求 Feature-17 的 GitHub 工程活动查询（如"帮我查一下 personal-assistant
仓库最近的 commits 和 PRs"）时，端到端响应时间远超预期。以 1 个仓库、5 种
事件类型全选的典型场景为例，单次 `github_mcp_search_activity` 调用需要
发起 10~20 次 MCP 往返，耗时 30~60 秒甚至更久。

Agent 侧表现为长时间无 SSE 输出，用户感知为"Agent 卡住了"。

## 已确认事实

### 调用链路分析

一次 `github_mcp_search_activity` 的完整 MCP 往返路径：

```
Service → IAM 签名 → HTTP → MCP Gateway → GitHub MCP Server → GitHub API
```

以 1 个仓库、5 种事件类型全选、命中 5 个 Issue + 3 个 PR 为例，共 13 次
MCP 往返：

```
list_tools         1 次
get_me             1 次
list_commits       1 次
list_pull_requests 1 次
list_issues        1 次
get_issue_comments 5 次（每个 Issue 一次，串行）
get_pr_reviews     3 次（每个 PR 一次，串行）
─────────────────────
                  13 次 MCP 往返
```

### 旧代码：每次调用新建 Session

旧版 `MCPGatewayClient`（修复前）中，`list_tools()` 和 `call_tool()`
各自独立调用 `self._client()` 创建全新的 `MultiServerMCPClient` 实例，
然后 `async with client.session()` 打开一个全新的 MCP Session：

```python
# 修复前 — 每次调用独立建连
async def list_tools(self) -> list[MCPToolInfo]:
    client = self._client()                              # 新建 MultiServerMCPClient
    async with client.session(_GITHUB_MCP_SERVER_NAME) as session:
        result = await session.list_tools()              # 新建 HTTP 连接 + session 握手

async def call_tool(self, name, arguments) -> Any:
    client = self._client()                              # 又新建
    async with client.session(_GITHUB_MCP_SERVER_NAME) as session:
        result = await session.call_tool(name, arguments) # 又新建 HTTP 连接
```

同时 `_mcp_http_client_factory` 每次返回全新的 `httpx.AsyncClient(trust_env=False)`，
无连接池复用。

这意味着 13 次 MCP 往返 = 13 次：
- `MultiServerMCPClient` 对象创建
- MCP Session 协议握手
- TCP+TLS 握手（无 keep-alive 复用）
- IAM SDK 签名计算
- MCP Session 销毁

此外，旧版使用模块级固定 `_FIXED_MCP_SESSION_ID`，MCP 协议的动态
session 管理机制完全未被利用。

### 耗时公式

```
总耗时 ≈ 往返次数 × (TCP+TLS + IAM签名 + Gateway处理 + GitHub API延迟)
```

| 场景 | 往返次数 | 估算耗时（每跳 1s） | 估算耗时（每跳 3s） |
|------|----------|---------------------|---------------------|
| 轻型（不含 comment/review） | 5 | 5s | 15s |
| 典型（5+3 子调用） | 13 | 13s | 39s |
| 活跃仓库（10+5 子调用） | 20 | 20s | 60s |

## 修复方案

将 `MCPGatewayClient` 改造为 async context manager，在 `__aenter__`
中建立一次 MCP Session，后续所有 `list_tools()` 和 `call_tool()` 复用
同一个 Session。

### 核心变更

**1. `MCPGatewayClient` 实现 `__aenter__` / `__aexit__`**

```python
class MCPGatewayClient:
    def __init__(self, *, config, sts_credentials) -> None:
        self._session_context: AbstractAsyncContextManager[ClientSession] | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> MCPGatewayClient:
        # 只创建一次 session，存储引用
        session_context = self._client().session(_GITHUB_MCP_SERVER_NAME)
        self._session = await session_context.__aenter__()
        self._session_context = session_context
        return self

    async def __aexit__(self, ...):
        # 操作结束后统一关闭 session
        await self._session_context.__aexit__(...)
```

**2. `list_tools()` / `call_tool()` 复用已有 Session**

```python
async def list_tools(self) -> list[MCPToolInfo]:
    session = self._require_session()  # 使用已建立的 session
    result = await session.list_tools()

async def call_tool(self, name, arguments) -> Any:
    session = self._require_session()  # 使用已建立的 session
    result = await session.call_tool(name, arguments)
```

**3. `run_with_github_mcp_sts` 使用 `async with` 包裹整个操作**

```python
async def _run(*, sts_credentials: StsCredentials) -> Any:
    async with MCPGatewayClient(config=config, sts_credentials=sts_credentials) as client:
        return await operation(client)  # 整个搜索操作共享一个 session
```

**4. 移除固定 Session ID**

`_DEFAULT_MCP_HEADERS` 不再包含硬编码的 `mcp-session-id`。Session ID
改由 MCP 协议动态协商——首次请求不带 session ID，Gateway 在响应中返回，
后续请求自动携带。

**5. `extract_mcp_payload` 增加 `isError` 检查**

```python
def extract_mcp_payload(result: Any) -> Any:
    if getattr(result, "isError", False):
        raise MCPGatewayError("mcp_error", "GitHub MCP tool execution failed.", ...)
```

### 修复效果

13 次 MCP 往返从"13 次全新连接"变为"1 次连接 + 13 次请求/响应"，
消除了每次调用的 TCP+TLS 握手和 MCP Session 建立开销。

```
修复前：list_tools ──── TCP+TLS + Session 握手 + 请求 → 响应 → 关闭
       get_me ──────── TCP+TLS + Session 握手 + 请求 → 响应 → 关闭
       list_commits ── TCP+TLS + Session 握手 + 请求 → 响应 → 关闭
       ...（共 13 次完整建连）

修复后：__aenter__ ─── TCP+TLS + Session 握手
       list_tools ──── 请求 → 响应（复用已有连接）
       get_me ──────── 请求 → 响应
       list_commits ── 请求 → 响应
       ...（共 13 次请求，1 次建连）
       __aexit__ ───── 关闭
```

节省的主要是每跳中 TCP+TLS 握手（通常 1~3 个 RTT，数十到数百毫秒）和
MCP Session 协商开销。具体节省幅度取决于网络延迟，预计 1 个典型仓库
的场景下可节省 15%~30%。

### 未修复的并行化机会

Session 复用解决了"每次建新连接"的开销，但以下串行问题仍存在，
详见 [feature-17-mcp-performance-analysis.md](./feature-17-mcp-performance-analysis.md)：

- N+1 查询：Comments 和 Reviews 仍逐个串行调用
- 事件类型串行：commits / PRs / issues 三者相互独立但顺序执行
- 仓库串行：多仓库间顺序执行
- `list_tools` 每次搜索都重新获取

## 验证命令

本地启动 Service 后，通过 Web Chat 或 API 触发一次 GitHub 工程活动查询：

```bash
curl -X POST http://localhost:8000/invocations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <local-jwt>" \
  -H "x-user-id: test-user" \
  -H "x-session-id: test-session-$(date +%s)" \
  -d '{
    "message": "查询 personal-assistant 仓库最近一周的 commits 和 PRs"
  }'
```

观察日志中 MCP Session 初始化只出现一次（`__aenter__` 阶段），
后续 `list_tools` 和 `call_tool` 日志中不应再出现 session 建立相关
的 HTTP 连接日志。

也可在 Service 日志中对比单次 `_operation` 的总耗时：

```text
# 修复前：13 次独立建连，每次几百 ms 握手开销
# 修复后：1 次建连 + 13 次请求复用
```
