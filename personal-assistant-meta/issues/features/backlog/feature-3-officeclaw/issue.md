---
status: backlog
---

# Feature 3: OfficeClaw 渠道

本 Phase 接入 OfficeClaw 桌面客户端，通过 AgentArts 转发调用后端 `/invocations`，使 Agent 同时支持飞书和微信渠道。

---

## 背景

OfficeClaw 是运行在 Windows PC 上的桌面客户端，桥接飞书和微信。它通过 AgentArts 平台转发消息到后端的 `/invocations`，零代码实现多渠道覆盖。本 Phase 几乎不需要写代码，主要是配置和验证。

## 范围

- Windows PC 安装 OfficeClaw
- 配置 OfficeClaw 连接 AgentArts
- 飞书渠道通过 OfficeClaw 验证
- 微信渠道通过 OfficeClaw 验证

## 不涉及

- 任何后端代码改动（`/invocations` 已在 Feature 1 实现）
- 飞书直连模式（Feature 5，OfficeClaw 是另一种接入路径）

## 任务拆解

### 3.1 OfficeClaw 安装与配置

- [ ] Windows PC 下载安装 OfficeClaw
- [ ] 配置 AgentArts 连接信息（Region、Agent ID）
- [ ] 配置飞书和微信桥接

### 3.2 验证

- [ ] 飞书客户端 @Agent → OfficeClaw 转发 → Agent 回复
- [ ] 微信客户端发消息 → OfficeClaw 转发 → Agent 回复
- [ ] 确认 Memory 跨渠道生效（Feature 2 的记忆在 OfficeClaw 渠道也能加载）

## 依赖

- Feature 1（Agent 骨架 + Web Chat）
- Feature 2（Memory）

## 参考

- `architecture/frontend_architecture.md` #2.3 OfficeClaw
- AgentArts 平台文档
