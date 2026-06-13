
# Personal Assistant

基于 [AgentArts](https://www.huaweicloud.com/product/agentarts.html) 平台的对话式 AI 助手。通过自然语言管理日程、邮件、笔记和任务，具备跨 Session Memory 和用户委托能力。支持 Web Chat、飞书直连和 OfficeClaw 三种接入渠道。

## Development Workflow

系统开发遵循 5 步流水线流程，详细流程见各目录下的 AGENTS.md：

1. **Issue 创建**：在 `personal-assistant-meta/issues/` 下创建 issue，描述变更动机和预期结果
2. **Meta 阶段**：meta-manager 编排 meta-dev（并行分部撰写）、panel-chair（专家评审与合成），生成 Implementation Plan
3. **Implementation**：service-manager、client-manager、infra-manager 并行执行实现
4. **E2E 验证**：e2e-manager 执行端到端测试，验证 Service + Client 联调
5. **Merge**：所有检查通过后合并到 main 分支

## Directory Guide

```
personal-assistant/
├── personal-assistant-client/   # 前端应用，Web Chat 界面及飞书/OfficeClaw 客户端适配
├── personal-assistant-service/  # 后端服务，AgentArts Runtime 上的 AI Agent 服务
├── personal-assistant-meta/     # Design hub，所有设计讨论、架构决策和变更规划
├── personal-assistant-infra/    # 基础设施即代码（IaC），OpenTofu + HCL，管理华为云资源
└── personal-assistant-e2e/      # E2E 测试脚本，pytest，覆盖 Service+Client 联调
```

### personal-assistant-client/ — 前端应用

提供 Web Chat 对话界面，负责用户交互、消息渲染，以及飞书、OfficeClaw 等多接入渠道的客户端适配层。开始前先阅读 [`personal-assistant-client/AGENTS.md`](./personal-assistant-client/AGENTS.md) 了解该目录的详细规范。

### personal-assistant-service/ — 后端服务

运行在 AgentArts Runtime 上的 AI Agent 服务，处理对话逻辑、日程/邮件/笔记/任务管理、跨 Session Memory、用户委托等核心能力。开始前先阅读 [`personal-assistant-service/AGENTS.md`](./personal-assistant-service/AGENTS.md) 了解该目录的详细规范。

### personal-assistant-meta/ — Design Hub

所有设计讨论、架构决策和变更规划在此目录下进行。开始前先阅读 [`personal-assistant-meta/AGENTS.md`](./personal-assistant-meta/AGENTS.md) 了解设计规范和约束。

### personal-assistant-infra/ — 基础设施即代码

管理华为云基础资源（OBS、RDS、IAM、VPC、EIP、CDN 等）的 IaC 目录，使用 OpenTofu + HCL 编写。`.agentarts_config.yaml` 管 AgentArts 层（容器/认证/可观测），本目录管华为云基础资源层。开始前先阅读 [`personal-assistant-infra/AGENTS.md`](./personal-assistant-infra/AGENTS.md) 了解 IaC 规范、目录结构和常用命令。

### personal-assistant-e2e/ — E2E 测试

端到端测试脚本目录，使用 pytest 框架，覆盖 Service + Client 联调场景。包含回归测试（按 bug 组织，用于复现和验证修复）和功能测试（按 feature 组织）。开始前先阅读 [`personal-assistant-e2e/AGENTS.md`](./personal-assistant-e2e/AGENTS.md) 了解测试编写和运行规范。

## How to Run Locally

### Backend（`personal-assistant-service/`）

```bash
cd personal-assistant-service
uv sync
cp .env.example .env
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

验证：

```bash
curl http://localhost:8080/ping
curl -X POST http://localhost:8080/invocations -H "Content-Type: application/json" -d '{"message": "你好"}'
curl -N -X POST http://localhost:8080/invocations -H "Content-Type: application/json" -H "Accept: text/event-stream" -d '{"message":"你好","stream":true}'
# Playground: http://localhost:8080/invocations/playground
```

### Frontend（`personal-assistant-client/`）

```bash
cd personal-assistant-client
npm install
npm run dev
```

> Vite proxy 在 dev 模式下自动将 `/api` 请求转发到 `localhost:8080`。

## Deployment

| 组件 | 部署平台 | 技术栈 | 说明 |
|------|----------|--------|------|
| Backend | AgentArts Runtime（cn-southwest-2） | FastAPI, ARM64 容器, port 8080 | 部署 runbook 见 [`chore-1-agentarts-deploy/plan.md`](./personal-assistant-meta/issues/chores/chore-1-agentarts-deploy/plan.md) |
| Frontend | OBS 静态网站托管（cn-southwest-2） | Vite + React | 构建产物通过 obsutil 上传至 OBS bucket |
| Infrastructure | OpenTofu + HCL（`personal-assistant-infra/`） | HCL | 管理 OBS bucket 及华为云基础资源 |

**部署流程**：Docker build ARM64 镜像 → SWR push → agentarts launch 启动后端；`VITE_API_BASE_URL` 构建前端 → obsutil cp 上传至 OBS。

---

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **personal-assistant** (3,151 nodes, 4,061 edges, 24 clusters, 59 flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `gitnexus analyze --skip-agents-md --skip-skills` or `npx gitnexus analyze` in terminal first.

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
| Understand architecture / "How does X work?" | `.opencode/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.opencode/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.opencode/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.opencode/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.opencode/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.opencode/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
