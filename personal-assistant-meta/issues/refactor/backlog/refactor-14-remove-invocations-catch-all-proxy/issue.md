---
status: backlog
---

# Refactor 14: 移除 Cloudflare `/invocations/*` catch-all proxy

当前生产 API 只需要两个明确入口：

| Public path | Cloudflare Pages Function |
|-------------|---------------------------|
| `POST /invocations` | `functions/invocations.js` |
| `GET /auth/callback/m365-calendar` | `functions/auth/callback/m365-calendar.js` |

但代码里还存在：

```text
personal-assistant-client/functions/invocations/[[path]].js
```

它会匹配 `/invocations/{anything}`，例如 `/invocations/tools/example` 或
`/invocations/auth/oauth2/callback/m365-calendar`。这类 catch-all proxy 容易让人误以为
`/invocations/*` 是 production public API contract，与当前 API 映射文档希望表达的
“生产 API 必须逐条声明”冲突。

---

## 动机

`functions/invocations/[[path]].js` 现在混合了两种职责：

1. **Route file**：作为 Cloudflare Pages 的 `/invocations/*` catch-all route。
2. **Shared implementation**：存放 Web Chat proxy、AgentArts upstream URL 构造、
   header allowlist、Calendar callback context cookie 等共享 helper。

从 production API 设计看，`/invocations/*` 不应该作为默认公开入口；但从当前代码
实现看，不能直接删除 `[[path]].js`，因为 `functions/invocations.js` 和
`functions/auth/callback/m365-calendar.js` 仍复用其中的 helper。

本 refactor 的目标是先拆出共享 helper，再删除 catch-all route 文件，让文件结构与
production API contract 对齐。

---

## 目标

目标文件结构：

```text
personal-assistant-client/functions/
├── _shared/
│   ├── agentarts-proxy.js
│   └── callback-context.js
├── invocations.js
└── auth/callback/m365-calendar.js
```

目标 public routes：

| Public path | Cloudflare Function | 说明 |
|-------------|---------------------|------|
| `POST /invocations` | `functions/invocations.js` | Web Chat 对话入口 |
| `GET /auth/callback/m365-calendar` | `functions/auth/callback/m365-calendar.js` | Microsoft 365 Calendar OAuth callback |

删除后不再有 production Pages Function route：

```text
/invocations/{anything}
```

---

## 范围

### Client / Cloudflare Pages Functions

- [ ] 从 `functions/invocations/[[path]].js` 拆出 AgentArts proxy helper。
- [ ] 从 `functions/invocations/[[path]].js` 拆出 Calendar callback context cookie helper。
- [ ] 让 `functions/invocations.js` 直接持有 `POST /invocations` handler，并调用 shared helper。
- [ ] 让 `functions/auth/callback/m365-calendar.js` 继续处理
      `GET /auth/callback/m365-calendar`，并调用 shared helper。
- [ ] 删除 `functions/invocations/[[path]].js`。
- [ ] 更新 `functions/invocations.test.js`，移除 nested `/invocations/*` route tests，
      保留 Web Chat invocation 与 Calendar callback tests。

### Meta / Documentation

- [ ] 更新 `personal-assistant-meta/architecture/api.md`，移除
      `functions/invocations/[[path]].js` 相关 route matching 说明。
- [ ] 更新 `personal-assistant-meta/architecture/cloud-service/cloudflare/pages.md`，
      明确生产 Pages routes 只有 `/invocations` 和 `/auth/callback/m365-calendar`。
- [ ] 检查 `frontend_architecture.md`、`backend_architecture.md`、AgentArts docs 中是否仍把
      Cloudflare `/invocations/*` 描述为 production public route。

---

## 非目标

- 不改变 FastAPI container 内部 route，例如 `/invocations`、
  `/auth/oauth2/callback/m365-calendar`、`/invocations/playground`。
- 不改变 AgentArts Gateway `PREFIX_MATCH` 配置；Gateway 仍可支持 full Runtime path suffix。
- 不改变 Web Chat SSE 协议。
- 不改变 Microsoft 365 Calendar OAuth callback 业务行为。
- 不引入新的 BFF deployable。

---

## Implementation Plan 要求

正式实施前需要先确认：

1. `functions/invocations/[[path]].js` 没有被 production public API 依赖。
2. `/invocations/auth/oauth2/callback/m365-calendar` 只属于 legacy/local fallback 或测试路径，
   不是 production OAuth callback URL。
3. `functions/auth/callback/m365-calendar.js` 能通过 shared helper 构造当前 production
   Gateway full Runtime callback path：

   ```text
   /runtimes/personal-assistant/invocations/auth/oauth2/callback/m365-calendar
   ```

4. 按 GitNexus 规则，对将修改的 Function/helper symbol 执行 impact analysis。

---

## 验收标准

- [ ] `personal-assistant-client/functions/invocations/[[path]].js` 已删除。
- [ ] Cloudflare Pages production public route 只保留：
  - `POST /invocations`
  - `GET /auth/callback/m365-calendar`
- [ ] `/invocations/{anything}` 不再作为 Pages Function public route 被测试或文档化。
- [ ] `POST /invocations` 仍能转发到 AgentArts Gateway
      `/runtimes/personal-assistant/invocations`，并透传 SSE。
- [ ] `GET /auth/callback/m365-calendar` 仍能转发到 FastAPI
      `/auth/oauth2/callback/m365-calendar`，并恢复 callback context headers。
- [ ] `AGENTARTS_OAUTH_CALLBACK_URL` 仍仅作为 local full-flow direct override 使用。
- [ ] `api.md` 的 production API instances 表不再出现 `[[path]].js`。

---

## Tests

- [ ] Client: `npm run test`
- [ ] Client: `npm run build`
- [ ] 如修改 Pages Function routing，使用 Wrangler local preview 验证：
  - `POST /invocations`
  - `GET /auth/callback/m365-calendar`
  - `/invocations/anything` 返回预期 404 或不再命中 proxy

---

## Four-Question Gate

| Question | Answer | 论证 |
|----------|:------:|------|
| Is it best practice? | Yes | Public API 显式声明，shared code 放入 `_shared`，route file 不承担隐藏公共代理能力。 |
| Is it industry standard? | Yes | Cloudflare Pages Functions 常规做法是 file route 表达 public endpoint，共享逻辑放 shared module。 |
| Is it conventional? | Yes | 新成员看到 `functions/invocations.js` 和 `functions/auth/callback/...` 就能直接对应生产路径，不需要理解 catch-all route。 |
| Is it modern? | Yes | 显式 API contract + thin BFF route + shared helper module，比 catch-all proxy 更利于安全边界和可维护性。 |

四个 gate 均为 **Yes**。

---

## 参考

- [`personal-assistant-meta/architecture/api.md`](../../../../architecture/api.md)
- [`personal-assistant-meta/architecture/cloud-service/cloudflare/pages.md`](../../../../architecture/cloud-service/cloudflare/pages.md)
- [`personal-assistant-client/functions/invocations.js`](../../../../../personal-assistant-client/functions/invocations.js)
- [`personal-assistant-client/functions/invocations/[[path]].js`](../../../../../personal-assistant-client/functions/invocations/[[path]].js)
- [`personal-assistant-client/functions/auth/callback/m365-calendar.js`](../../../../../personal-assistant-client/functions/auth/callback/m365-calendar.js)
