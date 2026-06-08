---
status: backlog
---

# Feature 2: Memory 集成

本 Phase 集成 AgentArts Memory，实现跨 Session 的用户记忆。飞书渠道上验证：第一轮对话设定偏好，第二轮对话（新 Session）Agent 能记住。

---

## 背景

当前 Agent 每次对话都是 "失忆" 的。本 Phase 接入 AgentArts Memory SDK，使 Agent 能够在每次对话开始时加载用户的历史偏好和上下文，对话结束时保存本轮交互。

## 范围

- 创建 Memory Space（AgentArts 控制台）
- `app/memory.py` — Memory 集成模块
- Agent 处理逻辑中注入 Memory 上下文
- 对话结束后保存交互
- 飞书渠道验证跨 Session 记忆

## 不涉及

- Memory 策略调优（先用默认配置）

## 任务拆解

### 2.1 Memory Space 创建

- [ ] AgentArts 控制台创建 Memory Space
- [ ] 获取 Space ID，配置环境变量 `MEMORY_SPACE_ID`

### 2.2 Memory 集成模块

- [ ] `app/memory.py` — PersonalAssistantMemory 类
  - `get_context(user_id)` → 搜索长期记忆，返回上下文字符串
  - `save_interaction(user_id, query, response)` → 保存对话
- [ ] 依赖：`agentarts.sdk.memory`

### 2.3 Agent 处理逻辑改造

- [ ] `handle()` 方法：LLM 调前注入 Memory 上下文，调后保存交互
- [ ] system prompt 增加 Memory 使用说明

### 2.4 验证

- [ ] 飞书第一轮："我喜欢简洁的回答"
- [ ] 飞书第二轮（新对话）："帮我查日程" → 回答风格偏简洁
- [ ] 注意 Memory 生成有约 30s 延迟

## 依赖

- Feature 1（Agent 骨架 + Web Chat）

## 参考

- ADR-003: AgentArts 平台
- `architecture/overall_architecture.md` #6 Memory 集成
- `architecture/devops/local-development.md` #3 Memory 开发说明
