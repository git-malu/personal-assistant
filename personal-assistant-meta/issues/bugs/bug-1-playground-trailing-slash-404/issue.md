---
status: closed
related: feat/chainlit-playground
discovered_by: personal-assistant-e2e-tester
discovered_at: 2026-06-07 E2E test session for Feature 1.4
resolved_by: personal-assistant-e2e-tester
resolved_at: 2026-06-08 E2E regression verification
resolution: >-
  修复已确认。app/main.py L97-100 添加了显式 redirect route，
  GET /playground 返回 307 Temporary Redirect → /playground/。
  单元测试 + 回归测试 + Hermes E2E 全部通过。
---

# Bug 1: GET /playground (无 trailing slash) 返回 404

## 现象 (Symptoms)

访问 `http://host:8080/playground`（不带尾部斜杠）返回 HTTP 404 Not Found，而 `http://host:8080/playground/`（带尾部斜杠）正常返回 Chainlit UI。

```bash
$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/playground
404

$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/playground/
200
```

Service log 显示：
```
INFO: "GET /playground HTTP/1.1" 404 Not Found
INFO: "GET /playground/ HTTP/1.1" 200 OK
```

## 复现步骤 (Reproduction Steps)

1. 启动 Service：`uv run uvicorn app.main:app --host 127.0.0.1 --port 8080`
2. `curl http://127.0.0.1:8080/playground` → 404
3. `curl http://127.0.0.1:8080/playground/` → 200

## 预期 vs 实际 (Expected vs Actual)

| 场景 | 预期行为 | 实际行为 |
|------|---------|---------|
| GET /playground | 200，返回 Chainlit HTML UI | 404 Not Found |
| GET /playground/ | 200，返回 Chainlit HTML UI | 200 OK ✓ |

## 环境 (Environment)

- Feature branch: `feat/chainlit-playground`
- Service commit: `705b135` feat: chainlit-playground — debugging UI mounted at /playground
- Client commit: N/A (仅 Service 侧变更)
- E2E test session: 2026-06-07 manual verification + Hermes session `20260607_230014_ae776e`

## 影响 (Impact)

- **Blocking**: No — Chainlit Playground 功能完全可用（通过 `/playground/` 访问），但用户体验有瑕疵
- **Affected flows**: 浏览器地址栏输入 `/playground`（无尾部斜杠）的用户会看到 404 页面

## 根因分析

FastAPI 的 `app.mount("/playground", ...)` 仅匹配 `/playground/...` 路径，不匹配 `/playground` 本身。这是 Starlette 的 mount 行为 — 不会对挂载的 ASGI 子应用做自动 trailing slash redirect。

`mount_chainlit()` 内部调用 `app.mount(path=...)`, 同样受此限制。

## 修复方向

在 `mount_chainlit(...)` 之前添加显式 redirect route：

```python
from fastapi.responses import RedirectResponse

@app.get("/playground", include_in_schema=False)
async def playground_redirect():
    return RedirectResponse(url="/playground/")
```
