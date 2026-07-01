# Personal Assistant

基于 [AgentArts](https://www.huaweicloud.com/product/agentarts.html) 平台的对话式 AI 助手。系统目标是通过自然语言管理日程、邮件、笔记和任务，具备跨 Session Memory 和用户委托能力。当前 production 主入口为 Web Chat；飞书直连和 OfficeClaw 仍按 roadmap 推进。

## Development Workflow

系统开发遵循 5 步流水线流程，详细流程见各目录下的 `AGENTS.md`：

1. **Issue 创建**：在 `personal-assistant-meta/issues/` 下创建 issue，描述变更动机和预期结果。
2. **Meta 阶段**：meta-manager 编排 meta-dev（并行分部撰写）、panel-chair（专家评审与合成），生成 Implementation Plan。
3. **Implementation**：service-manager、client-manager、infra-manager 按影响范围并行或串行执行实现。
4. **E2E 验证**：e2e-manager 执行端到端测试，验证 Service + Client 联调。
5. **Merge**：所有检查通过后合并到 `main` 分支。

## Directory Guide

```text
personal-assistant/
├── personal-assistant-client/   # Web Chat 前端，Cloudflare Pages Functions proxy
├── personal-assistant-service/  # AgentArts Runtime 后端，FastAPI + deepagents
├── personal-assistant-meta/     # Design hub，规格、架构、ADR 和 issue 规划
├── personal-assistant-infra/    # HuaweiCloud 基础资源 IaC，OpenTofu + HCL
└── personal-assistant-e2e/      # E2E 测试，pytest + httpx + Playwright
```

### `personal-assistant-client/`

提供 Web Chat 对话界面，负责用户登录、消息渲染、SSE 流式消费和 Cloudflare Pages same-origin `/invocations` proxy。开始前先阅读 [`personal-assistant-client/AGENTS.md`](./personal-assistant-client/AGENTS.md)。

### `personal-assistant-service/`

运行在 AgentArts Runtime 上的 AI Agent 服务，处理对话入口、Agent 编排、Inbound Identity、Outbound Credential Provider、OAuth2 用户委托和工具调用。开始前先阅读 [`personal-assistant-service/AGENTS.md`](./personal-assistant-service/AGENTS.md)。

### `personal-assistant-meta/`

所有设计讨论、架构决策和变更规划在此目录下进行。开始前先阅读 [`personal-assistant-meta/AGENTS.md`](./personal-assistant-meta/AGENTS.md)。

### `personal-assistant-infra/`

管理 HuaweiCloud 基础资源（当前包括 PostgreSQL RDS、VPC/Subnet 引用、Security Group、EIP、Agent Identity OAuth2 return URL bridge）。`.agentarts_config.yaml` 仍属于 Service/AgentArts 层，不放入 Infra。开始前先阅读 [`personal-assistant-infra/AGENTS.md`](./personal-assistant-infra/AGENTS.md)。

### `personal-assistant-e2e/`

端到端测试脚本目录，覆盖 Service + Client 联调场景。包含 regression tests（按 bug 组织）和 feature tests（按 feature 组织）。开始前先阅读 [`personal-assistant-e2e/AGENTS.md`](./personal-assistant-e2e/AGENTS.md)。

## Build and Test Commands

各个子系统的构建与测试命令独立管理。

| 子系统 | 常用命令 |
|--------|----------|
| Backend (`personal-assistant-service`) | `uv sync`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run pytest tests/` |
| Frontend (`personal-assistant-client`) | `npm ci`; `npm run build`; `npm run test`; `npm run pages:dev` |
| Infra (`personal-assistant-infra`) | `tofu fmt -check -recursive`; `tofu validate`; `tofu plan`; helper scripts 用 `uv run python ...` |
| E2E (`personal-assistant-e2e`) | `uv sync`; `uv run ruff check .`; `uv run pytest` |

## Code Style Guidelines

- **Python (Service/E2E/Infra helpers)**: 遵循 PEP8，使用 Ruff (`ruff check` 和 `ruff format`) 统一风格。
- **TypeScript/React (Client)**: 遵循 React 推荐规范和 TypeScript 类型安全原则。样式修改必须依赖 `DESIGN.md` 中的 design tokens，避免硬编码颜色和尺寸。
- **HCL (Infra)**: 使用 `tofu fmt` 格式化。Resource name 使用 snake_case；云端资源名称使用 `pa-` 前缀和 kebab-case。
- **文档 (Meta)**: 正文以中文为主，核心术语使用英文，如 Agent、API、SDK、Runtime。架构图必须使用 Mermaid。

## Testing Instructions

- 所有开发提交前应运行受影响子系统的 lint、unit tests 和 integration tests。
- 修改 API route 或 request/response schema 后，需在 Service 目录执行 `uv run python scripts/generate_openapi.py` 并提交 `openapi.json` 的预期 diff。
- 每个 issue 开发结束后，应在 E2E 阶段运行或编写相应端到端测试，确保 Service 和 Client 正常联调。
- Infra PR 和 `main` push 只能自动运行 `tofu plan`；`tofu apply` 只能通过人工 `workflow_dispatch` 执行。

## How to Run Locally

### Backend (`personal-assistant-service/`)

```bash
cd personal-assistant-service
uv sync
cp .env.example .env
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload \
  --log-config config/logging.dev.yaml
```

验证：

```bash
curl http://localhost:8080/ping
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "X-HW-AgentGateway-User-Id: dev-user" \
  -H "x-hw-agentarts-session-id: dev-session" \
  -d '{"message":"你好"}'
curl -N -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-HW-AgentGateway-User-Id: dev-user" \
  -H "x-hw-agentarts-session-id: dev-session" \
  -d '{"message":"你好","stream":true}'
# Playground: http://localhost:8080/invocations/playground
```

### Frontend (`personal-assistant-client/`)

```bash
cd personal-assistant-client
npm ci
npm run dev
```

Vite proxy 在 dev 模式下自动将 `/invocations` 请求转发到 `localhost:8080`。

## Deployment

| 组件 | 部署平台 | 技术栈 | 说明 |
|------|----------|--------|------|
| Backend | AgentArts Runtime (`cn-southwest-2`) | FastAPI, ARM64 container, port 8080 | 部署 runbook 见 [`agentarts-deploy-runbook.md`](./personal-assistant-meta/architecture/devops/agentarts-deploy-runbook.md) |
| Frontend | Cloudflare Pages | Vite + React + Pages Functions | 静态前端与 same-origin `/invocations` proxy |
| Infrastructure | HuaweiCloud + OpenTofu | HCL, OBS backend | RDS、EIP、Security Group、Agent Identity OAuth helper |

部署流程：Infra apply 准备基础资源和 secrets → Docker build ARM64 image → SWR push → `agentarts launch` 启动后端；Client merge 到 `main` 后由 GitHub Actions 执行 tests、Vite build 和 Wrangler Pages deployment。

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
