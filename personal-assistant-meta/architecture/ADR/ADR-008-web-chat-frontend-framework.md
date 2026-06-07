# ADR-008: Web Chat 前端框架选型

> 状态：Accepted | 日期：2026-06-05

---

## 背景

Personal Assistant 的 Web Chat 前端需要选择一个 JavaScript 框架。前端职责：提供浏览器端对话界面，通过 SSE 接收流式响应，通过 OAuth 跳转完成 Microsoft Entra ID 登录。

候选方案：Vanilla HTML/JS、React (Vite)、React (Next.js)、Vue 3。

## 决策

**使用 Vite + React + TypeScript + Tailwind CSS。**

选择依据：

| 因素 | Vite + React | Next.js | Vanilla HTML/JS | Vue 3 |
|------|-------------|---------|-----------------|-------|
| **SSE 流式渲染** | Vercel AI SDK (`useChat`) 开箱可用 | 同 React | 手写 EventSource + DOM 更新 | 无成熟方案，需手写 |
| **Markdown 渲染** | react-markdown + rehype-highlight | 同 React | 引入 marked.js 等，集成麻烦 | 有方案但生态较小 |
| **部署方式** | 纯静态文件 → OBS 或 FastAPI mount | 需要 Node.js 运行时（SSR）或 static export（受限） | 纯静态文件 | 纯静态文件 |
| **架构匹配** | ✅ 前后端分离，与 FastAPI 后端职责清晰 | ❌ 自带 API Routes，与 FastAPI 路由层职责重叠 | ✅ 极简 | ✅ 前后端分离 |
| **团队技能** | 有 React 经验 | 有 React 经验 | 无框架依赖 | 有 Vue 经验 |
| **组件生态** | shadcn/ui 提供 Chat 模板 | 同 React | 无 | 有但 AI Chat 组件不如 React 成熟 |
| **构建速度** | Vite 秒级 HMR | Turbopack，较快 | 无需构建 | Vite 秒级 HMR |

## 拒绝的方案

### Next.js

Next.js 的核心价值（SSR、RSC、API Routes、Middleware）在本项目中全部多余：

- **SSR / RSC**：Chat 是纯客户端交互，无 SEO 需求，SSR 只会增加不必要的服务端复杂度
- **API Routes**：项目已有 FastAPI 后端处理所有逻辑（`/auth/callback`、`/chat/stream`），Next.js API Routes 会造成 Node.js 和 Python 双服务端并存，职责重叠
- **OAuth 冲突**：token 交换必须在后端（保护 client_secret），如果用 Next.js，需要决定 `/auth/callback` 走 Node 还是 FastAPI，增加无谓的架构决策
- **部署负担**：Next.js 需要 Node.js 运行时，而 Vite 构建产出纯静态文件，可直接托管 OBS

> 如果未来需要 SEO landing page（项目主页），可以用 Astro 或独立 Next.js 仓做，不影响 Chat 应用。

### Vanilla HTML/JS

Feature spec 中写了 `web/index.html` 方案作为 MVP 最小实现。这适合快速验证 SSE 链路，但作为正式方案有以下问题：

- Markdown 渲染、代码高亮、文件上传等功能加入后代码会快速失控
- 无组件化，UI 状态管理全靠 DOM 操作
- 无法利用 AI Chat 生态（`useChat` 等）

### Vue 3

技术栈有 Vue 经验，理论上可行。但 AI Chat 生态差距明显：

- 没有 `useChat` 级别的开箱方案，SSE 流式渲染需自行实现
- Chat UI 组件模板不如 React 生态成熟
- 投入产出比不如直接选 React

## 影响

- `personal-assistant-client/` 目录使用 Vite + React + TypeScript + Tailwind CSS 初始化
- 前端部署方式：Vite build 产出纯静态文件，托管到华为云 OBS（或本地开发时由 FastAPI StaticFiles mount）
- 不需要 Node.js 服务端运行时
- OAuth 登录流程全部由 FastAPI 后端处理，前端只负责发起跳转和携带 Cookie

## 技术栈

```
React 18+ / TypeScript
Vite                      — 构建工具
Tailwind CSS              — 样式
assistant-ui              — AI Chat UI 组件库（替代原计划的 shadcn/ui + 手写 SSE，详见 ADR-013）
@assistant-ui/react-ai-sdk — Vercel AI SDK 集成
@ai-sdk/react             — SSE 流式对话（useChat hook）
```

> **2026-06-07 更新**：shadcn/ui Chat 方案被 ADR-013 取代。assistant-ui 提供开箱即用的流式渲染、消息分支/编辑、Markdown+代码高亮、文件附件、Generative UI 等能力，与自定义后端通过 `ChatModelAdapter` 集成。

## 参考

- `architecture/frontend_architecture.md` — 前端架构设计
- `ADR-004` — FastAPI 替代 AgentArtsRuntimeApp
- `ADR-007` — Microsoft Entra ID 作为 Identity Provider
- `issues/features/feature-5-feishu-channel.md` — 飞书渠道 Feature Spec
