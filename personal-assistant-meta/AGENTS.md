# personal-assistant-meta

> 本文件是 `personal-assistant-meta/` 目录的专用 instructions，仅适用于该目录下的相关工作。开始前先阅读项目根目录的 [`AGENTS.md`](../AGENTS.md)。

## Project Overview

`personal-assistant-meta/` 是整个系统架构的 design hub。所有系统设计讨论、架构决策、文档规格和增量变更 issue 规划均在此目录下进行，不包含可执行的产品代码。

## Directory Guide

```text
personal-assistant-meta/
├── specs/          # What the system does (用户视角)
├── architecture/   # How the system works (技术视角)
│   ├── ADR/        # Architecture Decision Records
│   ├── auth/       # inbound/outbound auth 与 OAuth2 设计
│   └── devops/     # deployment、CI/CD、本地开发 runbook
└── issues/         # What needs to change (增量修改)
    ├── features/
    ├── bugs/
    ├── refactor/
    └── chores/
```

### `specs/`

描述系统当前或目标能力，侧重用户视角。入口文件是 `specs/overall_specifications.md`，目录内所有其他 specs 文件必须被该入口直接或间接引用。

### `architecture/`

描述系统如何从技术层面实现 specs。入口文件是 `architecture/overall_architecture.md`，目录内所有 architecture 文件必须被该入口直接或间接引用。

`architecture/cloud-service/huaweicloud/` 是涉及 AgentArts Runtime、HuaweiCloud 基础服务、部署约束、domain/routing、认证、可观测性或云端集成方案时的首要参考目录；其他云厂商目录仅作为对比参考。

### `issues/`

每个 issue 描述一个相对于 baseline 的增量变更请求，需明确变更动机、影响的 specs/architecture 文档、Implementation Plan 和预期结果。

## Build and Test Commands

- 本目录主要由 Markdown 和 Mermaid 图表组成，无传统编译构建命令。
- 修改 Mermaid 图表后，应使用 GitHub Preview、IDE Preview 或 Mermaid renderer 验证语法。
- 涉及 AgentArts API PDF 时，必须使用 PDF skill 阅读 `architecture/cloud-service/agentarts-api-pdf.pdf`，不要凭记忆改 API 细节。

## Code Style Guidelines

- **Diagram-First**: 架构设计和流程设计优先使用 Mermaid 图表表达。
- **Language Policy**: 正文首选中文，软件工程术语保留英文原文。
- **The Four-Question Gate**: 新架构决策或新库引入必须评估 Best practice、Industry standard、Conventional、Modern。
- **ADR 同步**: ADR Accepted 后，其结论必须体现到对应 architecture 文档中，不能只存在于 ADR。

## Testing Instructions

- 这里的 Testing 指严格的同行评审（Design/Code Review）。
- 提交 Meta 变更前，确保相关 specs/architecture 入口文件引用了新文档。
- 确保 Mermaid 图表语法正确，且图中的节点、边和术语与正文一致。
- Issue 的 Implementation Plan 必须能映射到 Service、Client、Infra、E2E 的实际变更和验证命令。

## Diagram-First Philosophy

- 所有 diagram 必须使用 Mermaid，包括 Flowchart、Sequence Diagram、Class Diagram、State Diagram、ER Diagram、Gantt Chart、Pie Chart 等。
- 禁止使用 ASCII art 或其他非 Mermaid 格式绘制架构图。
- 文字说明是对 diagram 的补充，不应替代关键结构和流程图。

## Language Policy

- **Primary language for documentation**: Chinese（中文）
- **Secondary language**: English（英文）
- **Software engineering terminology**: 保留英文原文，例如 Agent、Runtime、Memory、Gateway、SDK、MCP、API、CLI、IAM、Dockerfile、CI/CD、PR、commit、branch、deployment、rollback、container、image、token、prompt、RAG、LLM。

正文以中文撰写，保持自然流畅。代码块、配置文件、命令行示例保持英文。代码注释推荐英文，但面向中文读者的说明性注释可使用中文。

## The Four-Question Gate

在做任何设计决策时，必须通过以下四道闸门：

1. **Is it best practice?** 是否遵循公认的软件工程最佳实践？
2. **Is it industry standard?** 是否与主流云厂商、框架作者或平台厂商推荐模式一致？
3. **Is it conventional?** 熟悉该技术栈的新成员是否能立即理解并预期这个方案？
4. **Is it modern?** 是否代表当前技术生态方向，而非即将被淘汰的遗留技术？

四个问题的答案都应当为 Yes。若任一答案为 No，需在文档中明确记录偏离原因及 trade-off 分析。

## AgentArts API Reference

`architecture/cloud-service/agentarts-api-pdf.pdf` 是 AgentArts 平台官方 API 参考文档（PDF）。所有与 AgentArts Runtime 交互的接口定义、参数说明、错误码等均以此 PDF 为准。需要阅读或检索其中内容时，必须使用 PDF skill。
