# Architecture Decision Records (ADR)

Personal Assistant 项目的架构决策记录。采用 [Michael Nygard 的 ADR 格式](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)。

## 决策列表

| 编号 | 标题 | 状态 | 决策 |
|------|------|------|------|
| [ADR-001](ADR-001-python-3.12.md) | Python 3.12 作为运行时 | Accepted | 使用 Python 3.12 替代即将 EOL 的 3.10 |
| [ADR-002](ADR-002-langgraph.md) | LangGraph 作为 Agent 编排框架 | Superseded by [ADR-009] | 使用 LangGraph StateGraph 实现 Agent 推理循环 |
| [ADR-003](ADR-003-agentarts-platform.md) | AgentArts 平台作为基础设施 | Accepted | 全面采用 AgentArts（Memory/Identity/Gateway/Sandbox） |
| [ADR-004](ADR-004-fastapi-over-agentarts-runtime-app.md) | FastAPI 替代 AgentArtsRuntimeApp | Accepted | 标准 FastAPI 获取更多路由自由度 |
| [ADR-005](ADR-005-maas-llm-platform.md) | 华为云 MaaS 作为 LLM 推理平台 | Accepted (Amended by ADR-011) | MaaS 平台 + DeepSeek-V4-Pro，模型可替换，多 provider 共存 |
| [ADR-006](ADR-006-iac-cdktf-typescript.md) | 基础设施即代码（IaC）工具选型 | Accepted | AgentArts 层用 agentarts_config.yaml，基础资源层用 CDKTF (TypeScript) |
| [ADR-007](ADR-007-identity-provider.md) | Inbound Identity Provider 选型 | Accepted | Microsoft Entra ID 为主，GitHub / 国内 IdP 为备选，不用 Google |
| [ADR-008](ADR-008-web-chat-frontend-framework.md) | Web Chat 前端框架选型 | Accepted | Vite + React + TypeScript + Tailwind CSS，不用 Next.js |
| [ADR-009](ADR-009-deepagents.md) | deepagents 替代 LangGraph 裸用 | Accepted | 用 deepagents harness 替代手写 StateGraph，底层仍是 LangGraph |
| [ADR-010](ADR-010-astral-ecosystem-tooling.md) | Astral 生态工具链（uv + ruff） | Accepted | uv 管理包和虚拟环境，ruff 负责 linting 和 formatting |
| [ADR-011](ADR-011-multi-llm-provider.md) | 多 LLM Provider 可配置架构 | Accepted | `config.yaml` 管理多个 OpenAI-compatible provider，MaaS 默认，DeepSeek 官方备选 |

## 决策原则

1. **平台优先** — 优先使用 AgentArts 和华为云原生能力，展示平台完整链路
2. **可展示性** — 选型需体现 Agent 工程最佳实践，具简历展示价值
3. **简单够用** — 不引入超出当前需求的复杂度，保持架构清晰
