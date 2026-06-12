---
status: backlog
---

# Feature 6: Outbound User Federation (GitHub Tool)

本 Phase 实现 Agent 以用户身份调用 GitHub API（User Federation 模式）。用户完成一次 OAuth 授权后，Agent 可以代表用户查询本项目 `git-malu/personal-assistant` 的 Issues / PR 信息。

**v1 成功标准**：通过 Web Chat 或 AgentArts `/invocations` 询问"查一下本项目 open issues / PR"，Agent 走 AgentArts Identity `github-provider` 获取 GitHub OAuth2 access token，并返回 `git-malu/personal-assistant` 的 open Issues / Pull Requests 摘要与链接。

---

## 背景

Personal Assistant 的核心价值之一是 "以用户身份访问外部服务"。本 Phase 验证最典型的 User Federation 场景：Agent 帮你查 GitHub Issues / PR。底层走 AgentArts Identity 的 OAuth2 Credential Provider。

## 范围

- 创建 GitHub OAuth App + AgentArts `github-provider` Credential Provider
- `app/tools/github_tools.py` — GitHub 工具函数
- 工具注册到 deepagents `create_deep_agent(tools=[...])`
- 验证：Web Chat / AgentArts invoke "帮我查本项目 open issues / PR"，Agent 调 GitHub API 返回结果

## 不涉及

- Microsoft 365 工具（Outlook / Calendar，结构相同，后续可复用）
- M2M 模式（Feature 7）
- STS 模式（Feature 8）
- 读取源码、README、目录树或文件内容

## 任务拆解

### 6.1 GitHub OAuth App + Provider

- [ ] GitHub Settings 创建 OAuth App，获取 client_id / client_secret
- [ ] AgentArts 控制台/SDK 创建 `github-provider`（OAuth2, vendor=github）
- [ ] Runtime / 本地环境配置 `HUAWEICLOUD_SDK_AK`、`HUAWEICLOUD_SDK_SK`

### 6.2 GitHub 工具函数

- [ ] `app/tools/github_tools.py`
  - `list_project_issues(state="open", limit=20)` — 查询 `git-malu/personal-assistant` Issues，过滤 Pull Requests
  - `list_project_pull_requests(state="open", limit=20)` — 查询 `git-malu/personal-assistant` Pull Requests
  - 返回结构化字段：`number/title/state/html_url/author/updated_at/labels`；PR 额外包含 `draft/base/head`

### 6.3 Token 获取

- [ ] 调 AgentArts Identity SDK 获取 access_token
- [ ] 首次使用时引导用户完成 OAuth 授权
- [ ] OAuth scopes 使用 `repo` + `read:user`，兼容私有仓库；确认只访问公开仓库后可收窄权限

### 6.4 工具注册与验证

- [ ] 注册到 `AgentHandler` 的 `create_deep_agent(tools=[...])`，更新 system prompt
- [ ] Web Chat "帮我查本项目 open issues" → 返回 Issue 列表
- [ ] Web Chat "帮我查本项目 PR" → 返回 PR 列表
- [ ] 跨 Session 无需重新授权

## 依赖

- Feature 1（Agent 骨架 + Web Chat）
- Feature 2（Memory）
- Feature 4（Inbound Identity）— 需要用户身份
- Feature 1.2（PostgreSQL）— 需要 `tool_configs` 表

## 参考

- ADR-003: AgentArts 平台（Identity 部分）
- `architecture/overall_architecture.md` #4 Identity 设计
- `agentarts-sdk>=0.1.3` — `require_access_token(provider_name="github-provider", auth_flow="USER_FEDERATION")`
- GitHub REST API — Issues / Pull Requests
