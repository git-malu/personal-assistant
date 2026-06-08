---
status: backlog
---

# Feature 8: Outbound STS (云资源 Tool)

本 Phase 实现 Agent 获取华为云 STS 临时凭证，代表用户操作云资源（OBS、RDS 等）。

---

## 背景

运维场景中，用户希望通过对话管理云资源。本 Phase 验证 STS 模式。

## 范围

- IAM Agency + AgentArts `huaweicloud-sts-provider`
- `app/tools/cloud_tools.py`
- 工具注册到 LangGraph

## 任务拆解

### 8.1 IAM Agency + Provider

- [ ] IAM 控制台创建 Agency（最小权限原则）
- [ ] AgentArts 创建 `huaweicloud-sts-provider`（STS 类型）

### 8.2 云资源工具

- [ ] `app/tools/cloud_tools.py`（纯函数，sts_credentials 外部注入）
- [ ] Token 获取：`require_sts_token`

### 8.3 验证

- [ ] 飞书 @Bot "帮我看看 my-bucket 里有哪些文件" → 返回 OBS 对象列表

## 依赖

- Feature 1（Agent 骨架 + Web Chat）
- Feature 4（Inbound Identity）
- Feature 1.2（PostgreSQL）— 需要 `tool_configs` 表

## 参考

- ADR-003: AgentArts 平台（STS）
- `architecture/overall_architecture.md` #4.2 Outbound
