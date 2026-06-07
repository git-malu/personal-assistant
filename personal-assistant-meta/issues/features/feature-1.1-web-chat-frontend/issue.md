---
status: backlog
---

# Feature 1.1: Web Chat 前端工程化

本 Feature 将 Feature 1 的 `web/index.html` 单文件前端升级为工程化前端项目，技术栈按 ADR-008 + ADR-013 决策：Vite + React + TypeScript + Tailwind CSS，使用 assistant-ui 作为 AI Chat UI 组件库。

---

## 背景

Feature 1 用单 HTML 文件快速验证了 Agent 骨架和 SSE 流式对话链路。该文件具备基本聊天功能（消息列表、文本输入、SSE 流式渲染），但缺少：

- 组件化架构（所有 UI 和逻辑塞在一个文件）
- 工程化工具链（模块打包、HMR、TypeScript）
- 样式系统（内联 CSS，无暗色模式、响应式断点）
- OAuth 登录流程（Feature 4 需要前端配合）
- 多轮对话管理、消息持久化、错误状态 UI

ADR-008 已决策 Vite + React + TypeScript + Tailwind CSS。ADR-013 进一步决策使用 assistant-ui 作为 AI Chat UI 组件库，替代原计划的 shadcn/ui + 手写 Chat 组件方案。assistant-ui 通过 `ChatModelAdapter` 接 FastAPI `/chat/stream` SSE 端点，开箱提供消息列表、流式渲染、Markdown+代码高亮、消息编辑/分支等完整 Chat 交互。

## 范围

- `personal-assistant-client/` 目录初始化（Vite + React + TypeScript + Tailwind CSS）
- 集成 assistant-ui：安装 `@assistant-ui/react` + `@assistant-ui/react-ai-sdk`，配置 shadcn/ui 主题（assistant-ui 使用 shadcn/ui 分发模型，主题可定制）
- 实现 `ChatModelAdapter`：一个 `async run()` 函数，对接 FastAPI `/chat/stream` SSE 端点——assistant-ui 接管所有 UI（消息列表、流式渲染、Markdown、编辑/分支）
- 定制 assistant-ui 主题以匹配项目视觉风格（iOS 风格色板、暗色模式）
- OAuth 登录入口预留（assistant-ui 的无障碍 shell 中嵌入登录/用户状态）
- 构建产物对接 FastAPI `StaticFiles` mount
- 开发模式代理配置（Vite dev server proxy → FastAPI）

## 不涉及

- OAuth 登录 UI（Feature 4 的前端适配，本 Feature 只预留入口）
- 飞书/OfficeClaw 客户端适配（Feature 5/3）
- 消息持久化（Feature 2 Memory 的前端配合）
- OBS/CDN 部署（Feature 9 或后续部署 Feature）

## 任务拆解

### 1.1.1 项目初始化

- [ ] `npm create vite@latest personal-assistant-client -- --template react-ts`
- [ ] 安装依赖：`@assistant-ui/react @assistant-ui/react-ai-sdk @ai-sdk/react tailwindcss @tailwindcss/vite`
- [ ] 配置 Tailwind（`tailwind.config.ts`，iOS 风格色板）—— assistant-ui 使用 Tailwind，通过 CSS 变量定制主题
- [ ] 配置 Vite 代理（`/api/*` → `localhost:8080`）
- [ ] 目录结构：`src/components/`, `src/lib/`, `src/types/`

### 1.1.2 assistant-ui 集成

- [ ] 创建 `ChatModelAdapter`（`src/lib/chat-adapter.ts`）：实现 `async run()` 函数
  - 将 assistant-ui 的消息格式转换为 FastAPI `/chat/stream` 请求
  - 读取 SSE 响应流，将 token 转换为 assistant-ui 标准流式格式
  - 处理 `done` / `error` 信号
- [ ] 创建 `AssistantThread` 组件（`src/components/ChatThread.tsx`）
  - 使用 `useLocalRuntime` + `ChatModelAdapter` 初始化 assistant-ui 运行时
  - 挂载 `Thread` 主组件——获得消息列表、流式渲染、Markdown+代码高亮的完整 Chat UI
- [ ] 在 `App.tsx` 中集成：`AssistantRuntimeProvider` 包裹应用根组件
- [ ] 定制主题：通过 CSS 变量覆盖 assistant-ui 默认样式，匹配项目 iOS 风格色板

### 1.1.3 错误处理和增强

- [ ] 连接中断处理：`ChatModelAdapter` 中 catch fetch 异常 → 转换为 assistant-ui 错误格式
- [ ] HTTP 错误处理：非 200 响应 → 解析错误信息展示在 UI 中
- [ ] 超时处理：`AbortSignal` 超时自动中断

### 1.1.4 构建和集成

- [ ] `vite build` → `personal-assistant-client/dist/`
- [ ] FastAPI `StaticFiles` mount 指向 `dist/`（替换原来的 `web/`）
- [ ] 验证：`npm run dev` → 代理到 FastAPI → 聊天正常（assistant-ui 界面运行）
- [ ] 验证：`npm run build` → FastAPI serve 静态文件 → 聊天正常

### 1.1.5 清理

- [ ] 删除 Feature 1 的 `personal-assistant-service/web/index.html`
- [ ] 更新 `frontend_architecture.md` 反映新前端项目路径

## 验证

- [ ] `npm run dev` → 浏览器打开 → 看到 assistant-ui 聊天界面
- [ ] 输入消息 → SSE 流式返回，逐 token 渲染 → 消息气泡正常显示
- [ ] Markdown 渲染正确（标题、列表、代码块 + 语法高亮）
- [ ] 多轮对话不串消息、不崩溃
- [ ] 断网/服务器宕机 → 界面显示错误提示（不白屏）
- [ ] `npm run build` → FastAPI serve `dist/` → 功能同开发模式
- [ ] 确认与 `/playground`（Chainlit）共存，互不影响

## 依赖

- Feature 1（Agent 骨架 + `/chat/stream` SSE 端点）

## 可并行

- Feature 2（Memory 集成）— 前端和后端独立，无冲突
- Feature 1.2（PostgreSQL）— 独立基础设施

## 参考

- ADR-008: Web Chat 前端框架选型（Vite + React + TypeScript + Tailwind CSS）
- ADR-013: AI Chat UI 组件库选型（assistant-ui 替代 shadcn/ui）
- `architecture/frontend_architecture.md` #2.1 Web Chat
- `architecture/frontend_architecture.md` #6.2 部署（Phase 1 同容器 serve）
- [assistant-ui 文档 — Custom Backend](https://www.assistant-ui.com/docs/runtimes/custom/local-runtime)
