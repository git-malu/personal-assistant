# Personal Assistant — 前端架构

> 版本：v0.1 | 状态：Draft | 关联文档：`backend_architecture.md`

---

## 1. 概述

Personal Assistant 前端采用**多客户端架构**，所有客户端通过统一协议与 FastAPI 后端通信，共享同一套 Agent 处理逻辑和 Memory 空间。

```mermaid
flowchart LR
    subgraph Clients["🖥️ 前端（消息通道）"]
        direction TB
        WebChat["Web Chat<br/>浏览器"]
        FeishuDirect["飞书直连<br/>自定义 Bot"]
        OfficeClaw["OfficeClaw<br/>桌面客户端"]
    end

    subgraph Backend["☁️ FastAPI 后端"]
        Agent["Agent 处理逻辑<br/>（三端共享）"]
    end

    WebChat -->|"SSE / OAuth"| Backend
    FeishuDirect -->|"事件回调"| Backend
    OfficeClaw -->|"AgentArts 转发"| Backend
```

**核心原则**：前端只负责消息通道和协议适配，不做 Agent 逻辑。所有 Agent 推理、Memory、Tool 调用都在后端。

---

## 2. 三种前端方案

### 2.1 Web Chat

**接入方式**：浏览器直连 FastAPI `/chat/stream`（SSE）和 `/auth/callback`（OAuth）

```mermaid
sequenceDiagram
    actor User as 用户
    participant Browser as 浏览器
    participant FastAPI as FastAPI :8080
    participant Google as Google OAuth

    Note over User,Google: === 登录 ===
    User->>Browser: 打开 /chat
    Browser->>FastAPI: GET /chat
    FastAPI-->>Browser: 重定向 Google OAuth
    Browser->>Google: 授权
    Google-->>Browser: code → /auth/callback
    Browser->>FastAPI: GET /auth/callback?code=xxx
    FastAPI-->>Browser: Set-Cookie + Chat UI

    Note over User,Google: === 对话 ===
    User->>Browser: 输入消息
    Browser->>FastAPI: GET /chat/stream?q=...
    FastAPI-->>Browser: SSE: data: token...\n\n
    Browser-->>User: 逐字渲染
```

| 维度 | 说明 |
|------|------|
| **协议** | SSE (Server-Sent Events) 流式推送 |
| **认证** | Google OAuth → JWT Cookie |
| **路由** | `/chat/stream`, `/auth/callback` |
| **优势** | 完全自定义 UI/UX，不受平台限制 |
| **代价** | 需要自己开发前端页面 |

### 2.2 飞书直连

**接入方式**：自行创建飞书 Bot，飞书事件回调到 FastAPI `/feishu/webhook`

```mermaid
sequenceDiagram
    actor User as 飞书用户
    participant FS as 飞书服务器
    participant FastAPI as FastAPI :8080

    Note over User,FastAPI: === 首次验证 ===
    FS->>FastAPI: URL 验证 (Challenge)
    FastAPI-->>FS: 返回 challenge

    Note over User,FastAPI: === 对话 ===
    User->>FS: @Bot 帮我查日程
    FS->>FastAPI: POST /feishu/webhook
    Note right of FastAPI: 验证 Token<br/>解析消息内容<br/>调用 Agent 处理逻辑
    FastAPI-->>FS: 消息回复 API
    FS-->>User: 展示回复
```

| 维度 | 说明 |
|------|------|
| **协议** | 飞书 Webhook 事件回调 |
| **认证** | 飞书 Token 验证 + API Key |
| **路由** | `/feishu/webhook` |
| **优势** | 完全自主可控，支持飞书卡片等高级交互 |
| **代价** | 需要公网回调 URL，需要写飞书消息解析代码 |

### 2.3 OfficeClaw

**接入方式**：OfficeClaw 桌面客户端作为飞书/微信桥接器，通过 AgentArts 调用后端 `/invocations`

```mermaid
sequenceDiagram
    actor User as 飞书用户
    participant FS as 飞书服务器
    participant OC as OfficeClaw<br/>(Windows PC)
    participant AgentArts as AgentArts 平台
    participant FastAPI as FastAPI :8080

    User->>FS: @Agent 查日程
    FS->>OC: WebSocket 推送
    OC->>AgentArts: 调用 Agent
    AgentArts->>FastAPI: POST /invocations
    FastAPI-->>AgentArts: {"response": "..."}
    AgentArts-->>OC: 返回结果
    OC-->>FS: 发送回复
    FS-->>User: 看到回复
```

| 维度 | 说明 |
|------|------|
| **协议** | AgentArts `/invocations` (JSON-in/JSON-out) |
| **认证** | AgentArts IAM / API Key |
| **路由** | `/invocations`（AgentArts 平台调用） |
| **优势** | 零代码接飞书/微信，不需要公网回调 URL |
| **代价** | 需要 Windows PC 常驻运行 OfficeClaw，不能自定义飞书交互 |

---

## 3. 渠道对比

| | Web Chat | 飞书直连 | OfficeClaw |
|---|---|---|---|
| **自定义 UI** | ✅ 完全自由 | ❌ 飞书原生 | ❌ 飞书原生 |
| **SSE 流式** | ✅ 原生支持 | ⚠️ 需转飞书消息 | ❌ 不支持 |
| **OAuth 登录** | ✅ 完整流程 | ❌ 不适用 | ❌ 不适用 |
| **飞书卡片** | ❌ 不适用 | ✅ 支持 | ❌ 不支持 |
| **飞书高级交互** | ❌ 不适用 | ✅ 支持 | ❌ 不支持 |
| **微信接入** | ❌ 不适用 | ❌ 需要额外开发 | ✅ 内置 |
| **公网 IP 要求** | AgentArts 提供 | 需要回调 URL | 不需要 |
| **额外软件** | 浏览器即可 | 无 | Windows PC + OfficeClaw |
| **开发工作量** | 前端页面 + OAuth | 飞书 Bot 代码 | 仅 Agent 逻辑 |

---

## 4. 渠道选择指南

```mermaid
flowchart TD
    Start["选择前端渠道"] --> Q1{"需要 OAuth 登录<br/>和 SSE 流式？"}
    Q1 -->|"是"| WebChat["✅ Web Chat"]
    Q1 -->|"否"| Q2{"需要飞书卡片/<br/>高级交互？"}
    Q2 -->|"是"| FeishuDirect["✅ 飞书直连"]
    Q2 -->|"否"| Q3{"想零代码接飞书/<br/>微信？"}
    Q3 -->|"是"| OC["✅ OfficeClaw"]
    Q3 -->|"否"| WebChat2["✅ Web Chat<br/>（最通用）"]
```

---

## 5. 跨渠道 Memory 共享

同一用户从不同渠道发起对话，通过统一的 `user_id` 关联到同一 Memory Space：

```mermaid
flowchart LR
    FS["飞书<br/>feishu_user_id=ou_abc"] -->|"映射"| UID["user_id<br/>= user@example.com"]
    Web["Web Chat<br/>Google=user@example.com"] -->|"OAuth 身份"| UID
    OC["OfficeClaw<br/>飞书=ou_abc"] -->|"映射"| UID
    UID --> Memory["AgentArts Memory Space<br/>偏好 / 事实 / 对话历史"]
```

- **Web Chat**：OAuth 登录后直接获得 `user_id`（Google email）
- **飞书直连**：`feishu_user_id` → 查绑定表映射到 `user_id`
- **OfficeClaw**：同飞书直连，OfficeClaw 传递飞书用户身份

---

## 6. 部署拓扑

```mermaid
flowchart TB
    subgraph UserDevices["用户设备"]
        Browser["浏览器<br/>Web Chat"]
        FeishuApp["飞书客户端"]
    end

    subgraph ExternalPlatforms["外部平台"]
        FeishuCloud["飞书云服务"]
    end

    subgraph UserPC["用户 PC（仅 OfficeClaw）"]
        OC["OfficeClaw"]
    end

    subgraph AgentArts["AgentArts 平台 (cn-southwest-2)"]
        FastAPI["FastAPI 容器 :8080<br/>─────────────────<br/>/ping<br/>/invocations<br/>/feishu/webhook<br/>/auth/callback<br/>/chat/stream"]
    end

    Browser -->|"SSE + OAuth"| FastAPI
    FeishuApp --> FeishuCloud
    FeishuCloud -->|"Webhook 回调"| FastAPI
    FeishuCloud -->|"WebSocket"| OC
    OC -->|"AgentArts 调用"| FastAPI
```
