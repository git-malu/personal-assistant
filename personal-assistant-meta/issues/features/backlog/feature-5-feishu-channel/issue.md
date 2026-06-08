---
status: backlog
---

# Feature 5: 飞书渠道

本 Phase 接入飞书自建应用，通过事件回调将飞书消息路由到 Agent，完成第二条接入渠道。飞书是内部最高频的 IM 工具，接入后用户可在飞书客户端 @Bot 完成对话。

---

## 背景

Web Chat（Feature 1）已在浏览器中验证了 Agent 核心能力。飞书作为企业内部 IM，接入成本低（飞书客户端就是 UI），且是日常高频使用场景。飞书走事件订阅模式：用户 @Bot → 飞书服务器 POST 到 `/feishu/webhook` → Agent 处理 → 调飞书 API 回复。

本 Phase 不需要 SSE 流式——飞书消息以卡片/文本形式一次性回复即可。

## 范围

- `app/feishu_adapter.py` — 飞书消息解析 + URL 验证 + 回复
- `POST /feishu/webhook` — 事件订阅回调路由
- 飞书 Bot 创建 + 配置（开放平台）
- 端到端验证：飞书 @Bot 对话

## 不涉及

- 飞书卡片交互（仅文本回复）
- 飞书高级功能（审批、文档、日历）
- Web Chat / OfficeClaw 改动（纯增量，不影响已有渠道）

## 任务拆解

### 5.1 飞书适配器

- [ ] `app/feishu_adapter.py`
  - `handle_feishu_webhook(body)` → 解析飞书事件
  - URL 验证（Challenge 模式）：返回 challenge 字段
  - 消息解析：提取消息文本 + user_id + chat_id
  - 消息回复：调飞书发送消息 API（HTTP POST）

### 5.2 Webhook 路由

- [ ] `POST /feishu/webhook` — 注册到 `app/main.py`
  - 验证飞书 Token（防伪造请求）
  - 非流式调用 `agent_handler.handle()`（复用 Feature 1 的 Agent 逻辑）
  - 通过飞书 API 回复消息
  - 错误处理：飞书要求 200 响应（即使处理失败），否则飞书会重试

### 5.3 飞书 Bot 创建

- [ ] 飞书开放平台创建自建应用
- [ ] 配置事件订阅：`/feishu/webhook` 作为回调 URL
- [ ] 配置 Bot 权限（`im:message:receive`、`im:message:send`）
- [ ] 发布应用

### 5.4 验证

- [ ] 本地 `curl` 模拟飞书 Webhook（URL 验证 + 消息事件）
- [ ] 飞书 @Bot "你好" → Agent 在飞书回复
- [ ] 多轮对话不崩溃
- [ ] Web Chat 渠道不受影响

## 依赖

- Feature 1（Agent 骨架 + Web Chat）— 复用 Agent 处理逻辑
- 飞书开放平台账号 + 自建应用权限

## 参考

- `architecture/frontend_architecture.md` #2.2 飞书直连
- `architecture/devops/local-development.md`
- 飞书开放平台文档：事件订阅、消息 API
