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
    participant Microsoft as Microsoft Entra ID

    Note over User,Microsoft: === 登录 ===
    User->>Browser: 打开 /chat
    Browser->>FastAPI: GET /chat
    FastAPI-->>Browser: 重定向 Microsoft Entra ID
    Browser->>Microsoft: 授权
    Microsoft-->>Browser: code → /auth/callback
    Browser->>FastAPI: GET /auth/callback?code=xxx
    FastAPI-->>Browser: Set-Cookie + Chat UI

    Note over User,Microsoft: === 对话 ===
    User->>Browser: 输入消息
    Browser->>FastAPI: GET /chat/stream?q=...
    FastAPI-->>Browser: SSE: data: token...\n\n
    Browser-->>User: 逐字渲染
```

| 维度 | 说明 |
|------|------|
| **协议** | SSE (Server-Sent Events) 流式推送 |
| **认证** | Microsoft Entra ID → JWT Cookie。详见 [ADR-007](../ADR/ADR-007-identity-provider.md) |
| **路由** | `/chat/stream`, `/auth/callback` |
| **优势** | 完全自定义 UI/UX，不受平台限制 |
| **代价** | 需要自己开发前端页面 |
| **技术栈** | Vite + React + TypeScript + Tailwind CSS，assistant-ui AI Chat 组件库（含 `@assistant-ui/react-ai-sdk`）。详见 [ADR-013](../ADR/ADR-013-assistant-ui-chat-library.md) |

**OAuth 前后端职责分离**：token 交换必须在后端，因为 client_secret 不能暴露在前端浏览器中。

```
前端（浏览器）                    后端（FastAPI）
─────────────────                ─────────────────
● 发起登录跳转                    ● 接收 code
  (只需 client_id)               ● code + client_secret → access_token
● 携带 Cookie 发请求              ● token → 用户信息 (Graph /me)
● 无感知 token 细节               ● 设 Cookie，302 跳回 /chat
```

`/auth/callback` 路由实现约 30 行代码，不额外引入 BFF 或独立认证服务。

#### 2.1.1 Chainlit Playground（调试工具）

Web Chat（Vite + React）面向最终用户，需要工程化构建。在开发阶段，需要一个零构建的轻量调试界面直接与 Agent 交互，观察推理过程。

Chainlit 定位为**同容器唯一的对话 UI**，挂载在 `/invocations/playground`，覆盖开发调试、Agent 链路验证和运维访问需求：

```
FastAPI 容器 :8080
  ├── /invocations/playground  → Chainlit app（对话/调试 UI）
  ├── /invocations             → 同步对话 / SSE 流式对话（body stream:true）
  └── /ping                    → 健康检查
```

> Web Chat 前端（Vite + React）不再打包进容器，直接走 OBS 独立部署（见 §6.2 Phase 2）。

| 维度 | 说明 |
|------|------|
| **定位** | 开发调试 + 运维访问，同容器唯一 UI |
| **语言** | Python，与后端同一进程，零构建 |
| **LangChain 集成** | 原生 `@cl.on_chat_start` + LangChain callback，直接观察 Agent 推理步骤 |
| **流式** | 内置 `cl.Message.stream_token()` |
| **路径** | `/invocations/playground` — 避免与 `/chat`（未来 OAuth 登录后的用户入口）冲突 |
| **生命周期** | 与项目长期共存。开发阶段快速验证 Agent 链路，生产环境保留给运维调试 |

Chainlit 与 Web Chat 共享同一 FastAPI 进程内的 `agent_handler`，只是接入的 UI 层不同：Web Chat 走 SSE + assistant-ui（React，独立部署于 OBS），Playground 走 Chainlit 的 WebSocket 协议（Python 原生，同容器）。

#### 2.1.2 本地开发与网关模拟（Vite Proxy）

在生产环境中，**AgentArts Gateway（API 网关）** 扮演着身份认证与安全过滤的角色。它会拦截请求、校验 Token，并将解析后的用户 ID 通过特有 Header（`X-HW-AgentGateway-User-Id`）透传给后端容器。

为了在本地开发时实现**环境对齐（Environment Parity）**，同时规避浏览器的**同源策略（CORS）**限制，Web Chat 在本地开发阶段引入了 **Vite Proxy** 机制：

##### 1) 架构与数据流向

```mermaid
sequenceDiagram
    autonumber
    actor User as 开发者 (Browser)
    participant Proxy as Vite Proxy<br/>(:5173 / Node.js)
    participant Backend as FastAPI<br/>(:8080 / Uvicorn)

    User->>Proxy: POST /invocations<br/>[Header] Authorization: Bearer eyJ...
    Note over Proxy: 1. 识别代理规则<br/>2. 绕过浏览器 CORS<br/>3. 注入模拟身份 Header
    Proxy->>Backend: POST http://localhost:8080/invocations<br/>[Header] Authorization: Bearer eyJ...<br/>[Header] X-HW-AgentGateway-User-Id: dev-user
    Backend-->>Proxy: 返回流式数据 (SSE)
    Proxy-->>User: 透传流式数据 (SSE)
```

##### 2) 核心实现原理

- **同源伪装（避开 CORS）**：前端代码中所有发往后端的 API 请求（如 `/invocations`），都以相对路径形式发出，即请求 `http://localhost:5173/invocations`（与前端自身同源）。浏览器检测到请求同源，**不会触发 CORS 校验，亦不会发起 OPTIONS 预检请求**。
- **Node.js 侧转发与 Header 注入（Cosplay 华为云网关）**：运行在开发机上的 Vite 进程（Node.js 端）拦截到 `/invocations` 路径请求，在服务器端将其转发至真正的后端 `http://localhost:8080/invocations`。在转发之前，Vite 的 `vite.config.ts` 会利用 `proxyReq.setHeader` 钩子，强行在请求头中注入 `X-HW-AgentGateway-User-Id: dev-user`。
- **后端 Uvicorn**：无论是本地还是云端，直接读取 `X-HW-AgentGateway-User-Id` 头即可，无感知调用方是 Vite 还是真实的 AgentArts Gateway。

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
    Web["Web Chat<br/>Microsoft=user@example.com"] -->|"OAuth 身份"| UID
    OC["OfficeClaw<br/>飞书=ou_abc"] -->|"映射"| UID
    UID --> Memory["AgentArts Memory Space<br/>偏好 / 事实 / 对话历史"]
```

- **Web Chat**：OAuth 登录后直接获得 `user_id`（Microsoft account email）
- **飞书直连**：`feishu_user_id` → 查绑定表映射到 `user_id`
- **OfficeClaw**：同飞书直连，OfficeClaw 传递飞书用户身份

---

## 6. 部署拓扑

### 6.1 整体拓扑

#### 当前部署：Netlify + Edge Function 认证代理

当前 Web Chat 前端部署在 Netlify，通过 Edge Function 注入 AgentArts Gateway 认证 header 后转发 API 请求。详见 [ADR-014](../ADR/ADR-014-netlify-edge-function-auth-proxy.md)。

```
浏览器 ──→ Netlify (agentarts-personal-assistant.netlify.app)
              │  / → SPA 静态文件
              │  /invocations → Edge Function → 注入 Authorization → AgentArts Gateway
```

| 维度 | 说明 |
|------|------|
| **同源** | 浏览器只调 Netlify 域名，零跨域 |
| **认证** | Edge Function 服务端注入 `Authorization: Bearer`，API Key 不出现在浏览器 |
| **限制** | Netlify 域名不可绑自定义域名（需 ICP 备案），OAuth Cookie 不可用 |

#### 目标部署：OBS + CDN + 自定义域名

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

    subgraph HuaweiCloud["华为云 (cn-southwest-2)"]
        CDN["CDN<br/>chat.personal-assistant.cn"]
        OBS["OBS 静态托管<br/>Vite build 产物"]
        subgraph AgentArts["AgentArts 平台"]
            FastAPI["FastAPI 容器 :8080<br/>─────────────────<br/>/ping<br/>/invocations<br/>/invocations/playground（本地）<br/>/feishu/webhook<br/>/auth/callback"]
        end
    end

    Browser -->|"/ → 静态文件"| CDN
    CDN -->|"回源"| OBS
    Browser -->|"/invocations → SSE + OAuth"| CDN
    CDN -->|"回源"| FastAPI
    FeishuApp --> FeishuCloud
    FeishuCloud -->|"Webhook 回调"| FastAPI
    FeishuCloud -->|"WebSocket"| OC
    OC -->|"AgentArts 调用"| FastAPI
```

### 6.2 Web Chat 前端部署

Web Chat 前端独立部署于华为云 OBS，不打包进 FastAPI 容器。同容器的对话 UI 需求由 Chainlit Playground（`/invocations/playground`）覆盖。

#### 当前阶段：OBS 静态托管

前端 Vite build 产物上传到华为云 OBS bucket，直接通过 OBS 默认域名访问。此阶段存在跨域问题（OBS 域名 ≠ FastAPI 容器域名），适用于功能验证。

```
Web Chat 部署（OBS）
  浏览器 → https://obs-bucket.obs.cn-southwest-2.myhuaweicloud.com/
    ├── index.html, assets/*  → OBS 静态文件
    └── fetch /invocations    → 跨域请求 FastAPI 容器
```

| 维度 | 说明 |
|------|------|
| **跨域** | 存在，需 FastAPI 配置 CORS |
| **Cookie** | 跨域不可用，OAuth 需额外处理 |
| **适用** | 功能验证阶段 |

#### 目标阶段：OBS + CDN + 自定义域名

前端部署到 OBS，通过 CDN 回源并配置自定义域名（如 `chat.personal-assistant.cn`）。CDN 通过路径前缀分流请求，实现前后端同域零跨域：

```
https://chat.personal-assistant.cn/
  ├── /invocations → CDN 回源到 FastAPI 容器
  └── /*       → CDN 回源到 OBS bucket
```

| 维度 | 说明 |
|------|------|
| **跨域** | 无，前后端同 origin（同一域名） |
| **Cookie** | 天然共享，OAuth 流程零额外配置 |
| **国内速度** | CDN 全国加速，首屏秒开 |
| **扩容** | 静态资源 CDN 承载，后端容器只处理 API |
| **额外工作** | OBS bucket + CDN 配置 + 域名备案 + HTTPS 证书 |

#### 为什么不做跨域方案

OAuth Cookie 跨域（前端 OBS 默认域名 → 后端 AgentArts 域名）需要：
- FastAPI 配 CORS `Allow-Credentials: true`
- Cookie 设 `SameSite=None; Secure`
- 前端 SSE 请求带 `credentials: 'include'`

更关键的是安全网关的限制：
- **AgentArts Gateway 预检拦截**：华为云 AgentArts Gateway 在安全策略下，会拦截/校验所有进入网关的请求。由于浏览器的 CORS `OPTIONS` 预检请求（Preflight Request）默认不带 Token 或签名，**会导致 `OPTIONS` 预检直接被网关拦截并返回 401/403**，从而阻断真实的跨域 `POST`/`GET` 业务请求。

多一层配置多一个故障点，且在安全网关前难以维系。自定义域名方案**从架构层面彻底消除跨域问题**，而不是用配置修补，符合"简单够用"原则：
- 通过 CDN 路径分发后，前端页面与 API 接口完全处于**同源（Same-Origin）**下。
- 浏览器识别为同源请求，**绝对不会发起 `OPTIONS` 预检请求**，完美绕过网关对预检请求的校验拦截，直接发起带有认证信息的真实请求。

#### 为什么不用 GitHub Pages

- `github.io` 域名与 FastAPI 不同域，Cookie 跨域
- 国内无 CDN 节点，首次加载慢
- 无法绑 CDN 做路径分流（GitHub Pages 不支持回源到第三方 API）

#### 容器内 UI：Chainlit Playground

FastAPI 容器内仅保留 Chainlit Playground（`/invocations/playground`）作为对话 UI，覆盖以下场景：

| 用途 | 说明 |
|------|------|
| **开发调试** | 本地 `uvicorn` 启动后直接访问 `/invocations/playground`，零构建验证 Agent 链路 |
| **内部运维访问** | 直连容器地址可拿到 Chainlit 对话界面，调试时绕过 CDN |
| **深度健康检查** | 用聊天请求探测端到端链路（见下方） |

#### 聊天式健康检查

传统 `/health` 或 `/ping` 端点只验证"进程存活"，无法探测 AI Agent 核心链路。Chainlit Playground 路径可以作为**深度健康检查**的入口：

```mermaid
sequenceDiagram
    participant HC as 健康检查器（集群内）
    participant FastAPI as FastAPI 容器（内部地址）
    participant LLM as LLM API

    HC->>FastAPI: POST /invocations {"message":"ping","stream":true}
    FastAPI->>LLM: 请求推理
    LLM-->>FastAPI: SSE 流式响应
    FastAPI-->>HC: SSE 流式返回
    Note over HC: 验证：SSE 连接正常 + 有效文本返回
```

一次"聊天式 ping"覆盖的关键路径：

| 验证项 | 传统 `/health` | 聊天式 `POST /invocations` |
|--------|:---:|:---:|
| FastAPI 进程存活 | ✅ | ✅ |
| LLM API 连通性 | ❌ | ✅ |
| SSE 流式中间件正常 | ❌ | ✅ |
| Memory / Identity SDK 可用 | ❌ | ✅ |
| OAuth Cookie / JWT 验证链路 | ❌ | ✅（带 token） |

**实现建议**：在 AgentArts 或 K8s 的 readiness probe 中配置直连容器的聊天式检查（绕过 CDN），间隔可设长一些（如 5 分钟），因为 LLM 调用有成本。`/ping` 仍用于高频 liveness check（30 秒）。
