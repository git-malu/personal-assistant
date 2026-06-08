---
status: backlog
---

# Refactor 1: 合并 /ping 路由，去掉 /api 前缀冗余

移除 `/api/ping` 端点，统一使用 root-level `/ping` 和 `/invocations`。AgentArts 平台健康检查和 CDN 回源探活共用同一个 `/ping`。

## 背景

Feature 1 中出于避免 StaticFiles 路由冲突的考虑，所有 API 路由统一加了 `/api` 前缀（plan §2.4），导致出现了两套 ping：

| 端点 | 调用方 | 是否必要 |
|------|--------|----------|
| `GET /ping` | 不存在 | ❌ 漏了——AgentArts 实际需要这个 |
| `POST /invocations` | 不存在 | ❌ 漏了——同上 |
| `GET /api/ping` | 外部 / CDN | ❌ CDN 健康检查用 `/ping` 即可 |
| `POST /api/invocations` | 外部 | ❌ 外部客户端不直接调这个 |

**结论**：AgentArts 平台只认 root-level `/ping` 和 `/invocations`，CDN 健康检查同样用 `/ping`。`/api` 前缀的两个是多余的。

四个闸门均已通过：单一职责、K8s 惯例、命名空间隔离、现代标准。

## 范围

- `personal-assistant-service/app/main.py`：删除 `/api/ping` 和 `/api/invocations`，新增 root-level `/ping` 和 `/invocations`
- `personal-assistant-service/tests/test_main.py`：更新路由测试指向 root-level 路径
- `personal-assistant-meta/architecture/backend_architecture.md` §2：路由表更新
- `personal-assistant-meta/issues/features/feature-1-agent-skeleton/plan.md` §2.4：标注决策变更

## 不涉及

- `/api/chat/stream` 保持不变（CDN `/api/*` 分流需要）
- 其他 `/api/*` 路由不受影响

## 影响

- AgentArts 平台健康检查恢复正常（`GET :8080/ping`）
- AgentArts 平台调用分发恢复正常（`POST :8080/invocations`）
- CDN 健康检查改用 `GET /ping`（原来也是走 `/ping`，无变化）

## 关联文档

- [ADR-004](../architecture/ADR/ADR-004-fastapi-over-agentarts-runtime-app.md) — FastAPI 替代 AgentArtsRuntimeApp
- [Feature 1 plan §2.4](../features/feature-1-agent-skeleton/plan.md) — API 路由 `/api` 前缀决策
