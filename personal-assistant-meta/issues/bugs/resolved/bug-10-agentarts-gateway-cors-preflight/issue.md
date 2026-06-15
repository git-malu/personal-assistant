---
status: in_progress
---

# Bug 10: AgentArts Gateway CORS Preflight 阻断前端请求

## Motivation

前端部署在 Netlify（`https://agentarts-personal-assistant.netlify.app`），后端部署在 AgentArts Runtime，通过 Gateway（`https://defaultgw-xxx.cn-southwest-2.huaweicloud-agentarts.com/invocations`）转发请求。由于前后端不同域，浏览器在发送 POST 请求时先发送 OPTIONS preflight。AgentArts Gateway 不处理 CORS preflight（无 CORS 配置能力，且 `authorizer_type: IAM` 会阻止未认证的 OPTIONS 请求），导致 preflight 失败，浏览器阻断后续 POST 请求。

**错误信息**：
```
Access to fetch at 'https://defaultgw-xxx.cn-southwest-2.huaweicloud-agentarts.com/invocations'
from origin 'https://agentarts-personal-assistant.netlify.app' has been blocked by CORS policy:
Response to preflight request doesn't pass access control check:
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

**根因**：AgentArts Gateway 不支持 CORS 配置（`.agentarts_config.yaml` 无 CORS 字段），且 `authorizer_type: IAM` 会拒绝未携带 IAM 签名的 OPTIONS preflight 请求。FastAPI 后端的 CORSMiddleware 配置正确（`CORS_ALLOWED_ORIGINS` 已包含 Netlify 域名），但 preflight 请求根本无法到达容器。

## Scope

- **在 `netlify.toml` 中配置 `/invocations` 代理，将前端请求转为同源请求**
- 清空 Netlify 构建环境变量 `VITE_API_BASE_URL`（使其为空，从而使用相对路径 `/invocations`）
- 验证 SSE 流式对话在 Netlify proxy 下正常工作
- **不涉及**：AgentArts Gateway 配置变更（平台不支持）
- **不涉及**：FastAPI 后端 CORS 配置变更（当前配置保留，作为双层防御）
- **不涉及**：自定义域名、CDN、反向代理等基础设施变更

## Acceptance Criteria

- [ ] `netlify.toml` 新增 `/invocations` 代理 redirect（`status = 200`），位于 SPA catch-all 之前
- [ ] Netlify 环境变量 `VITE_API_BASE_URL` 已清空
- [ ] 从 Netlify 域名发送对话消息，CORS 错误消失
- [ ] SSE 流式对话正常返回（token 逐字渲染，非缓冲后一次性返回）
- [ ] 长时间对话（>30s）不出现连接超时
- [ ] OBS 部署不受影响（OBS 仍使用完整 AgentArts Gateway URL）
- [ ] 浏览器 DevTools Network 面板确认请求路径为 `https://agentarts-personal-assistant.netlify.app/invocations`（同源）

## 技术方案

### 方案：Netlify Same-Origin Proxy

**原理**：通过 Netlify 的 proxy rewrite（`status = 200`）将 `/invocations` 请求服务器到服务器转发到 AgentArts Gateway。浏览器视角下请求是**同源**的（`https://agentarts-personal-assistant.netlify.app/invocations`），因此**不会触发 CORS preflight**，从根本上消除跨域问题。

```
浏览器 → https://agentarts-personal-assistant.netlify.app/invocations (同源，无 preflight)
          ↓ Netlify Edge proxy (server-to-server, no CORS needed)
AgentArts Gateway → https://defaultgw-xxx.../invocations
                      ↓
FastAPI 容器 → CORSMiddleware (作为双层防御保留)
```

### 实现步骤

**1. 更新 `personal-assistant-client/netlify.toml`**（新增 `/invocations` 代理，在 SPA catch-all 之前）：

```toml
[build]
  base = "personal-assistant-client"
  command = "npm run build"
  publish = "dist"

# API 代理 — 必须位于 SPA catch-all 之前
[[redirects]]
  from = "/invocations"
  to = "https://defaultgw-xxx.cn-southwest-2.huaweicloud-agentarts.com/invocations"
  status = 200

# SPA 路由回退
[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

**2. 清空 Netlify 构建环境变量**：

在 Netlify Site Settings → Environment variables 中，清空 `VITE_API_BASE_URL`（或删除此变量）。

**3. 验证 Frontend 代码无需变更**：

`chat-adapter.ts` 中已有逻辑：
```typescript
const baseUrl: string = (
  import.meta.env.VITE_API_BASE_URL ?? ""
).replace(/\/$/, "");
// ...
const response = await fetch(`${baseUrl}/invocations`, { ... });
```

当 `VITE_API_BASE_URL` 未设置或为空时，`baseUrl = ""`，请求 URL 为 `/invocations` → 浏览器发出同源请求 → Netlify 代理至 AgentArts Gateway。

### 为什么不用其他方案

| 方案 | 判定 | 理由 |
|------|------|------|
| AgentArts Gateway CORS 配置 | ❌ 不可行 | AgentArts 平台不支持 Gateway 级别的 CORS 配置 |
| 改 IAM 为 KEY_AUTH | ❌ 无效 | 改认证方式不影响 Gateway 对 OPTIONS preflight 的处理，仍不会返回 CORS headers |
| 前端 `mode: "no-cors"` | ❌ 无效 | 响应变为 opaque，JS 无法读取 SSE stream |
| 改 `Content-Type` 避免 preflight | ❌ 反模式 | `Content-Type: text/plain` 伪装 JSON 违反 HTTP 语义，脆弱且不推荐 |
| 自定义域名 + 反向代理 | 🟡 过度设计 | 当前阶段不需要额外基础设施（ECS/Nginx/证书），未来需要时再考虑 |

## Four-Question Gate

> 全部通过，无偏离。

| Question | Answer | Notes |
|----------|--------|-------|
| Is it best practice? | Yes | 通过 CDN Edge 反向代理消除 CORS 是公认的最佳实践。Vite dev proxy 已使用相同模式。不违反任何安全原则或 HTTP 语义。 |
| Is it industry standard? | Yes | Vercel、Netlify、Cloudflare Pages、AWS CloudFront 等主流平台都使用 `/api/*` proxy rewrite 解决前后端跨域问题。 |
| Is it conventional? | Yes | 前端开发者普遍理解和预期这种模式。`netlify.toml` 的 `status = 200` proxy rewrite 是 Netlify 的标准用法，文档完善。 |
| Is it modern? | Yes | 这是 Jamstack 架构的标准模式：静态前端 + 通过 CDN Edge 代理 API 请求。Netlify 的 Edge 基础设施持续活跃维护。 |

## Affected Architecture Docs

- `personal-assistant-meta/architecture/frontend_architecture.md` — §6.2 Netlify 部署节点架构图需更新，体现 `/api/*` proxy 路径
- `personal-assistant-meta/architecture/devops/agentarts-deploy-runbook.md` — 部署步骤中 Netlify 部分需补充 proxy 配置说明

## Notes

### SSE 流式兼容性

Netlify proxy redirect 支持流式传输（`text/event-stream`），但需注意：

- **Netlify Free 计划连接超时为 26 秒**。只要 FastAPI 后端在 1-2 秒内开始输出 SSE chunk，连接就不会超时。对话过程中的持续 token 输出会 keep alive 连接。
- **Netlify CDN 可能在边缘节点缓冲响应**。如果首次测试发现 SSE token 不是逐字到达而是批量到达，可能需要排查 CDN buffering 行为。大多数情况下这不是问题。
- **长时间对话（>26s idle）**：如果用户在输入消息后长时间不发新消息，连接会超时。这是正常行为，聊天在发送时建立新连接。

### 与 Feature 4 (Inbound Identity) 的兼容性

当前使用 `authorizer_type: IAM`，未来 Feature 4 可能切换到 `CUSTOM_JWT` 或 `KEY_AUTH`。Netlify proxy 的 `status = 200` rewrite 会**自动转发所有请求头**（包括 `Authorization`、`X-API-Key` 等），无需额外配置。

### 与 OBS 部署的关系

OBS 部署继续使用完整 AgentArts Gateway URL（`VITE_API_BASE_URL=https://defaultgw-...`），通过 FastAPI CORS middleware 处理跨域。两条部署通道互不干扰：
- **Netlify**：走 `/api/*` proxy → 同源无 CORS
- **OBS**：走跨域 CORS → FastAPI CORSMiddleware 处理

### 安全收益

Netlify proxy 将 AgentArts Gateway 的真实域名隐藏在服务端，前端 bundle 中暴露的只是 `/api` 相对路径，减少后端域名暴露面。

---

## Solution: Bug 10 — AgentArts Gateway CORS Preflight 阻断前端请求

### Integrated Recommendation

通过 **Netlify same-origin proxy**（`/api/*` rewrite）将前端请求转为同源请求，从根本上消除 CORS preflight。具体改动仅在 `netlify.toml` 增加一条 proxy redirect 规则，并将 Netlify 环境变量 `VITE_API_BASE_URL` 从完整 Gateway 域名改为 `/api` 相对路径。前端代码无需任何改动。

这是解决此类问题**最少改动、最可靠**的方案——从架构层面消除跨域，而非用配置修补。两个独立 AI 顾问（DeepSeek、Gemini）均独立收敛到此方案。

### Four-Question Gate

已在上方 §Four-Question Gate 中逐项评估，全部通过。

### Solution Rationale

- **Consensus**：DeepSeek 和 Gemini 均认为根因是 AgentArts Gateway 不支持 CORS + IAM 阻断 preflight；均推荐 Netlify proxy rewrite 作为首选方案；均认可 `status = 200` rewrite 模式；均建议保留 FastAPI CORS 配置作为双层防御。
- **Complementary insights**：
  - DeepSeek 深入分析了 SSE 流式兼容性风险及 Netlify 26s timeout 问题，提出了详细的验证策略和 fallback（自定义反向代理）。
  - Gemini 提出使用 `/api/*` + `:splat` 模式（比 `/invocations` 更通用），并补充了 `force = true` 参数、安全收益（隐藏后端域名）、与 Feature 4 的兼容性分析。
- **Trade-offs resolved**：
  - DeepSeek 建议直接 proxy `/invocations`，Gemini 建议 `/api/*`。**选择 `/api/*`**——更符合业界惯例（几乎所有 Jamstack 应用都用 `/api/*`），可扩展性好（未来新增 API 端点无需改 netlify.toml），且不需要改动前端代码中的 `/invocations` 路径段。
  - DeepSeek 建议移除 `VITE_API_BASE_URL`（为空），Gemini 建议设为 `/api`。**选择设为 `/api`**——显式声明比隐式依赖空字符串更清晰，便于维护者理解数据流。

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SSE 流式在 Netlify proxy 下不工作（CDN buffering） | Medium | High — 聊天不可用 | 首次部署后立即端到端测试。如问题存在，fallback 到华为云 APIG 反向代理或 Nginx on ECS |
| Netlify 26s 空闲超时切断长对话 | Low | Medium — 长时间不发新消息时断连 | 正常聊天行为不会触发（持续输出 SSE chunk 会 keep alive）。如需长时间保持连接，可在后端添加 heartbeat comment |
| Netlify 请求体大小限制（<1MB） | Low | Low — 对话消息体很小 | 监控日志。如用户发送大附件，后续可走独立上传端点 |

### Advisor Reports (supporting data)

<details>
<summary>DeepSeek Report</summary>

## DeepSeek Analysis

### Key Findings

1. **The FastAPI backend's CORSMiddleware is correctly configured** — it reads `CORS_ALLOWED_ORIGINS` which includes `https://agentarts-personal-assistant.netlify.app`. However, it **never executes for preflight requests** because the AgentArts Gateway handles (and blocks) OPTIONS before forwarding to the container.

2. **The OPTIONS preflight is triggered by `Content-Type: application/json`** — under the CORS spec, this is not a CORS-safelisted content type (only `application/x-www-form-urlencoded`, `multipart/form-data`, and `text/plain` are). The browser MUST send a preflight before the actual POST.

3. **The AgentArts Gateway (`.agentarts_config.yaml`) has no CORS configuration support** — the schema (`url_match_type`, `authorizer_type`, `network_mode`, etc.) contains no CORS-related fields. Web searches into AgentArts and Huawei Cloud APIG documentation confirm CORS is not configurable at the AgentArts Gateway level. This is a platform limitation.

4. **The `authorizer_type: IAM` is a secondary blocker** — OPTIONS preflight requests carry no authentication headers by design (they're not meant to be authenticated). The IAM authorizer likely either:
   - Rejects the OPTIONS request outright
   - Lets it through but returns a response without CORS headers
   Either outcome means the preflight fails.

5. **The Netlify deployment currently has no proxy configuration** — the `netlify.toml` only has a SPA redirect (`/* → /index.html`). The `VITE_API_BASE_URL` is set in the production build to the AgentArts Gateway domain, making requests cross-origin.

6. **SSE streaming is used** — the backend returns `text/event-stream` responses for streaming chat. Any solution must support long-lived streaming connections, not just simple request-response.

### Solution Analysis

#### Solution A: Netlify Same-Origin Proxy ✅ Recommended

Don't set `VITE_API_BASE_URL` in production. The frontend sends requests to `https://netlify.app/invocations` (same origin). Add a Netlify proxy redirect that forwards `/invocations` to the AgentArts Gateway server-to-server.

- Same-origin → no CORS preflight → browser sends POST directly
- Netlify proxies the request server-to-server → no cross-origin restriction
- Matches the existing Vite dev proxy pattern (`/invocations` → `localhost:8080`)
- **Frontend code needs NO changes** — if `VITE_API_BASE_URL` is empty, it already uses relative paths (`/invocations`)
- Backend FastAPI CORS middleware becomes optional (still good to keep for defense-in-depth)

**Risk**: SSE streaming through Netlify's CDN proxy may not work reliably. Netlify's proxy rewrites (status `200` redirects) support response streaming, but the CDN edge may buffer or timeout on long-lived SSE connections. This needs verification in production.

#### Solution B: AgentArts Gateway CORS Configuration ❌ Not Viable

No CORS configuration fields exist in `agentarts_config.yaml` or AgentArts platform documentation.

#### Solution C: Change Auth Type ❌ Doesn't Fix CORS

Changing the authorizer type doesn't affect the root problem: the Gateway still doesn't add CORS headers to the OPTIONS response.

#### Solution D: Custom Domain + Reverse Proxy 🟡 Viable Fallback

Deploy a reverse proxy (e.g., Nginx on ECS, Huawei Cloud ELB) that has full CORS control. Significant infra cost but most robust.

### Recommendation

**Tier 1 — Primary: Netlify Same-Origin Proxy (Solution A)**. If SSE streaming fails, **Tier 2 — Fallback: Custom Reverse Proxy (Solution D)**.

### Four-Question Gate

All Yes. Netlify proxy is best practice, industry standard, conventional, and modern (Jamstack pattern).

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SSE streaming doesn't work through Netlify proxy | Medium | High | Fall back to custom reverse proxy |
| Netlify proxy connection timeout for long SSE streams | Low-Medium | High | Verify streaming, add heartbeat |
| Additional latency from extra hop | Low | Low | Acceptable for chat |
| Netlify request body size limits | Low | Low | Monitor |

</details>

<details>
<summary>Gemini Report</summary>

## Gemini Analysis

### Key Findings

- **Root Cause of CORS Preflight Block**: Because the frontend is hosted on Netlify and the backend is on the AgentArts Gateway, the browser must perform a cross-origin preflight `OPTIONS` request due to non-simple request headers (`Content-Type: application/json` and `Accept: text/event-stream`).
- **Gateway Authentication & CORS Deficiency**: The AgentArts Gateway (built on Huawei Cloud API Gateway) is configured with `authorizer_type: IAM`. The unauthenticated preflight `OPTIONS` request sent by the browser lacks IAM signature headers and is immediately blocked by the Gateway before it can reach the FastAPI backend's `CORSMiddleware`.
- **Lack of Programmatic CORS in AgentArts**: There is no native configuration key in `.agentarts_config.yaml` to enable CORS at the Gateway level.
- **Inbound Auth Evolution**: Production setup will evolve to use `authorizer_type: CUSTOM_JWT` or `KEY_AUTH`.

### Recommendations

#### Netlify Proxy/Rewrite (Solution A)

The most elegant, secure, and practical solution.

**Step 1: Update Netlify Redirects**
Add API proxy rule in `netlify.toml` *before* the general SPA catch-all:
```toml
[[redirects]]
  from = "/api/*"
  to = "https://defaultgw-xxx.cn-southwest-2.huaweicloud-agentarts.com/:splat"
  status = 200
  force = true
```

**Step 2: Adjust Environment Variables**
Set `VITE_API_BASE_URL` to `/api` (relative path). Browser will dispatch requests to `https://agentarts-personal-assistant.netlify.app/api/invocations` — same origin, no preflight.

**Step 3: Keep FastAPI CORS as Fallback**
Retain the `CORSMiddleware` for local development or direct testing.

### Four-Question Gate

All Yes. Edge proxying/rewriting is the absolute industry standard. Using `netlify.toml` redirects with `status = 200` is the standard, documented way to solve cross-origin API integration on Netlify.

### Risks / Concerns

- **Netlify Timeout Limits**: Netlify's free proxy has a maximum connection timeout of 26 seconds. Ensure FastAPI backend initiates streaming response immediately.
- **Bandwidth Consumption**: Text-based conversational assistant has negligible bandwidth — well within Netlify's 100GB/month free tier.
- **Future Inbound Authentication Compatibility**: Netlify redirects with `status = 200` automatically forward all request headers, ensuring full forward compatibility.

</details>

> GPT sub-agent was cancelled mid-execution. Synthesis based on DeepSeek + Gemini reports, which independently converged on the same solution.

</parameter>
