# AGENTS.md

> 本文件是 **personal-assistant-meta** 目录的专用 instructions，仅适用于该目录下的相关工作。

## Directory Guide

`personal-assistant-meta/` 是系统的 **design hub**，所有设计讨论、架构决策和变更规划都在此目录下进行。

### 目录关系

```
personal-assistant-meta/
├── specs/          # What the system does (用户视角)
├── architecture/   # How the system works (技术视角)
└── issues/         # What needs to change (增量修改)
```

### specs/ — 功能规格

描述系统**当前或目标**的能力，侧重于用户视角的功能描述。可以反映现状（as-is），也可以描述未来目标（to-be），作为系统的 **baseline**。

- `specs/` 回答："系统能做什么？用户如何使用？"
- 以用户故事、功能需求和交互流程为主线组织
- **入口文件**：`specs/overall_specifications.md` 是该目录的根入口，目录内所有其他文件都必须被该文件引用（直接或间接）

### architecture/ — 系统架构

`specs/` 的具体设计具象化，描述系统如何从技术层面实现这些能力。同样可作为 baseline，既可以反映当前架构，也可以描述目标架构。

- `architecture/` 回答："系统由哪些组件构成？它们如何协作？"
- 以组件图、模块划分、数据流和接口定义为主线组织
- **入口文件**：`architecture/overall_architecture.md` 是该目录的根入口，目录内所有其他文件都必须被该文件引用（直接或间接）

### issues/ — 变更任务

`issues/` 是**增量修改**的描述——每一份 issue 代表一个相对于 baseline 的变更请求。

- `features/` — 新增能力
- `bugs/` — 缺陷修复
- `refactor/` — 重构改进

每个 issue 需明确说明：变更动机、影响的 specs/architecture 文档、预期结果。

## Diagram-First Philosophy

- **所有 diagram 必须使用 [Mermaid](https://mermaid.js.org/) 格式**，包括但不限于 Flowchart、Sequence Diagram、Class Diagram、State Diagram、ER Diagram、Gantt Chart、Pie Chart 等。
- 禁止使用 ASCII art 或其他非 Mermaid 格式绘制图表。
- 在 meta 目录下进行设计讨论时，**优先用 diagram 表达设计意图**。文字说明是对 diagram 的补充，而非替代。

## Language Policy

- **Primary language for documentation**: Chinese（中文）
- **Secondary language**: English（英文）
- **Software engineering terminology**: Always use the original English term. Do NOT translate technical terms into Chinese.

### 专业术语对照示例

以下是本项目文档中必须使用英文原文的术语，以及常见的错误翻译对照：

| English (use this)          | Chinese (DO NOT use)      |
| --------------------------- | ------------------------- |
| Agent                       | 智能体（正文可使用）        |
| Runtime                     | 运行时                     |
| Sandbox                     | 沙箱                       |
| Memory                      | 记忆库                     |
| Gateway                     | 网关                       |
| SDK                         | -                          |
| MCP (Model Context Protocol) | -                         |
| API                         | -                          |
| CLI                         | -                          |
| IAM                         | -                          |
| QPS                         | -                          |
| Dockerfile                  | -                          |
| CI/CD                       | -                          |
| PR (Pull Request)           | -                          |
| commit                      | -                          |
| branch                      | -                          |
| deploy / deployment         | -                          |
| rollback                    | -                          |
| scaling                     | -                          |
| container                   | -                          |
| image                       | -                          |
| token                       | -                          |
| prompt                      | -                          |
| RAG                         | -                          |
| LLM                         | -                          |

**原则**：当一个术语在软件工程领域有广泛接受的英文表达时，优先使用英文原文，避免生硬的直译造成歧义。

### 正文写作规范

- 正文以中文撰写，保持自然流畅。
- 英文术语首次出现时可附中文说明，后续直接使用英文原文。
- 代码块、配置文件、命令行示例保持英文。
- 代码注释推荐英文，但面向中文读者的说明性注释可使用中文。
- README.md、CHANGELOG.md 等对外文档以中文为主，英文摘要可附在关键段落后方。

## The Three-Question Gate

在做任何设计决策时，必须通过以下三道闸门——用三个问题审视每一个选择：

1. **Is it best practice?**
   - 这个方案是否遵循了公认的软件工程最佳实践（如 SOLID 原则、Separation of Concerns、Defense in Depth）？
   - 一位有经验的工程师在 code review 中是否会认可这个方案？

2. **Is it industry standard?**
   - 这是否是业界有影响力的组织在生产系统中广泛采用的方案？
   - 是否与主流云厂商、框架作者或平台厂商推荐的模式一致？

3. **Is it conventional?**
   - 对于这类问题，这是否是最常见、最广为人知的解决方案？
   - 一个熟悉该技术栈的新成员是否能立即理解并预期这个方案？

三个问题的答案都应当为 **Yes**。若任一答案为 No，需在文档中明确记录偏离原因及 trade-off 分析。
