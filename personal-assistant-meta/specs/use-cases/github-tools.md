# GitHub Tools Use Case

`github_tools.py` 提供 GitHub 仓库和代码访问能力。Agent 通过 AgentArts Identity 的 OAuth2 User Federation，以当前用户身份调用 GitHub API。

## Tool 列表

| Tool | 用户意图 | 外部 API | Identity Provider |
|---|---|---|---|
| `github_list_repositories` | 列出当前用户可访问的仓库 | GitHub `/user/repos` | `github-provider` |
| `github_list_repo_contents` | 查看仓库目录或文件列表 | GitHub `/repos/{owner}/{repo}/contents/{path}` | `github-provider` |
| `github_get_file_content` | 读取仓库文件内容 | GitHub contents API | `github-provider` |
| `github_search_code` | 搜索代码 | GitHub `/search/code` | `github-provider` |
| `github_star_repository` | 给仓库 star | GitHub `/user/starred/{owner}/{repo}` | `github-provider` |

## 典型 Use Case

### UC-GitHub-01：列出仓库

```text
用户：列出我能访问的 GitHub 仓库。
Agent：我需要你的 GitHub 授权。请点击授权卡片完成授权。
用户完成授权后重试。
Agent：你可访问的仓库包括：...
```

Agent 调用 `github_list_repositories`，返回仓库名、完整名、是否私有、默认分支和 URL。

### UC-GitHub-02：查看仓库目录

```text
用户：帮我看一下 git-malu/personal-assistant 的根目录文件。
Agent：该仓库根目录包含 README.md、personal-assistant-service、personal-assistant-client 等。
```

Agent 调用 `github_list_repo_contents(owner="git-malu", repo="personal-assistant", path="")`。

### UC-GitHub-03：读取文件内容

```text
用户：打开这个仓库里的 README.md，总结项目定位。
Agent：README.md 显示该项目是 Agent Identity 最佳实践 Demo，核心关注...
```

Agent 调用 `github_get_file_content(owner=..., repo=..., path="README.md")`，读取并总结文本内容。

### UC-GitHub-04：搜索代码

```text
用户：在我的 GitHub 仓库里搜索 require_access_token 的用法。
Agent：找到以下代码位置：...
```

Agent 调用 `github_search_code(query="require_access_token user:<user-or-org>")`。

### UC-GitHub-05：给仓库 star

```text
用户：帮我给 git-malu/personal-assistant 点星。
Agent：将为 GitHub 仓库 git-malu/personal-assistant 点星。是否确认？
用户：确认。
Agent：已为该仓库点星。
```

`github_star_repository` 是 tool-level Guard 示例：默认 `confirm=False` 只返回预览和 `requires_confirmation=True`；用户明确确认后，Agent 才能以 `confirm=True` 再次调用并执行真实写操作。

## Agent Identity 能力映射

| 能力 | 在 GitHub Tools 中的使用 |
|---|---|
| OAuth2 User Federation | `_github_request` 使用 `@require_access_token(provider_name=get_github_provider_name(), auth_flow="USER_FEDERATION")` |
| Configurable Scope | GitHub scopes 来自 `GITHUB_SCOPES`，当前默认 `repo,read:user` |
| AuthCard | `_handle_auth_url` 通过 SSE custom stream 展示 GitHub 授权链接 |
| Token Vault | GitHub OAuth token 由 AgentArts Identity 保存，不写入业务代码或浏览器 |
| Tool-level Guard | `github_star_repository` 使用 `confirm` 参数执行预览与真实操作分离 |
| Workload Identity | Gateway 注入 Workload Access Token，SDK 使用它向 Identity Service 获取用户 GitHub token |

## 安全边界

- GitHub token 不进入 LLM prompt、浏览器 storage 或日志。
- 读取仓库内容时，Agent 只能访问用户 OAuth token 可访问的仓库。
- `github_star_repository` 必须先预览，确认后才执行。
- 如果用户未授权，tool 返回 `auth_required` 并通过 AuthCard 引导授权。
