---
status: backlog
---

# Feature 4: Inbound Identity 认证

本 Phase 配置 AgentArts Identity 的 Inbound 认证（Microsoft Entra ID Custom JWT + API Key），使用户身份在 Request Header 中自动注入。这是 Web Chat 和所有 Outbound 工具的前置条件。

---

## 背景

飞书和 OfficeClaw 渠道自带用户身份（飞书 user_id）。但 Web Chat 和 User Federation 工具（GitHub/Microsoft 365）需要用户通过 OAuth 登录，Agent 拿到用户身份后才能以用户身份调外部 API。本 Phase 搭建 OAuth 基础设施。

## 范围

- Microsoft Entra ID 应用注册 + `agentarts_config.yaml` 配置（Custom JWT + API Key）
- `agentarts_config.yaml` Identity 配置（Custom JWT + API Key）
- `app/oauth.py` — OAuth 流程（code → id_token，Microsoft Entra ID）
- `GET /auth/callback` 路由
- AgentHandler 从 Request Header 读取 `X-AgentArts-User-Id`

## 不涉及

- SSE 流式对话（已在 Feature 1 实现）
- Web Chat 前端页面（Feature 1.1 负责）
- Outbound 工具（Feature 6-8）

## 任务拆解

### 4.1 Microsoft Entra ID 应用注册

- [ ] Azure Portal → Microsoft Entra ID → 应用注册
- [ ] 配置 Redirect URI
- [ ] 获取 client_id / client_secret（即 Application (client) ID + Secret）

### 4.2 Identity 配置

- [ ] 更新 `agentarts_config.yaml`
  - `authorizer_type: CUSTOM_JWT`
  - `discovery_url` → Microsoft OIDC（`https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration`）
  - `allowed_audience` / `allowed_clients` / `allowed_scopes`
  - `key_auth`（开发调试用 API Key）

### 4.3 OAuth 模块

- [ ] `app/oauth.py`
  - `exchange_oauth_code(code)` → 用 code 向 Microsoft 换 id_token
  - `verify_id_token(id_token)` → 用 Microsoft 公钥验证并提取用户信息

### 4.4 路由

- [ ] `GET /auth/callback?code=xxx`
  - 调 `exchange_oauth_code()` → 获取 id_token
  - 302 重定向 + Set-Cookie

### 4.5 AgentHandler 身份读取

- [ ] `handle()` 中 user_id 从以下来源获取：
  - AgentArts Runtime 注入的 `X-AgentArts-User-Id` header
  - 飞书/OfficeClaw 传入的 user_id
  - Cookie 中的 id_token（Web Chat，Feature 5 接入）

### 4.6 验证

- [ ] API Key 方式：`curl -H "X-AgentArts-User-Id: dev-user" /invocations` → 正常
- [ ] OAuth 流程：浏览器访问 `/auth/callback?code=xxx` → Cookie 正确设置
- [ ] 飞书渠道不受影响（飞书自带用户身份，不依赖 OAuth）

## 依赖

- Feature 1（Agent 骨架 + Web Chat）
- Feature 2（Memory）— user_id 需关联 Memory
- Feature 1.2（PostgreSQL）— 需要 `user_channel_mapping` + `oauth_tokens` 表

## 参考

- `architecture/overall_architecture.md` #3 认证流、#4 Identity 设计
- `architecture/frontend_architecture.md` #2.1 Web Chat
