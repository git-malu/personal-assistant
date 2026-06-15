# Personal Assistant Client

基于 [AgentArts](https://www.huaweicloud.com/product/agentarts.html) 平台的 AI 助手 Web Chat 前端应用。提供对话界面、SSE 流式消息渲染、Markdown 内容展示，支持 Web Chat、飞书和 OfficeClaw 多接入渠道的客户端适配层。

Vite + React + TypeScript + Tailwind CSS + assistant-ui。支持 OAuth 登录（Microsoft Entra ID）、登录落地页和聊天界面。

## 目录结构

```
personal-assistant-client/
├── src/
│   ├── components/
│   │   ├── assistant-ui/             # assistant-ui 组件（thread, markdown-text, reasoning, attachment 等）
│   │   ├── ui/                       # shadcn/ui 基础组件（button, dialog, avatar, tooltip, collapsible）
│   │   ├── landing/                  # 登录落地页组件（LandingPage, LandingHero, FeatureTile 等）
│   │   ├── chat/                     # 聊天界面组件（ChatPage）
│   │   ├── RuntimeProvider.tsx       # assistant-ui RuntimeProvider 包装
│   │   ├── LoginButton.tsx           # OAuth 登录按钮
│   │   └── AuthGuard.tsx             # 认证守卫组件
│   ├── stores/
│   │   └── auth-store.ts            # 认证状态管理（MSAL）
│   ├── lib/
│   │   ├── chat-adapter.ts           # assistant-ui ChatModelAdapter（fetch POST + SSE）
│   │   ├── auth.ts                   # MSAL 认证配置
│   │   └── utils.ts                  # 工具函数（cn 等）
│   ├── types/
│   │   └── chat.ts                   # Message、SSEEvent 类型定义
│   ├── test/
│   │   └── setup.ts                  # Vitest 测试配置
│   ├── App.tsx                       # 根组件
│   ├── main.tsx                      # React 入口
│   ├── index.css                     # Tailwind 入口 + 自定义动画
│   └── vite-env.d.ts                # Vite 类型声明
├── index.html                     # Vite 入口 HTML
├── vite.config.ts                 # Vite 配置（代理 + React 插件 + Tailwind CSS）
├── tsconfig.json                  # TypeScript 配置
├── tsconfig.node.json             # Vite 配置文件 TypeScript 配置
├── package.json                   # 项目依赖与 scripts
├── netlify.toml                   # Netlify 部署配置（staging 环境）
├── DESIGN.md                      # 前端设计文档
└── .gitignore
```

## 环境要求

- Node.js >= 18
- npm >= 9

## 快速开始

### 1. 安装依赖

```bash
npm ci
```

### 2. 启动开发服务器

```bash
npm run dev
```

开发服务器默认监听 `http://localhost:5173`，`/invocations` 请求通过 Vite proxy 转发到 FastAPI（`http://localhost:8080`）。

确保后端服务已启动：

```bash
# 在 personal-assistant-service/ 下
uv run uvicorn app.main:app --port 8080 --reload
```

### 3. 打开浏览器

访问 `http://localhost:5173` 进入 Web Chat 对话界面。

生产部署到 Netlify 时，`POST /invocations` 由 `netlify/edge-functions/invocations.ts` 转发到 `AGENTARTS_INVOCATIONS_URL`，并在服务端通过 `AGENTARTS_API_KEY` 注入 `Authorization`。浏览器端不保存或发送 Gateway API key。

## 构建

### 开发构建

```bash
npm run build
```

产出 `dist/` 目录。生产环境部署至 OBS 静态网站托管（或 Netlify staging），不再由 FastAPI StaticFiles 服务。

### 预览构建产物

```bash
npm run preview
```

## 测试

```bash
# 运行全部测试
npm test

# watch 模式
npm run test:watch
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 构建工具 | Vite 6 |
| UI 框架 | React 19 + assistant-ui 0.14 |
| 语言 | TypeScript 5.8 (strict) |
| 样式 | Tailwind CSS 4 + shadcn/ui |
| Markdown 渲染 | @assistant-ui/react-markdown |
| 测试 | Vitest + @testing-library/react |

## 架构

```
浏览器 ──GET /──→ Vite Dev Server (:5173) ──proxy /invocations──→ FastAPI (:8080)
  │                    │                                    │
  │  React App         │                                    │
  │  ├─ RuntimeProvider │                                    │
  │  │  └─ Thread       │                                    │
  │  │     └─ assistant-ui markdown / reasoning              │
  │  ├─ LoginPlaceholder│                                    │
  │  └─ assistant-ui runtime ─┘── fetch POST + SSE ───────→ /invocations
  │
  └── 生产模式 ── OBS 静态网站 / Netlify ── serve dist/ ──→ CDN → 同上
```

## SSE 协议

前端通过 `fetch` 向 `POST /invocations` 发送 `{"message":"...","stream":true}`，并消费响应体中的 SSE 流：

```
data: {"token":"你","done":false}

data: {"token":"好","done":false}

data: {"token":"","done":true}
```

- `token`：当前 token 文本
- `done`：`true` 表示流结束

## 后续 Feature

| Feature | 内容 | 状态 |
|---------|------|------|
| Feature 4 | OAuth 登录 UI（MSAL + Microsoft Entra ID） | 已实现 |
| Feature 5 | 飞书客户端适配 | [Planned — not yet implemented] |
| Feature 3 | OfficeClaw 客户端适配 | [Planned — not yet implemented] |
