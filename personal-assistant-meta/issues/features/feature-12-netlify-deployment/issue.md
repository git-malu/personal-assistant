---
status: backlog
---

# Feature 12: Netlify 前端部署

为 personal-assistant-client 前端新增 Netlify 部署目标，作为现有 OBS 部署的补充。

---

## 背景

当前前端仅部署到华为云 OBS 静态网站托管。新增 Netlify 部署可提供：
- **自动构建**：Git push 到 main 后 Netlify 自动构建并部署
- **Deploy Preview**：PR 提交时自动生成预览链接（可选，后续启用）
- **全球 CDN + 免费 SSL**：无需额外配置
- **与 OBS 独立**：两条部署通道互不干扰，OBS 继续作为华为云正式部署

## 范围

### 前端配置

- [ ] 创建 `personal-assistant-client/netlify.toml`，配置 monorepo build、publish 目录、SPA redirect
- [ ] 确认 Netlify 构建命令 `npm run build` 和发布目录 `dist/` 正确

### 构建时环境变量

- [ ] 在 Netlify Site Settings → Environment variables 中设置 `VITE_API_BASE_URL` 为 AgentArts Runtime 域名（与 OBS 部署使用相同的值）
- [ ] 确认前端代码通过 `import.meta.env.VITE_API_BASE_URL` 获取 API base URL（已实现，`chat-adapter.ts`）

### 后端 CORS 配置

- [ ] 将 `app/main.py` 中硬编码的 CORS `allow_origins` 改为从环境变量读取，支持逗号分隔的多个 origin
- [ ] 在 AgentArts Runtime 环境变量中更新 `CORS_ALLOWED_ORIGINS`，加入 Netlify 生产域名
- [ ] 更新 `test_main.py` 中 CORS 相关测试，使其适配多 origin 模式

### SPA 路由

- [ ] `netlify.toml` 中配置 SPA fallback redirect：`/* → /index.html (200)`

### 验证

- [ ] Netlify 构建成功，页面正常渲染
- [ ] 从 Netlify 域名发送对话消息，SSE 流式回复正常
- [ ] 浏览器 DevTools Console 无 CORS 错误
- [ ] 直接访问非根路径（如 `/chat`）返回 200（SPA fallback 生效）
- [ ] OBS 部署不受影响，两条通道独立工作

## 不涉及

- Netlify proxy rewrites（`/api/*` 反向代理到后端）—— 保持前后端直连架构，与未来 CDN 同域方案不冲突
- Netlify Deploy Previews 的 CORS 配置（预览域名动态生成，后续按需启用）
- OBS 部署流程的任何变更
- 自定义域名绑定（后续按需配置，届时更新 CORS 列表即可）
- CI/CD 集成（Netlify 自带 Git 集成，无需额外 GitHub Actions）

## 受影响架构文档

- `personal-assistant-meta/architecture/frontend_architecture.md` — §6.2 Web Chat 部署拓扑需新增 Netlify 部署节点
- `personal-assistant-meta/architecture/devops/cicd.md` — 部署策略需记录 Netlify 作为额外部署目标

## Notes

### 技术决策要点

1. **CORS 是首要阻塞点**：当前后端 CORS 硬编码了 OBS 域名（`allow_origins=["https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com"]`），Netlify 域名是新 origin，必须加入允许列表。推荐改为环境变量驱动（`CORS_ALLOWED_ORIGINS`），支持逗号分隔多域名。

2. **SPA fallback**：Netlify 通过 `netlify.toml` 的 `[[redirects]]` 声明 `/* → /index.html (200)` 实现，比 OBS 的 Error Document hack 更原生。

3. **`VITE_API_BASE_URL` 是构建时变量**：Vite 在构建时将 `VITE_` 前缀变量静态嵌入 bundle，Netlify 必须在构建前通过 Environment variables 设置。变更后端 URL 需要重新触发构建。

4. **OAuth Cookie 跨 origin 隔离**：用户在 OBS 上的登录状态不会在 Netlify 上可用（不同 cookie 域），这是预期行为，无需特殊处理。

### 推荐配置

**`personal-assistant-client/netlify.toml`**：

```toml
[build]
  base = "personal-assistant-client"
  command = "npm run build"
  publish = "dist"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

**`app/main.py` CORS 改造**（核心变更）：

```python
import os

default_origins = [
    "https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com"
]
env_origins = os.getenv("CORS_ALLOWED_ORIGINS")
allowed_origins = [o.strip() for o in env_origins.split(",")] if env_origins else default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**AgentArts Runtime 环境变量更新**：
```
CORS_ALLOWED_ORIGINS=https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com,https://<site-name>.netlify.app
```

### 与现有 Issues 的关系

| Issue | 关系 |
|-------|------|
| `feature-11-github-workflow-terraform-deploy` | 独立 — feature-11 专注华为云 OBS + Terraform CI/CD，本 issue 专注 Netlify 平台部署 |
| `chore-1-agentarts-deploy` | 需更新 runbook，新增 Netlify 部署步骤及 CORS 环境变量配置说明 |
| `feature-9-deployment` | 总体部署上线包含本 issue 产出的验证项 |
