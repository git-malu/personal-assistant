
# Personal Assistant

基于 [AgentArts](https://www.huaweicloud.com/product/agentarts.html) 平台的对话式 AI 助手。通过自然语言管理日程、邮件、笔记和任务，具备跨 Session Memory 和用户委托能力。支持 Web Chat、飞书直连和 OfficeClaw 三种接入渠道。

## Directory Guide

```
personal-assistant/
├── personal-assistant-client/   # 前端应用，Web Chat 界面及飞书/OfficeClaw 客户端适配
├── personal-assistant-service/  # 后端服务，AgentArts Runtime 上的 AI Agent 服务
├── personal-assistant-meta/     # Design hub，所有设计讨论、架构决策和变更规划
└── .gitnexus/                   # GitNexus 索引配置
```

### personal-assistant-client/ — 前端应用

提供 Web Chat 对话界面，负责用户交互、消息渲染，以及飞书、OfficeClaw 等多接入渠道的客户端适配层。

### personal-assistant-service/ — 后端服务

运行在 AgentArts Runtime 上的 AI Agent 服务，处理对话逻辑、日程/邮件/笔记/任务管理、跨 Session Memory、用户委托等核心能力。

### personal-assistant-meta/ — Design Hub

所有设计讨论、架构决策和变更规划在此目录下进行。开始前先阅读 [`personal-assistant-meta/AGENTS.md`](./personal-assistant-meta/AGENTS.md) 了解设计规范和约束。

---

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **personal-assistant** (200 symbols, 197 relationships, 0 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/personal-assistant/context` | Codebase overview, check index freshness |
| `gitnexus://repo/personal-assistant/clusters` | All functional areas |
| `gitnexus://repo/personal-assistant/processes` | All execution flows |
| `gitnexus://repo/personal-assistant/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
