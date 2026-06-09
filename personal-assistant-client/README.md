# Personal Assistant Client

基于 [AgentArts](https://www.huaweicloud.com/product/agentarts.html) 平台的 AI 助手 Web Chat 前端应用。提供对话界面、SSE 流式消息渲染、Markdown 内容展示，支持 Web Chat、飞书和 OfficeClaw 多接入渠道的客户端适配层。

当前为 **Feature 1.1**（Web Chat 前端工程化）——Vite + React + TypeScript + Tailwind CSS。

## 目录结构

```
personal-assistant-client/
├── src/
│   ├── components/
│   │   ├── ChatContainer.tsx      # 主布局（header + messages + input）
│   │   ├── ChatInput.tsx          # 自动伸缩输入框（Enter 发送 / Shift+Enter 换行）
│   │   ├── LoginPlaceholder.tsx   # OAuth 登录占位横幅（Feature 4 前不可交互）
│   │   ├── MessageBubble.tsx      # 消息气泡（user 蓝 / assistant 灰，Markdown 渲染）
│   │   ├── MessageList.tsx        # 消息列表容器（自动滚底）
│   │   └── StreamingText.tsx      # 流式文本渲染（逐 token + 光标动画）
│   ├── hooks/
│   │   └── useChat.ts             # SSE 连接管理 hook（EventSource + 并发保护）
│   ├── types/
│   │   └── chat.ts                # Message、SSEEvent 类型定义
│   ├── App.tsx                    # 根组件
│   ├── main.tsx                   # React 入口
│   ├── index.css                  # Tailwind 入口 + 自定义动画
│   └── vite-env.d.ts             # Vite 类型声明
├── index.html                     # Vite 入口 HTML
├── vite.config.ts                 # Vite 配置（代理 + React 插件 + Tailwind CSS）
├── tailwind.config.ts             # Tailwind CSS 配置（可选，v4 用 CSS-first）
├── tsconfig.json                  # TypeScript 配置
├── tsconfig.node.json             # Vite 配置文件 TypeScript 配置
├── package.json                   # 项目依赖与 scripts
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

开发服务器默认监听 `http://localhost:5173`，`/api/*` 请求通过 Vite proxy 转发到 FastAPI（`http://localhost:8080`）。

确保后端服务已启动：

```bash
# 在 personal-assistant-service/ 下
MODEL_API_KEY="<your-api-key>" uv run uvicorn app.main:app --port 8080 --reload
```

### 3. 打开浏览器

访问 `http://localhost:5173` 进入 Web Chat 对话界面。

## 构建

### 开发构建

```bash
npm run build
```

产出 `dist/` 目录，由 FastAPI `StaticFiles` mount 服务。

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
| UI 框架 | React 19 |
| 语言 | TypeScript 5.8 (strict) |
| 样式 | Tailwind CSS 4 |
| Markdown 渲染 | react-markdown 9 + rehype-highlight |
| 测试 | Vitest 4 + @testing-library/react |
| 代码高亮 | highlight.js |

## 架构

```
浏览器 ──GET /──→ Vite Dev Server (:5173) ──proxy /api/*, /invocations/*──→ FastAPI (:8080)
  │                    │                                    │
  │  React App         │                                    │
  │  ├─ ChatContainer  │                                    │
  │  │  ├─ MessageList │                                    │
  │  │  │  └─ MessageBubble × N                             │
  │  │  │     └─ StreamingText (react-markdown)             │
  │  │  └─ ChatInput    │                                    │
  │  └─ useChat hook ───┘── EventSource ── SSE ────────────→ /invocations/stream
  │                                                                   │
  └── 生产模式 ──GET /──→ FastAPI StaticFiles ── serve dist/ ──→ 同上
```

## SSE 协议

前端通过原生 `EventSource` 消费后端的 SSE 流：

```
data: {"token":"你","done":false}

data: {"token":"好","done":false}

data: {"token":"","done":true}
```

- `token`：当前 token 文本
- `done`：`true` 表示流结束

## 后续 Feature

| Feature | 内容 |
|---------|------|
| Feature 4 | OAuth 登录 UI（替换 LoginPlaceholder） |
| Feature 5 | 飞书客户端适配 |
| Feature 3 | OfficeClaw 客户端适配 |
| Feature 9 | OBS/CDN 部署（独立静态托管） |
