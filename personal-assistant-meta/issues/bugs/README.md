# Bugs

缺陷跟踪与修复记录。活跃 bug 平铺在 `bugs/` 下，已解决的 bug 归档到 `bugs/resolved/`。

## 活跃 Bug

| Bug | 标题 | 关联 Feature | 状态 |
|-----|------|-------------|------|
| [1](bug-1-maas-rate-limit/issue.md) | MaaS API Rate Limit 导致多轮对话失败 | feature-1-agent-skeleton | backlog |
| [2](bug-2-spa-fallback-not-working/issue.md) | SPA Fallback Not Working (StaticFiles html=True) | feature-1.1-web-chat-frontend | backlog |
| [4](bug-4-cwd-sensitive-chainlit-mount/issue.md) | `mount_chainlit` relative path breaks module import from outside SERVICE_DIR | feature-1.4-chainlit-playground | backlog |
| [5](bug-5-env-merge-prevents-key-removal-in-e2e-tests/issue.md) | E2E Test Environment Merge Prevents Removing Environment Variables | feature-1-agent-skeleton | backlog |

## 已解决 Bug

已归档至 [`resolved/`](resolved/)。

| Bug | 标题 | 关联 Feature | 状态 |
|-----|------|-------------|------|
| [1](resolved/bug-1-playground-trailing-slash-404/issue.md) | GET /playground (无 trailing slash) 返回 404 | feature-1.4-chainlit-playground | closed |
| [3](resolved/bug-3-playground-returns-404/issue.md) | /playground Endpoint Returns 404 — Chainlit Not Mounted | feature-1.4-chainlit-playground | resolved |

## 相关文档

| 文档 | 路径 |
|------|------|
| Features 概览 | `../features/README.md` |
| 总体功能规格 | `../../specs/overall_specifications.md` |
| 架构设计 | `../../architecture/overall_architecture.md` |
| E2E 回归测试 | `../../../personal-assistant-e2e/tests/regression/` |
