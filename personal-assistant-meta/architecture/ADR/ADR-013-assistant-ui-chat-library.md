# ADR-013: AI Chat UI 组件库选型 — assistant-ui 替代 shadcn/ui

> 状态：Accepted | 日期：2026-06-07

---

## 背景

ADR-008 已决策 Web Chat 前端使用 Vite + React + TypeScript + Tailwind CSS。当时计划基于 **shadcn/ui** 的 Chat 代码块 + Vercel AI SDK (`useChat`) 手写聊天界面，包括 SSE 流式、Markdown 渲染、消息编辑/分支等所有交互逻辑。

经过进一步调研，发现 **assistant-ui** 作为 AI Chat 专用 React 组件库，可以在相同技术栈下大幅减少手写代码量，同时提供更完整的 Chat 交互体验。

## 决策

**使用 assistant-ui 替代 shadcn/ui 作为 Web Chat 的 AI Chat UI 组件库。** Chainlit 作为 Playground 调试工具保留，两者定位不同。

### 两个 Web Client 定位

| 名称 | 定位 | 技术基座 | 路径 | 面向用户 |
|------|------|---------|------|---------|
| **Web Chat** | 生产对话界面：聊天、工具调用可视化、领域功能（日程/任务/邮件） | **assistant-ui** (React) | `/` (Phase 2: CDN) | 所有最终用户 |
| **Playground** | Agent 调试工具：观察推理步骤、tool 调用链路、中间状态 | **Chainlit** (Python) | `/playground` | 开发者/运维 |

两者的核心区别：**Web Chat 是 WHAT（用户要什么），Playground 是 WHY（Agent 为什么这么回答）。**

### assistant-ui 的选择依据

| 因素 | assistant-ui | shadcn/ui Chat blocks | NLUX |
|------|-------------|----------------------|------|
| **npm 周下载** | **735.7K** (核心包 `@assistant-ui/react`) | N/A (代码片段) | ~5K |
| **流式渲染** | ✅ 内置 | ❌ 手写 | ✅ 内置 |
| **消息分支/编辑** | ✅ 内置 | ❌ 手写 | ❌ 不支持 |
| **Markdown + 代码高亮** | ✅ `react-streamdown` (153K/w) + `react-syntax-highlighter` (30K/w) | ⚠️ 需自己装 react-markdown | ✅ 内置 |
| **自定义后端** | ✅ `ChatModelAdapter` — 一个 `async run()` 函数 | ❌ 自己写 EventSource + 状态管理 | ✅ Custom Adapter |
| **文件附件** | ✅ 内置适配器 | ❌ 手写 | ⚠️ 基础 |
| **Generative UI** | ✅ LLM tool call → 自定义 React 组件 | ❌ 不支持 | ⚠️ 有限 |
| **Vite 支持** | ✅ 官方 `@assistant-ui/vite` 插件 | ✅ 可用 | ✅ 可用 |
| **无障碍 (a11y)** | ✅ Radix UI 基座 | ⚠️ 依赖手动配置 | ❌ |
| **分发模型** | shadcn/ui 风格（源码到项目，可任意修改） | 同 | npm 黑盒 |
| **商业支持** | Y Combinator + SaaStr Fund 投资 | 无 | 独立开发者 |
| **生态集成** | Vercel AI SDK / LangGraph / LangChain / AG-UI | 无 | OpenAI / HuggingFace |

### 关键能力：Custom Backend 集成

assistant-ui 通过 `LocalRuntime` + `ChatModelAdapter` 接入任意后端。接入项目的 AgentArts FastAPI 仅需实现一个 `async run()` 函数：

```typescript
const modelAdapter: ChatModelAdapter = {
  async run({ messages, abortSignal }) {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
      signal: abortSignal,
    });
    // 返回 assistant-ui 标准流式格式
    return new ReadableStream({ ... });
  },
};
```

### 关键能力：Generative UI

assistant-ui 支持将 LLM tool call 映射为自定义 React 组件，为后续 Feature 提供嵌入能力：

```typescript
const CalendarTool = makeToolUI({
  toolName: "list_events",
  render: ({ result }) => <CalendarCard events={result.events} />,
});
```

这意味着**日程卡片、任务面板、邮件摘要**等可以自然地出现在对话流中，而不是另开页面。

## 拒绝的方案

### shadcn/ui Chat blocks（原 ADR-008 方案）

shadcn/ui 的 Chat 模板仅提供**视觉骨架**（气泡样式、输入框布局），所有核心交互逻辑需自己实现：
- EventSource SSE 管理（连接/重连/中断）
- 流式 token 追加和渲染
- 消息编辑、回退、重新生成
- 文件上传和附件管理

这些正是 assistant-ui 开箱提供的。继续手写这些通用能力属于"重新发明轮子"，与项目"追求复用"的原则矛盾。

### NLUX

功能集明显小于 assistant-ui。缺少消息分支/编辑、Generative UI、无障碍支持。社区规模差距 150 倍，长期维护风险更高。

## 影响

- ADR-008 的技术栈中 **shadcn/ui 被 assistant-ui 取代**，其余（Vite + React + TypeScript + Tailwind CSS）不变
- `feature-1.1-web-chat-frontend` 的实现方式从"手写 Chat 组件"变为"集成 assistant-ui + 写 `ChatModelAdapter` + 定制主题"
- Web Chat 的开发工作量大幅降低：消息列表、流式渲染、Markdown、编辑/分支等通用能力全部由 assistant-ui 提供
- 后续 Feature 可通过 Generative UI 将领域组件（日程/任务/邮件）嵌入对话流
- Chainlit Playground (feature-1.4) 不受影响，独立演进

## 参考

- [assistant-ui 官方文档](https://www.assistant-ui.com/docs)
- [assistant-ui GitHub](https://github.com/assistant-ui/assistant-ui)
- ADR-008 — Web Chat 前端框架选型
- `issues/features/feature-1.4-chainlit-playground/issue.md` — Playground 调试工具
