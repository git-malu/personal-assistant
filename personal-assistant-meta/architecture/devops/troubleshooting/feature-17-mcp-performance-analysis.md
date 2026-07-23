# Feature-17 MCP 调用耗时分析

> 日期：2026-07-16
> 范围：`github_mcp_search_activity` 端到端调用链路
> 方法：静态代码路径分析

## 1. 调用链路全景

一次 `github_mcp_search_activity` 的完整 MCP 往返链路：

```
应用代码 → IAM 签名 → HTTP 请求 → AgentArts MCP Gateway → GitHub MCP Server → GitHub API
                                                                                  ↓
应用代码 ← JSON 解析 ← HTTP 响应 ← AgentArts MCP Gateway ← GitHub MCP Server ←──┘
```

以 **1 个仓库、5 种事件类型全选、命中 5 个 Issue + 3 个 PR** 的典型场景为例，共 **13 次** MCP 往返：

```
list_tools         █ 1 次
get_me             █ 1 次
list_commits       █ 1 次
list_pull_requests █ 1 次
list_issues        █ 1 次
get_issue_comments █████ 5 次（每个 Issue 一次）
get_pr_reviews     ███ 3 次（每个 PR 一次）
                   ─────
                   13 次 MCP 往返
```

---

## 2. 瓶颈分析

### 瓶颈 1：每次调用都新建 Session（✅ 已于 2026-07-17 修复，详见 [session-per-call 修复文档](./feature-17-mcp-session-per-call-performance.md)）

**位置**（修复前旧代码）：[`gateway_client.py`](../../../../personal-assistant-service/app/mcp/gateway_client.py)（旧 `list_tools`/`call_tool` 代码已不存在，当前为 context manager 实现）

`list_tools()` 和 `call_tool()` 各自独立调用 `self._client()` + `client.session()`，每次创建全新的 `MultiServerMCPClient` 实例和 MCP session。

同时 [`_mcp_http_client_factory`](../../../../personal-assistant-service/app/mcp/gateway_client.py#L160-L178) 每次 `new` 一个 `httpx.AsyncClient`（`trust_env=False`），**无连接池复用**。

**影响**：13 次调用 = 13 次 TCP+TLS 握手 + 13 次 IAM 签名计算 + 13 次 MCP Session 创建/销毁。这不是"13 个 HTTP 请求"的代价，而是"13 个全新连接"的代价。

```python
# 修复前旧代码 — gateway_client.py（已不存在此逻辑）
async def list_tools(self) -> list[MCPToolInfo]:
    client = self._client()                              # 新建 MultiServerMCPClient
    async with client.session(_GITHUB_MCP_SERVER_NAME) as session:  # 新建 session
        result = await session.list_tools()

# 修复前旧代码 — gateway_client.py（已不存在此逻辑）
async def call_tool(self, name, arguments) -> Any:
    client = self._client()                              # 又新建一个
    async with client.session(_GITHUB_MCP_SERVER_NAME) as session:  # 又新建 session
        result = await session.call_tool(name, arguments)
```

---

### 瓶颈 2：N+1 查询问题（Comment/Review 收集）

**位置**：[`github_activity_source.py:1486-1493`](../../../../personal-assistant-service/app/mcp/github_activity_source.py#L1486-L1493)

Comments 和 Reviews 没有批量查询接口，代码为每个 Issue/PR **逐个串行**发起独立的 `get_issue_comments` / `get_pull_request_reviews` 调用。这是**最隐蔽且增长最快的瓶颈**。

```python
# github_activity_source.py:1486-1493
if task.discover_parents:
    child_tasks = _child_tasks_from_parent_page(task, page)
    ...
    tasks[0:0] = child_tasks + continuation  # 子任务插入队列头部，逐个串行弹出执行
```

**影响**：10 个 Issue + 5 个 PR = 额外 15 次串行往返。活动的仓库越活跃，子调用越多，耗时线性增长。

---

### 瓶颈 3：仓库间与事件类型间全部串行

**位置**：[`github_activity_source.py:1458-1494`](../../../../personal-assistant-service/app/mcp/github_activity_source.py#L1458-L1494)

三个维度全部顺序执行，但 commits / PRs / issues 三者**相互独立**，多仓库之间也**相互独立**，完全具备并行条件。

```
Repo 1
  └→ commits ──→（等）
  └→ PRs ──────→（等）
  └→ issues ───→（等）
  └→ comments ─→（等，逐个串行）
  └→ reviews ──→（等，逐个串行）
       ↓ 全部完成后才进入
Repo 2
  └→ ...（同上）
```

**影响**：3 个仓库 = 耗时 ×3。

---

### 瓶颈 4：每次搜索都重新 `list_tools`

**位置**：[`github_activity_source.py:1435`](../../../../personal-assistant-service/app/mcp/github_activity_source.py#L1435)

MCP 工具列表在 Target 配置不变的情况下是稳定的，但每次 `github_mcp_search_activity` 调用都重新获取，额外增加 1 次往返。

```python
# github_activity_source.py:1434-1435
async def _operation(client: MCPGatewayClient) -> GitHubActivityResult:
    tools = await _tool_index(client)  # 每次都重新获取工具列表
```

---

## 3. 耗时估算

### 往返次数公式

```
总往返次数 = 2 + N_repos × (3 + N_issues + N_PRs)
```

其中：
- `2` = `list_tools` + `get_me`
- `3` = commits + pull_requests + issues（每个仓库）
- `N_issues` = 命中时间窗口的 Issue 数（每个触发 1 次 `get_issue_comments`）
- `N_PRs` = 命中时间窗口的 PR 数（每个触发 1 次 `get_pull_request_reviews`）

### 典型场景估算

| 场景 | 仓库数 | 往返次数 | 估算耗时（每跳 1s） | 估算耗时（每跳 3s） |
|------|--------|----------|---------------------|---------------------|
| 轻型（仅 commits/PRs/issues，不含 comment/review） | 1 | 5 | 5s | 15s |
| 典型（含 5 issues + 3 PRs 子调用） | 1 | 13 | 13s | 39s |
| 活跃仓库（含 10 issues + 5 PRs 子调用） | 1 | 20 | 20s | 60s |
| 多仓库（2 个典型仓库） | 2 | 24 | 24s | 72s |

---

## 4. 优化方向（供参考）

| 优先级 | 瓶颈 | 思路 |
|--------|------|------|
| **P0（✅ 已修复）** | Session 重复创建 | 已将 `MCPGatewayClient` 改造为 async context manager，详见 [修复文档](./feature-17-mcp-session-per-call-performance.md) |
| **P0** | N+1 查询 | comments 和 reviews 与对应 issue/PR 收集合并为并行批处理（`asyncio.gather`） |
| **P1** | 事件类型串行 | commits / PRs / issues 三者无依赖，可用 `asyncio.gather` 并行发起 |
| **P1** | 仓库串行 | 多仓库场景可用 `asyncio.gather` 并行处理 |
| **P2** | list_tools 缓存 | 同一次 Agent turn 内缓存工具列表（如缓存到 `MCPGatewayClient` 实例上），避免重复获取 |

### P0 优化预期效果（1 个典型仓库）

```
优化前（13 次串行，每次新建连接）：13 × 3s ≈ 39s

Session 复用 + 并行后：
  list_tools         █ 1 次（缓存后 0 次）
  get_me             █ 1 次（session 复用）
  ┌ commits         █ 1 次 ┐
  ├ PRs             █ 1 次 ├ asyncio.gather 并行（3 次同时发出）
  └ issues          █ 1 次 ┘
  ┌ comments × 5    █████ 5 次 ┐
  └ reviews × 3     ███ 3 次   ┘ asyncio.gather 并行

优化后总耗时 ≈ max(3 核心调用, 8 子调用) × 1s ≈ 5~8s
节省约 75%~85%
```
