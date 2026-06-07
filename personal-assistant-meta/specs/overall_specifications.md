# Personal Assistant — 总体功能规格书

> 版本：v0.4 | 状态：Draft | 基于 AgentArts 平台

---

## 1. 项目概述

Personal Assistant 是一个对话式 AI 助手应用，用户通过自然语言对话管理邮件。系统具备跨 Session 的 Memory 能力，能够记住用户偏好和历史上下文，并在用户授权下以用户身份访问外部服务（如 Microsoft 365 邮件）。

### 1.1 核心价值

- **多渠道接入**：支持 Web Chat、飞书直连和 OfficeClaw 三种客户端接入方式，同一 Agent 后端同时服务多个入口
- **安全委托**：Agent 以用户委托身份调用外部服务，无需暴露个人凭证给 Agent 代码

### 1.2 目标用户

| 用户类型 | 典型场景 |
|----------|----------|
| 职场人士 | 通过对话处理邮件、查询收件箱摘要 |
| 开发者 | 通过对话管理邮件，辅助日常工作 |

---

## 2. 接入渠道

系统支持三种客户端接入方式，共享同一 FastAPI 后端和 Agent 处理逻辑：

```mermaid
flowchart LR
   subgraph Clients["🖥️ 客户端（消息通道）"]
       direction LR
       WebChat["Web Chat<br/>浏览器"]
       Feishu["飞书直连<br/>自定义 Bot"]
       OC["OfficeClaw<br/>桌面客户端"]
   end

   subgraph Backend["☁️ FastAPI 后端 — AgentArts 容器 :8080"]
       direction LR
       R_Stream["/chat/stream<br/>SSE 流式"]
       R_Auth["/auth/callback<br/>OAuth 回调"]
       R_FS["/feishu/webhook<br/>飞书事件"]
       R_Invoke["/invocations<br/>Agent 对话"]
       Handler["Agent 处理逻辑<br/>（三端共享）"]
   end

   WebChat --> R_Stream
   WebChat --> R_Auth
   Feishu --> R_FS
   OC --> R_Invoke
   R_Stream --> Handler
   R_Auth --> Handler
   R_FS --> Handler
   R_Invoke --> Handler
   Handler --> Memory["AgentArts Memory"]
   Handler --> Sandbox["AgentArts Sandbox"]
```

| 渠道 | 接入方式 | 说明 | 适用场景 |
|------|----------|------|----------|
| **Web Chat** | 浏览器直连 `/chat/stream` | 独立 Web 聊天界面，支持 OAuth 登录和 SSE 流式响应，完全自定义 UI/UX | 个人桌面使用、对外 Demo |
| **飞书直连** | 飞书事件回调 `/feishu/webhook` | 自行创建飞书 Bot，处理事件回调，完全自主可控，支持飞书卡片等高级交互 | 企业内部推广、移动端触达、高级飞书交互 |
| **OfficeClaw** | AgentArts 转发 `/invocations` | 通过 OfficeClaw 桌面客户端桥接飞书/微信，无需写飞书代码，不需要公网回调 URL | 快速接入飞书/微信，不想维护飞书 Bot 代码 |

三种渠道共享同一个 Agent 处理逻辑和 Memory 空间，用户无论从哪个入口发起对话，Assistant 都能加载其偏好和历史上下文。

---

## 3. 功能模块

### 3.1 邮件处理

- **收件箱摘要**：按优先级汇总未读邮件，提取关键信息（发件人、主题、紧急程度）
- **草拟回复**：根据上下文草拟邮件回复内容，用户确认后发送
- **邮件发送**：通过对话撰写并发送邮件，支持指定收件人、抄送和附件
- **敏感操作拦截**：发送邮件等写操作需用户二次确认（Guard 机制）

---

## 4. 认证与授权

### 4.1 用户登录（Inbound）

用户通过以下方式之一登录后访问 Agent：

| 认证方式 | 说明 | 适用场景 |
|----------|------|----------|
| **OAuth 2.0 (Custom JWT)** | 通过 Microsoft Entra ID、Okta、Auth0 等 OIDC IdP 登录 | 生产环境，面向终端用户 |
| **IAM** | 通过华为云 IAM 账号登录 | 华为云内部用户 |
| **API Key** | 使用预配置的 API Key 访问 | 开发调试、机器对机器调用 |

### 4.2 服务委托（Outbound）

用户可授权 Agent 以自身身份访问外部服务：

| 委托模式 | 说明 | 典型场景 |
|----------|------|----------|
| **User Federation** | Agent 以用户身份调用外部 API | 查询 Outlook 邮件、发送邮件 |

用户凭证始终由 Identity Service 管理，Agent 代码不会接触原始凭证（如密码或长期 Token）。

### 4.3 认证矩阵

| 用户身份 | Inbound 方式 | Outbound 目标 | Outbound 方式 | Auth Flow |
|----------|-------------|---------------|---------------|-----------|
| Microsoft 用户 | JWT (Microsoft Entra ID) | Outlook Mail | OAuth 2.0 | USER_FEDERATION |
| 开发者 | API Key | _(全部)_ | _(开发调试)_ | — |

---

## 5. 对话交互

### 5.1 对话流程

```mermaid
stateDiagram-v2
    [*] --> ReceiveMessage: 用户发送消息
    ReceiveMessage --> LoadMemory: 加载 Memory 上下文
    LoadMemory --> IntentRouter: 意图路由

    IntentRouter --> Chat: 普通对话
    IntentRouter --> EmailAction: 邮件操作请求

    Chat --> SaveMemory
    EmailAction --> GuardCheck: 敏感操作确认
    GuardCheck --> CallExternal: 调用邮件 API

    CallExternal --> SaveMemory
    SaveMemory --> StreamResponse: 流式返回结果
    StreamResponse --> [*]
```

### 5.2 典型对话示例

**场景一：收件箱摘要**

```
用户: 帮我看看最近有什么重要邮件
Agent: 你最近有 3 封未读邮件：
      1. 张三 — "项目进度同步"（标记为重要）
      2. HR — "年中绩效评估通知"
      3. 李四 — "周五午餐"
      需要我帮你查看哪一封的详细内容？
```

**场景二：草拟回复**

```
用户: 帮张三回一封邮件，告诉他项目 demo 安排在 7 月 10 号下午
Agent: 草拟如下：

      收件人：张三
      主题：Re: 项目进度同步
      正文：Hi 张三，项目 demo 安排在 7 月 10 日下午，具体时间我再确认后同步你。
      
      需要修改或直接发送吗？
```

---

## 6. LLM Provider 管理

系统支持配置多个 LLM Provider，通过 `config.yaml` 声明式管理。默认使用华为云 MaaS，可按需切换到 DeepSeek 官方或其他 OpenAI-compatible provider。

### 6.1 Provider 切换场景

| 场景 | 推荐 Provider | 原因 |
|------|--------------|------|
| 生产环境 | MaaS | 内网直连、数据合规、华为云统一账单 |
| 无 VPN 开发 | DeepSeek 官方 | 公网可达，不受华为内网限制 |
| 低成本长尾任务 | DeepSeek 官方 | 按量付费，无平台溢价 |
| 模型能力对比 | 任一 | 切换 `llm.default` 即可 A/B 测试 |

### 6.2 配置方式

详见 [ADR-011](../architecture/ADR/ADR-011-multi-llm-provider.md) 和 [LLM Provider 配置](../architecture/overall_architecture.md#6-llm-provider-配置)。

```yaml
# config.yaml
llm:
  default: maas
  providers:
    maas:
      base_url: https://api.modelarts-maas.com/openai/v1
      api_key_env: MAAS_API_KEY
      model: deepseek-v4-pro
    deepseek:
      base_url: https://api.deepseek.com
      api_key_env: DEEPSEEK_API_KEY
      model: deepseek-chat
```

---

## 7. 核心验证点

| 验证项 | 说明 |
|--------|------|
| **Inbound Auth** | 用户通过 OAuth 2.0 / API Key 认证后访问 Agent |
| **Outbound Auth (User Federation)** | Agent 以用户委托身份调用 Microsoft 365 邮件 API |
| **Chat Loop** | 多轮对话 + 工具调用 + 流式响应 |
| **Memory** | 跨 Session 持久化用户偏好和上下文 |
| **Guard** | 发送邮件等写操作需用户确认 |

---

## 8. 开发计划

| Phase | 内容 | 验证点 |
|-------|------|--------|
| **Phase 1** | 搭建 Agent 骨架：LangGraph chat loop + 本地开发环境 | 本地对话通 |
| **Phase 2** | 集成 Memory：创建 Memory Space，保存/检索记忆 | 跨 Session 记忆 |
| **Phase 3** | 配置 Inbound Identity：JWT + API Key 认证 | 用户登录后访问 |
| **Phase 4** | 实现 Outbound OAuth2 (User Federation)：邮件 Tool | Agent 代用户查邮件 |
| **Phase 5** | Web Chat 前端：Vite + React + SSE 流式对话 + OAuth 登录 | 浏览器完整对话体验 |
| **Phase 6** | 部署上线 + 全链路可观测 | 生产可用 |
