---
status: done
related: bug-3-playground-returns-404 (commit f51c0f7)
discovered_by: personal-assistant-e2e-tester
discovered_at: 2026-06-08 E2E re-run for Feature 1.1
resolved_by: personal-assistant-manager
resolved_at: 2026-06-08
resolution: |
  Fixed in commit 46d6b58.
  将 mount_chainlit 的 target 参数从相对路径 "app/playground.py" 改为 Path(__file__).parent / "playground.py"，
  使用模块自定位消弭 CWD 敏感性。
  验证: playground.py 路径恒解析为 <SERVICE_DIR>/app/playground.py（绝对路径），文件存在。
---

# Bug 4: `mount_chainlit` relative path breaks module import from outside SERVICE_DIR

## 现象 (Symptoms)

`main.py` line 103 调用 `mount_chainlit(app=app, target="app/playground.py", path="/playground")` 使用相对路径。Chainlit 的 `check_file()` 基于 CWD 解析该相对路径，导致：

- **uvicorn subprocess** (cwd=SERVICE_DIR): 路径解析为 `personal-assistant-service/app/playground.py` → ✅ 存在
- **pytest in-process import** (cwd=project root): 路径解析为 `personal-assistant/app/playground.py` → ❌ 不存在

11 个 feature E2E 测试全部 **ERROR**（Scenarios 2, 4, 5），因为它们通过 `fake_handler` fixture 在进程内 `from app.main import app`。

```
click.exceptions.BadParameter: File does not exist: app/playground.py
```

## 复现步骤 (Reproduction Steps)

1. Clone the repo, checkout `feat/web-chat-frontend`
2. `cd /Users/malu/Projects/github/personal-assistant` (project root, NOT service dir)
3. `python -c "import sys; sys.path.insert(0, 'personal-assistant-service'); from app.main import app"`
4. Observe: `BadParameter: File does not exist: app/playground.py`
5. Change CWD to service dir: `cd personal-assistant-service && python -c "from app.main import app"` → succeeds

## 预期 vs 实际 (Expected vs Actual)

| 场景 | 预期行为 | 实际行为 |
|------|---------|---------|
| Import `app.main` from project root | Module loads successfully | `BadParameter` — relative path resolved wrong |
| Subprocess-based E2E tests (Scenarios 3,7,8) | Pass | Pass ✅ (uvicorn runs from SERVICE_DIR) |
| In-process E2E tests (Scenarios 2,4,5) | Pass | ERROR — `fake_handler` fixture can't import `app.main` |

## 环境 (Environment)

- Feature branch: `feat/web-chat-frontend`
- Service commit: f51c0f7 ("fix: BUG-3 — merge Chainlit playground code from main, resolve /playground 404")
- Client commit: same
- E2E test session: 2026-06-08 re-run

## 影响 (Impact)

- **Blocking**: Yes — prevents 11/31 E2E tests from running (Scenarios 2, 4, 5 — SSE streaming, multi-turn, error handling)
- **Affected flows**: In-process testing, any code that imports `app.main` from outside SERVICE_DIR, potential production edge case if deployment CWD differs

## Suggested Fix Direction

Replace relative path with module-relative path in `main.py`:

```python
# Before (fragile):
mount_chainlit(app=app, target="app/playground.py", path="/playground")

# After (robust):
playground_path = Path(__file__).parent / "playground.py"
mount_chainlit(app=app, target=str(playground_path), path="/playground")
```
