# Bug 9: AgentArts Gateway 对 `/invocations/stream` 返回 404 — CORS 头缺失

## Motivation

部署前端（Netlify: `https://agentarts-personal-assistant.netlify.app`）和后端（AgentArts Runtime, Gateway `https://defaultgw-xxx.cn-southwest-2.huaweicloud-agentarts.com`）后，浏览器发送 `GET /invocations/stream?q=hello%3F` 时返回 **404 Not Found** 且 **无 CORS 响应头**：

```
Access to fetch at 'https://defaultgw-xxx.cn-southwest-2.huaweicloud-agentarts.com/invocations/stream?q=hello%3F'
from origin 'https://agentarts-personal-assistant.netlify.app' has been blocked by CORS policy:
No 'Access-Control-Allow-Origin' header is present on the requested resource.

GET ... net::ERR_FAILED 404 (Not Found)
```

**直接原因**：AgentArts Gateway 对 `/invocations/stream` 返回 404，请求未到达 FastAPI 容器，因此 `CORSMiddleware` 从未执行，`Access-Control-Allow-Origin` 响应头未被注入。

**深层原因**：部署的 Runtime 配置中 `invoke_config.url_match_type` 可能仍为 `ACCURATE_MATCH`（默认值，仅转发精确路径 `/invocations`），而非本地 `.agentarts_config.yaml` 中声明的 `PREFIX_MATCH`（转发 `/invocations/*` 所有子路径）。`agentarts launch` 在更新已存在 Runtime 的配置时存在**已知缺陷**——`refactor-4` plan.md 第 407 行明确记录了 "PREFIX_MATCH 配置不生效" 的风险。

> **注**：本 bug 与 `bug-8`（`VITE_API_BASE_URL` 占位符未替换）是独立的。Bug-8 已正确设置环境变量，前端请求的目标 URL 是真实的 Runtime 域名。失败发生在后端基础设施层（Gateway 路由），而非前端构建层。

## Scope

### 诊断（必须，修复前执行）

- [x] ~~`agentarts runtime describe`~~ — **此命令不存在**。`agentarts runtime` 仅支持 `invoke`、`exec-command`、`upload-files`、`download-files`、`start-session`、`stop-session`。Runtime 配置需通过**华为云 AgentArts 控制台 → Runtime 详情页**查看。
- [x] **诊断已执行**（2026-06-10），结果如下：
  - `curl -i /invocations/stream?q=hello` → `404 {"code":404,"message":"No matching policy found"}` ← **确认**
  - `agentarts invoke '{"message":"hello"}'`（精确路径 `/invocations`）→ ✅ 200 正常返回 ← **确认**
  - `agentarts invoke --custom-path invocations/stream '{"message":"hello"}'` → ❌ `No matching policy found` ← **确认**
  - **结论**：部署的 Runtime 中 `url_match_type` 为 `ACCURATE_MATCH`（默认值），精确路径 `/invocations` 正常，子路径 `/invocations/stream` 被 Gateway 拒绝
- [ ] 在 AgentArts 控制台确认 `invoke_config.url_match_type` 实际值、Runtime 运行状态、`CORS_ALLOWED_ORIGINS` 环境变量

### 修复（根据诊断结果选择对应场景）

- [ ] **场景 A（最可能）：`url_match_type` 未生效** — 重新部署 Runtime 以强制更新 Gateway 路由配置：
  ```bash
  cd personal-assistant-service
  # 若 Runtime 存在但配置不一致，可能需要先停止旧实例再重新 launch
  agentarts launch
  ```
- [ ] **场景 B：Runtime 容器崩溃** — 根据日志修复启动问题后重建部署：
  - ARM64 架构：确认 `docker buildx --platform linux/arm64`
  - OCI media types（Docker 27+）：`export BUILDKIT_USE_OCI_MEDIA_TYPES=0`
  - 环境变量缺失：确认 `MODEL_API_KEY`、`DEEPSEEK_API_KEY` 等已配置
- [ ] **场景 C：CORS 环境变量未应用** — 确认 Runtime 环境变量包含正确的 `CORS_ALLOWED_ORIGINS`，重新 launch

### 预防措施

- [ ] 更新 `personal-assistant-meta/architecture/devops/agentarts-deploy-runbook.md` §5（后端冒烟验证）：
  - 在 `agentarts launch` 后增加 Gateway 路由验证步骤：`curl -I /invocations/stream?q=test`，若返回 404 则立即阻断后续部署
  - 增加 `agentarts runtime describe` 验证步骤，确认 `url_match_type` 与实际配置一致
- [ ] （可选）在 `personal-assistant-meta/issues/refactor/resolved/refactor-4-consolidate-invocations-routes/plan.md` 的已知风险记录后追加本 bug 引用，作为 "PREFIX_MATCH 配置不生效" 的实际发生案例

### 不涉及

- Bug-8 的任何变更（该 bug 已独立处理前端 `VITE_API_BASE_URL` 占位符问题）
- 前端代码或构建流程的变更
- 硬编码 Runtime 域名
- Netlify proxy rewrites（不适用于 SSE 流式场景）

## Acceptance Criteria

1. **Gateway 路由正常**：`curl -I $RUNTIME_DOMAIN/invocations/stream?q=test` 返回 `200`（非 `404`）
2. **CORS 头正确注入**：带 `Origin: https://agentarts-personal-assistant.netlify.app` 的请求返回 `Access-Control-Allow-Origin: https://agentarts-personal-assistant.netlify.app`
3. **前端聊天功能恢复**：从 `https://agentarts-personal-assistant.netlify.app/` 发送消息 → SSE 流式回复正常，浏览器 Console 无 CORS 错误
4. **部署 runbook 已更新**：§5 包含 Gateway 路由验证步骤
5. **诊断步骤文档化**：本 issue 中记录的诊断命令可直接用于未来排查

## Four-Question Gate

> Must pass all four. If any answer is No, document the deviation and trade-off analysis.

| Question | Answer | Notes (if No, explain deviation & trade-off) |
|----------|--------|------|
| Is it best practice? | Yes | 从基础设施边界向内逐层诊断（Gateway → Runtime → Container → FastAPI → CORS），区分路由层错误与应用层错误，是云网络故障排除的核心最佳实践。 |
| Is it industry standard? | Yes | 所有主流云平台（AWS ECS、GCP Cloud Run、Azure Container Apps、Kubernetes）都支持 `describe`/`get` 命令检查已部署资源配置后进行增量修复。API Gateway 作为反向代理需明确路由规则以转发嵌套路径，是微服务架构的行业标准模式。 |
| Is it conventional? | Yes | 浏览器 CORS 错误伴随 404/5xx 通常是路由失败的**症状**而非根因——这是 Web 调试的常规认知。通过 `curl`/CLI 绕过浏览器验证真实 HTTP 状态码，再修复 Gateway 路由配置，是标准排障流程。 |
| Is it modern? | Yes | 声明式 Runtime 配置（`.agentarts_config.yaml`）+ 环境变量驱动的 CORS 白名单 + 部署后冒烟验证，代表了现代 GitOps/声明式基础设施实践。 |

## Affected Architecture Docs

- `personal-assistant-meta/architecture/devops/agentarts-deploy-runbook.md` — §5 新增 Gateway 路由验证步骤
- `personal-assistant-meta/issues/refactor/resolved/refactor-4-consolidate-invocations-routes/plan.md` — 追加本 bug 引用作为已知风险的实际案例

## Notes

### 确认诊断结果 (2026-06-10)

| 测试 | 命令 | 结果 |
|------|------|------|
| Gateway 子路径路由 | `curl -i /invocations/stream?q=hello` | ❌ `404 {"code":404,"message":"No matching policy found"}` |
| Gateway 精确路径路由 | `agentarts invoke '{"message":"hello"}'` | ✅ 200 OK，正常返回 Agent 响应 |
| CLI 子路径调用 | `agentarts invoke --custom-path invocations/stream ...` | ❌ `No matching policy found` |

**确认**：部署的 Runtime 的 `url_match_type` 为 `ACCURATE_MATCH`（默认值），精确路径 `/invocations` 可正常转发到容器，但子路径 `/invocations/stream` 被 Gateway 拒绝。

### 技术分析总结

以下结论综合了 DeepSeek、Gemini、GPT 三位 AI 顾问的并行分析：

| 分析维度 | 结论 |
|----------|------|
| **根因** | 404 是根因，CORS 错误是症状 — 请求从未到达 FastAPI，CORSMiddleware 未执行 |
| **最可能原因** | 部署的 Runtime `url_match_type` 为 `ACCURATE_MATCH`（默认值），未反映本地 `PREFIX_MATCH` 配置 |
| **平台已知缺陷** | `refactor-4` plan.md（第 407 行）已记录：*"`agentarts launch` 重新部署时 PREFIX_MATCH 配置不生效"* |
| **与 bug-8 的关系** | 独立 — 不同根因、不同子系统（基础设施 vs 前端构建） |
| **修复策略** | 诊断优先 → 确认配置漂移 → 重新 launch / 重建 Runtime → 验证 |

### 副发现：CORS 允许列表中的无关域名

当前 `CORS_ALLOWED_ORIGINS` 包含 `https://resource-governance.cloud`（可能来自模板/示例）。应确认该域名是否为合法来源，若非必要，应移除以避免放行意外 origin。此优化可作为本 bug 修复的一部分执行，但非阻塞项。

### 诊断决策树

```
浏览器报 CORS + 404
  ├─ curl -i /invocations/stream?q=test → 404 {"message":"No matching policy found"}
  │   └─ url_match_type 为 ACCURATE_MATCH → 场景 A：重新 launch
  └─ curl -i /invocations/stream?q=test → 200
      ├─ CORS_ALLOWED_ORIGINS 不包含 Netlify 域名 → 场景 C：修正 env var + relaunch
      └─ CORS_ALLOWED_ORIGINS 正确 → 检查 IAM 鉴权是否需要调整

注：agentarts runtime 无 describe 子命令，Runtime 配置需在 AgentArts 控制台查看
```

### 咨询顾问综合建议

本 issue 的范围和方案基于 DeepSeek（DeepSeek V4 Flash）、Gemini（Google Gemini 3.5 Flash）、GPT（GPT 5.5 Fast）三位 AI 顾问的并行分析综合得出。三方一致认为：

- **404 是根因，CORS 是症状** — 诊断必须从基础设施边界开始，而非从 CORS 配置开始
- **应创建新 bug，不更新 bug-8** — 根因和涉及子系统不同
- **诊断优先于修复** — 通过 `agentarts runtime describe` + `curl` 精确定位问题后再执行针对性修复
- **AgentArts 平台存在 `agentarts launch` 配置不生效的已知风险** — 需在 runbook 中增加验证步骤作为守护机制
- **所有四道闸门均通过** — 方案符合最佳实践、行业标准、常规认知和现代实践
