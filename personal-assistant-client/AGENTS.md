# personal-assistant-client

> 本文件是 `personal-assistant-client/` 目录的专用 instructions，仅适用于该目录下的相关工作。开始前先阅读项目根目录的 [`AGENTS.md`](../AGENTS.md)。

## Directory Guide

`personal-assistant-client/` 是 Personal Assistant 的 Web Chat 前端应用，负责用户登录、对话界面、SSE 流式消息渲染、Markdown 内容展示，以及 Cloudflare Pages Function same-origin `/invocations` proxy。当前 production 主入口为 Web Chat；飞书和 OfficeClaw 渠道仍在规划中。

## Tech Stack

- **核心框架**: React 19, TypeScript 5.8, Vite 6
- **UI 与样式**: Tailwind CSS v4, shadcn/ui, Radix UI / Base UI, Lucide React
- **对话/Agent 组件层**: `@assistant-ui/react`, `@assistant-ui/react-markdown`, `remark-gfm`
- **认证与状态**: Microsoft Entra ID / MSAL, Zustand
- **部署**: Cloudflare Pages + Pages Functions, Wrangler
- **测试工具**: Vitest, React Testing Library, jsdom

## Directory Structure

```text
personal-assistant-client/
├── src/
│   ├── components/          # assistant-ui、ui、landing、chat 等组件
│   ├── lib/                 # chat adapter、auth、utils
│   ├── stores/              # Zustand state
│   ├── types/               # TypeScript domain types
│   ├── test/                # Vitest setup
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── functions/
│   └── invocations.js       # Cloudflare Pages Function proxy
├── DESIGN.md                # Design tokens 与 UI 规范
├── package.json
├── vite.config.ts
├── wrangler.toml
└── AGENTS.md
```

## Build and Test Commands

- **安装依赖**: `npm ci`（需要更新 lockfile 时才使用 `npm install`）
- **本地启动**: `npm run dev`
- **构建生产产物**: `npm run build`
- **运行测试**: `npm run test`
- **Watch 测试**: `npm run test:watch`
- **Cloudflare Pages 本地预览**: `npm run pages:dev`
- **Cloudflare Pages 手动部署**: `npm run pages:deploy`

## Code Style Guidelines

- 遵循 React 官方最佳实践以及 TypeScript strict 类型安全原则。
- 样式遵循 [`DESIGN.md`](./DESIGN.md) 中定义的 design tokens。优先使用 Tailwind CSS token 化 class，禁止内联或硬编码 hex 颜色和随意绝对像素值。
- 使用已有 shadcn/ui、assistant-ui、Radix/Base UI 和 Lucide 组件；新增 UI 控件需保持现有 Apple 风格设计语言。
- 客户端逻辑保持轻量，复杂业务逻辑、外部工具调用和持久化逻辑应放在 Service 层。
- `functions/invocations.js` 是生产 proxy 的关键路径，修改时必须考虑 JWT、SSE streaming、headers 透传和 error handling。

## Testing Instructions

- 组件和前端逻辑使用 Vitest + React Testing Library。
- 修改 auth、SSE、Cloudflare Pages Function 或 runtime config 时，必须补充或更新相关测试。
- 提交前至少运行 `npm run test`；涉及类型或构建配置时运行 `npm run build`。

## Runtime Notes

- 本地 dev 默认使用 Vite proxy 将 `/invocations` 转发到 `http://localhost:8080`。
- `.env.example` 是配置入口；`VITE_*` 变量会进入浏览器 bundle，不得放 Secret。
- Pages Function runtime 配置通过 Cloudflare `context.env` 读取；敏感值必须使用 Cloudflare Secret。
