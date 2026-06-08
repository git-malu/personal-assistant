---
status: backlog
---

# Feature 9: 部署上线与全链路可观测

本 Phase 将 Personal Assistant 部署到 AgentArts Runtime 生产环境，配置全链路可观测，完成最终验证。

---

## 背景

前 8 个 Phase 完成了所有功能和渠道。本 Phase 将其推送到生产环境。

## 范围

- 生产环境 `agentarts launch`
- OTEL 可观测性（Tracing / Logging / Metrics）
- 三渠道冒烟测试（飞书 / OfficeClaw / Web Chat）
- 跨渠道 Memory 验证
- 文档完善

## 任务拆解

### 9.1 生产部署

- [ ] 确认生产配置（image、SWR、环境变量、network_mode）
- [ ] `agentarts launch`
- [ ] `/ping` + `/invocations` 验证

### 9.2 可观测性

- [ ] 确认 tracing / metrics / logs 在 AgentArts 控制台可查看
- [ ] 一次完整对话的 Trace 链路可追踪

### 9.3 多渠道验证

- [ ] 飞书 @Bot → Agent 回复正常
- [ ] OfficeClaw（飞书/微信）→ Agent 回复正常
- [ ] Web Chat → OAuth 登录 + SSE 流式正常

### 9.4 跨渠道 Memory

- [ ] 飞书设置偏好 → Web Chat 加载相同偏好
- [ ] OfficeClaw 设置偏好 → 飞书加载相同偏好

### 9.5 工具冒烟

- [ ] GitHub Issues 查询
- [ ] 内部 API 调用
- [ ] 云资源操作

### 9.6 文档

- [ ] README.md（项目介绍、快速开始、架构链接）
- [ ] Swagger UI 自动生成（FastAPI 自带）

## 依赖

- Feature 1-8、1.1、1.2 全部完成

## 参考

- `architecture/devops/cicd.md`
- `architecture/overall_architecture.md` #7 部署配置
