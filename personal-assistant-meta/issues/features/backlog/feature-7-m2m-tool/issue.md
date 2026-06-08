---
status: backlog
---

# Feature 7: Outbound M2M (内部 API Tool)

本 Phase 实现 Agent 以自身服务身份调用企业内部 API（M2M 模式）。Agent 使用预配置的 API Key 访问内部系统。

---

## 背景

企业内部系统通常通过 API Key 做服务间调用。本 Phase 验证 M2M 模式。

## 范围

- AgentArts `internal-api-provider` Credential Provider（API Key 类型）
- `app/tools/internal_tools.py`
- 工具注册到 LangGraph

## 任务拆解

### 7.1 Credential Provider

- [ ] AgentArts 控制台创建 `internal-api-provider`（API Key 类型）

### 7.2 内部 API 工具

- [ ] `app/tools/internal_tools.py`（纯函数，api_key 外部注入）
- [ ] Token 获取：`require_api_key` 或 IdentityClient

### 7.3 验证

- [ ] 飞书 @Bot 调内部 API → 返回结果
- [ ] API Key 不泄露到回复中

## 依赖

- Feature 1（Agent 骨架 + Web Chat）
- Feature 4（Inbound Identity）
- Feature 1.2（PostgreSQL）— 需要 `tool_configs` 表

## 参考

- ADR-003: AgentArts 平台（M2M）
- `architecture/overall_architecture.md` #4.2 Outbound
