---
status: backlog
---

# Feature 6: Outbound User Federation (GitHub Tool)

本 Phase 实现 Agent 以用户身份调用 GitHub API（User Federation 模式）。用户完成一次 OAuth 授权后，Agent 可以代表用户查询 Issues、PR、仓库信息。

---

## 背景

Personal Assistant 的核心价值之一是 "以用户身份访问外部服务"。本 Phase 验证最典型的 User Federation 场景：Agent 帮你查 GitHub Issues。底层走 AgentArts Identity 的 OAuth2 Credential Provider。

## 范围

- 创建 GitHub OAuth App + AgentArts `github-provider` Credential Provider
- `app/tools/github_tools.py` — GitHub 工具函数
- 工具注册到 LangGraph 的 ToolNode
- 验证：飞书 @Bot "帮我查我的 GitHub Issues"，Agent 调 GitHub API 返回结果

## 不涉及

- Microsoft 365 工具（Outlook / Calendar，结构相同，后续可复用）
- M2M 模式（Feature 7）
- STS 模式（Feature 8）

## 任务拆解

### 6.1 GitHub OAuth App + Provider

- [ ] GitHub Settings 创建 OAuth App，获取 client_id / client_secret
- [ ] AgentArts 控制台/SDK 创建 `github-provider`（OAuth2, vendor=github）

### 6.2 GitHub 工具函数

- [ ] `app/tools/github_tools.py`
  - `list_issues(owner, repo, access_token)` — 纯函数，token 外部注入
  - `get_issue(owner, repo, issue_number, access_token)`
  - `list_repos(access_token)`

### 6.3 Token 获取

- [ ] 调 AgentArts Identity SDK 获取 access_token
- [ ] 首次使用时引导用户完成 OAuth 授权

### 6.4 工具注册与验证

- [ ] 注册到 LangGraph ToolNode，更新 system prompt
- [ ] 飞书 @Bot "帮我查 my-org/my-repo 的 open issues" → 返回 Issue 列表
- [ ] 跨 Session 无需重新授权

## 依赖

- Feature 1（Agent 骨架 + Web Chat）
- Feature 2（Memory）
- Feature 4（Inbound Identity）— 需要用户身份
- Feature 1.2（PostgreSQL）— 需要 `tool_configs` 表

## 参考

- ADR-003: AgentArts 平台（Identity 部分）
- `architecture/overall_architecture.md` #4 Identity 设计
