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
- 每个 Mermaid code block 前必须标注图类型和用途，格式示例：
  `图类型：**Sequence Diagram（时序图）**。用于说明请求在组件之间的调用顺序。`

### Standard Architecture Diagram Types

架构文档优先使用以下标准图类型。Sequence Diagram 和 Component Diagram 都是标准图；
区别是前者回答“运行时按什么顺序发生”，后者回答“系统由哪些部分组成”。

| 图类型 | Mermaid 推荐语法 | 适用问题 |
|--------|------------------|----------|
| System Context Diagram（系统上下文图） | `flowchart` | 谁使用系统，系统连接哪些外部服务、平台或边界 |
| Container / Deployment Diagram（容器 / 部署图） | `flowchart` | 前端、BFF、Service、DB、Gateway、云资源如何部署和连通 |
| Component Diagram（组件图） | `flowchart` | 一个服务或子系统内部有哪些模块、职责和依赖 |
| Sequence Diagram（时序图） | `sequenceDiagram` | 一个请求、事件或异步流程按什么顺序调用哪些组件 |
| State Diagram（状态机图） | `stateDiagram-v2` | Session、Conversation、Job、OAuth flow 等状态如何转换 |
| ER Diagram（实体关系图） | `erDiagram` | 数据表、实体、主外键和 cardinality |
| Class Diagram（类图） | `classDiagram` | 类、接口、DTO、domain object 的结构关系 |
| Data Flow / Trust Boundary Diagram（数据流 / 信任边界图） | `flowchart` | 敏感数据、凭据、用户身份跨哪些边界流动 |
| Use Case Diagram（用例图） | `flowchart` | 用户角色和产品能力范围；仅用于需求澄清，不替代架构图 |
| Gantt Chart（计划图） | `gantt` | 阶段计划、依赖和实施顺序 |

选择规则：

- 讲静态结构：优先 System Context、Container、Deployment 或 Component Diagram。
- 讲动态调用：优先 Sequence Diagram。
- 讲生命周期：优先 State Diagram。
- 讲数据库：优先 ER Diagram。
- 讲安全边界或凭据流动：优先 Data Flow / Trust Boundary Diagram。
- 讲用户能做什么：可用 Use Case Diagram，但不要用它表达服务内部架构。

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
