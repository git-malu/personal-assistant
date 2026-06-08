---
status: backlog
related: feature-1.4-chainlit-playground
discovered_by: personal-assistant-e2e-tester
discovered_at: 2026-06-08 E2E session
---

# Bug 6: Vite Dev Server 未代理 /playground 到 Chainlit 后端

## 现象 (Symptoms)

访问 `http://localhost:5173/playground` 时，预期显示 Chainlit 调试 UI，实际却渲染了 assistant-ui 的 SPA（Web Chat 界面）。

后端 FastAPI 已正确挂载 Chainlit（`mount_chainlit` 在 `main.py:104`，`/playground` redirect 在 `main.py:98-101`），通过 `http://localhost:8080/playground/` 可正常访问 Chainlit UI。但 Vite dev server（端口 5173）没有代理 `/playground` 路径到后端，导致该路径被 Vite 的 SPA fallback 吃掉。

## 复现步骤 (Reproduction Steps)

1. 启动后端：`cd personal-assistant-service && uv run uvicorn app.main:app --port 8080`
2. 启动前端：`cd personal-assistant-client && npm run dev`
3. 浏览器访问 `http://localhost:5173/playground`
4. 观察：显示的是 assistant-ui SPA（Web Chat 界面），而非 Chainlit 调试 UI
5. 对比：访问 `http://localhost:8080/playground/` → Chainlit UI 正常显示

## 预期 vs 实际 (Expected vs Actual)

| 场景 | 预期行为 | 实际行为 |
|------|---------|---------|
| GET `localhost:5173/playground` | 代理到后端 Chainlit mount，返回 Chainlit HTML UI | Vite SPA fallback 捕获，返回 `index.html`（assistant-ui SPA） |
| GET `localhost:5173/playground/` | 同上，Chainlit UI | 同上，assistant-ui SPA |
| GET `localhost:5173/api/ping` | 代理到后端，返回 200 | ✅ 正常代理（`/api` 已有 proxy rule） |

## 根因 (Root Cause)

`vite.config.ts` 的 `server.proxy` 只配置了 `/api` 路径的代理，没有 `/playground` 路径：

```typescript
server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      // ❌ 缺少 '/playground' 代理规则
    },
},
```

根据 `frontend_architecture.md` §2.1.1，Chainlit Playground 定位为与 Web Chat 长期共存的调试工具，路径 `/playground`。在本地开发模式下，用户期望通过同一端口（Vite dev server 的 5173）访问所有功能，但当前必须记住后端端口 8080 才能访问 Playground。

## 环境 (Environment)

- Feature branch: `feat/web-chat-frontend`
- Service commit: Chainlit mount 已存在于 `main.py`（`mount_chainlit` + `/playground` redirect）
- Client commit: `vite.config.ts` 仅代理 `/api`，无 `/playground` 代理
- Chainlit: 已安装（`pyproject.toml` 包含 `chainlit>=2.11.1`）

## 影响 (Impact)

- **Blocking**: No — Playground 可通过 `localhost:8080/playground/` 正常访问，但开发体验有瑕疵
- **Affected flows**: 开发者在 Vite dev server 端口（5173）无法直接访问 Playground，需要记住切换到后端端口（8080）。与架构文档所述 "Web Chat 与 Playground 在同一容器内共存" 的预期不一致
