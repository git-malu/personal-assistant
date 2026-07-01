# Gitee Tools Use Case

`gitee_tools.py` 提供 Gitee / 码云仓库列表能力。它与 GitHub Tools 使用相同的 Agent Identity 模式：AgentArts Identity 管理 OAuth2 Provider，tool 通过 `@require_access_token` 获得用户委托 token。

## Tool 列表

| Tool | 用户意图 | 外部 API | Identity Provider |
|---|---|---|---|
| `gitee_list_repositories` | 列出当前用户可访问的 Gitee 仓库 | Gitee `/user/repos` | `gitee-provider` |

## 典型 Use Case

### UC-Gitee-01：列出 Gitee 仓库

```text
用户：帮我列一下我的 Gitee 仓库。
Agent：请先完成 Gitee 授权。
用户完成授权后重试。
Agent：你当前可访问的 Gitee 仓库如下：...
```

Agent 调用 `gitee_list_repositories`，返回仓库名、完整名、是否私有、命名空间、描述、默认分支和更新时间等信息。

### UC-Gitee-02：按分页和排序查看仓库

```text
用户：按更新时间列出前 20 个 Gitee 仓库。
Agent：以下是按更新时间筛选后的仓库：...
```

Agent 可设置 `sort`、`direction`、`page`、`per_page` 等参数调用 `gitee_list_repositories`。

## Agent Identity 能力映射

| 能力 | 在 Gitee Tools 中的使用 |
|---|---|
| OAuth2 User Federation | `list_repositories` 使用 `@require_access_token(provider_name=get_gitee_provider_name(), auth_flow="USER_FEDERATION")` |
| Provider Abstraction | `gitee-provider` 与 `github-provider` 独立配置，但 tool 侧使用相同的 Identity SDK 装饰器模式 |
| AuthCard | `handle_auth_url` 通过 SSE custom stream 展示 Gitee 授权入口 |
| Token Vault | Gitee access token 由 AgentArts Identity 保存，不暴露给 Service 持久化层 |
| Workload Identity | SDK 使用 Runtime context 中的 Workload Access Token 访问 Identity Service |

## Scope 策略

Gitee Tools 当前默认使用：

```text
user_info
projects
```

该 scope 覆盖读取当前用户信息和项目列表的需要。后续如新增写操作，应单独评估 scope 与 Guard。

## 安全边界

- 当前 Gitee Tool 只读，不执行仓库写入、删除或修改。
- Gitee token 只由 Identity SDK 注入到 tool，不写入日志或响应。
- 未授权时通过 AuthCard 引导用户完成授权。
