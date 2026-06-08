---
status: backlog
related: feat/web-chat-frontend
discovered_by: personal-assistant-e2e-tester
discovered_at: 2026-06-08 E2E test session for Feature 1.1
---

# Bug 2: SPA Fallback Not Working (StaticFiles html=True)

## 现象 (Symptoms)

The `StaticFiles` mount in `main.py` uses `html=True` with the documented intent of enabling SPA fallback (client-side routing). However, accessing any path that doesn't correspond to a physical file in `dist/` — such as `/chat`, `/settings`, or any client-side route — returns **404 Not Found** instead of serving `index.html`.

The comment in `main.py` (line 106) states:
> `html=True: enables SPA fallback — any path not matching a physical file serves index.html, allowing React Router (or equivalent) to handle client-side routing.`

This comment is incorrect for Starlette 1.2.1. The `html=True` parameter in Starlette's `StaticFiles` only serves `index.html` from a matching directory path (e.g., `/chat/` → tries `dist/chat/index.html`). It does **NOT** perform root-level `index.html` fallback for arbitrary paths.

### Evidence

```bash
# Service running with dist/ mounted
GET /chat → 404 Not Found (application/json)
GET /playground → 404 Not Found (application/json)
GET / → 200 OK (serves index.html correctly)
```

The 404 responses have `content-type: application/json` (FastAPI's default 404 handler), confirming the StaticFiles middleware is not handling these paths.

## 复现步骤 (Reproduction Steps)

1. Run `npm run build` in `personal-assistant-client/` to generate `dist/`
2. Start the service: `uv run uvicorn app.main:app --port 8765` with `MAAS_API_KEY=dummy`
3. `GET http://127.0.0.1:8765/chat`
4. Observe: **404 Not Found** (expected: 200 with index.html)

## 预期 vs 实际 (Expected vs Actual)

| 场景 | 预期行为 | 实际行为 |
|------|---------|---------|
| GET /chat | 200 OK, serves index.html (SPA fallback) | 404 Not Found |
| GET /settings | 200 OK, serves index.html | 404 Not Found |
| GET / | 200 OK, serves index.html | 200 OK ✅ |

## 环境 (Environment)

- Feature branch: `feat/web-chat-frontend`
- Starlette version: 1.2.1
- FastAPI version: (latest via uv.lock)
- E2E test session: Feature 1.1 E2E test run on 2026-06-08

## 影响 (Impact)

- **Blocking**: No — the root page (`/`) works correctly, and the application can function as long as users always start from `/`. However, direct navigation to client-side routes (e.g., bookmarking `/chat`) will fail.
- **Affected flows**: 
  - Direct URL navigation to any client-side route
  - Browser refresh on a client-side route
  - The assistant-ui client-side routing (via `@assistant-ui/react`) cannot be used with URL-based navigation

## 修复建议 (Fix Direction)

A catch-all route should be registered **before** the `StaticFiles` mount:

```python
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # Only fall back to index.html for non-API, non-asset paths
    if full_path.startswith("api/") or full_path.startswith("assets/"):
        raise HTTPException(status_code=404)
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    raise HTTPException(status_code=404)
```

Or consider using `Mount` with a custom SPA fallback ASGI app.

> ⚠️ **此方案的注意点**：若 catch-all 路由注册在 `StaticFiles` mount 之前，它会拦截**所有**请求，包括 Vite build 产物的真实文件（如 `/assets/main-abc123.js`、`/vite.svg` 等）。`startswith("assets/")` 过滤不够——Vite 输出可能有根级文件，且路径过滤与 build 产物结构耦合。若注册在 `StaticFiles` mount 之后，又永远走不到（mount `/` 会把请求全吃掉）。需要额外做文件存在性检查并自行处理路径遍历安全。

## 替代方案 (Alternative): Middleware 拦截 404

在 `StaticFiles` 外层加 Middleware，不跟路由优先级竞争——StaticFiles 该 serve 什么就 serve 什么，只在它返回 404 时把响应替换成 `index.html`。

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse

class SPAFallbackMiddleware(BaseHTTPMiddleware):
    """Intercept 404 from StaticFiles and serve index.html for SPA client-side routes."""

    def __init__(self, app, static_dir: Path, skip_prefixes=("/api/", "/playground")):
        super().__init__(app)
        self.static_dir = static_dir
        self.skip_prefixes = skip_prefixes

    async def dispatch(self, request, call_next):
        # Let API and playground requests pass through without fallback
        if any(request.url.path.startswith(p) for p in self.skip_prefixes):
            return await call_next(request)

        response = await call_next(request)
        if response.status_code == 404:
            index = self.static_dir / "index.html"
            if index.exists():
                return FileResponse(str(index))
        return response

# 使用方式：在 app 上 add，StaticFiles mount 保持不变
app.add_middleware(SPAFallbackMiddleware, static_dir=STATIC_DIR)
```

| 对比维度 | Catch-all 路由方案 | Middleware 方案 |
|---|---|---|
| 路由优先级冲突 | 存在，需要精确处理顺序和路径过滤 | 不存在，不参与路由匹配 |
| 真实静态文件 | 可能被误拦截，需要自行判断文件存在性 | StaticFiles 照常处理 |
| 路径遍历安全 | 需要自己实现 resolve + startswith 校验 | 复用 StaticFiles 内置校验 |
| 侵入性 | 替代 StaticFiles 的部分职责 | 零侵入，StaticFiles 不动 |
| 运行时开销 | 无额外开销（正常路由匹配） | 每个请求多一次 status code 检查 |
| 代码量 | ~10 行 | ~20 行（含 class 定义） |
