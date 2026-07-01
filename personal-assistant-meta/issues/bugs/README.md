# Bugs

缺陷跟踪与修复记录。活跃 bug 平铺在 `bugs/` 下，已解决的 bug 归档到 `bugs/resolved/`。

## 活跃 Bug

| Bug | 标题 | 关联 Feature | 状态 |
|-----|------|-------------|------|
| [1](canceled/bug-1-maas-rate-limit/issue.md) | MaaS API Rate Limit 导致多轮对话失败 | feature-1-agent-skeleton | backlog |
| [11](bug-11-agentarts-platform-issues/issue.md) | AgentArts 平台级缺陷与限制汇总 | — | backlog |
| [12](bug-12-agentarts-sandbox-cold-start-504/issue.md) | AgentArts Sandbox 冷启动触发 504 Gateway Timeout | — | todo |
| [13](resolved/bug-13-b2b-guest-user-401/issue.md) | 部分 Azure AD B2B Guest 用户调用 /invocations 返回 401 | feature-4-inbound-identity | todo |
| [14](resolved/bug-14-email-tool-b2b-guest-401/issue.md) | 邮件工具对 B2B Guest 用户（MSA）返回 401 | — | todo |
| [15](bug-15-auth-url-custom-event-not-delivered/issue.md) | adispatch_custom_event 无法将 Auth URL 推送到 SSE Stream | — | todo |
| [16](bug-16-auth-card-system-message-duplicated-in-chat/issue.md) | Auth Card system_message 重复出现在聊天气泡中 | feature-1.2-auth-url-redirect | backlog |
| [18](bug-18-expired-login-token-not-logging-out/issue.md) | 前端登录 token 过期后未自动登出并继续发送旧 token | feature-4-inbound-identity | todo |
| [20](bug-20-oauth2-state-replay-protection-not-enforced/issue.md) | OAuth2 callback state nonce replay protection 未跨实例生效 | feature-15-calendar-agentarts-full-oauth2 | implemented |
| [21](resolved/bug-21-calendar-oauth2-complete-session-identity-mismatch/issue.md) | Calendar OAuth2 complete 偶发 session identity mismatch | feature-15-calendar-agentarts-full-oauth2 | implemented |
| [22](bug-22-calendar-oauth2-local-complete-user-token-wat-mismatch/issue.md) | Calendar OAuth2 本地 complete 使用 user_token 与 WAT identity 不匹配 | feature-15-calendar-agentarts-full-oauth2 | superseded |

## 已解决 Bug

已归档至 [`resolved/`](resolved/)。

| Bug | 标题 | 关联 Feature | 状态 |
|-----|------|-------------|------|
| [1](resolved/bug-1-playground-trailing-slash-404/issue.md) | GET /playground (无 trailing slash) 返回 404 | feature-1.4-chainlit-playground | closed |
| [2](resolved/bug-2-spa-fallback-not-working/issue.md) | SPA Fallback Not Working (StaticFiles html=True) | feature-1.1-web-chat-frontend | resolved |
| [3](resolved/bug-3-playground-returns-404/issue.md) | /playground Endpoint Returns 404 — Chainlit Not Mounted | feature-1.4-chainlit-playground | resolved |
| [4](resolved/bug-4-cwd-sensitive-chainlit-mount/issue.md) | `mount_chainlit` relative path breaks module import from outside SERVICE_DIR | feature-1.4-chainlit-playground | resolved |
| [5](resolved/bug-5-env-merge-prevents-key-removal-in-e2e-tests/issue.md) | E2E Test Environment Merge Prevents Removing Environment Variables | feature-1-agent-skeleton | resolved |
| [6](resolved/bug-6-vite-playground-proxy-missing/issue.md) | Vite Dev Server 未代理 /playground 到 Chainlit 后端 | feature-1.4-chainlit-playground | resolved |
| [7](resolved/bug-7-agents-not-updating-docs/issue.md) | Agent 开发后未同步更新 AGENTS.md / README.md | — | resolved |
| [8](resolved/bug-8-netlify-vite-api-base-url-placeholder/issue.md) | Netlify 部署聊天失败 — VITE_API_BASE_URL 未替换占位符 | — | resolved |
| [9](resolved/bug-9-agentarts-gateway-404-stream/issue.md) | AgentArts Gateway 对 `/invocations/stream` 返回 404 — CORS 头缺失 | — | resolved |
| [10](resolved/bug-10-agentarts-gateway-cors-preflight/issue.md) | AgentArts Gateway CORS Preflight 阻断前端请求 | — | resolved |

## 相关文档

| 文档 | 路径 |
|------|------|
| Features 概览 | `../features/README.md` |
| 总体功能规格 | `../../specs/overall_specifications.md` |
| 架构设计 | `../../architecture/overall_architecture.md` |
| E2E 回归测试 | `../../../personal-assistant-e2e/tests/regression/` |
