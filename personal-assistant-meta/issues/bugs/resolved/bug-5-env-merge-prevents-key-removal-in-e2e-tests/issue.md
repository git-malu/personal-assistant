---
status: invalid
resolution: not-a-bug — 被测逻辑已由单元测试覆盖，E2E 测试设计不当
related: feat/web-chat-frontend
discovered_by: personal-assistant-e2e-tester
discovered_at: 2026-06-08 E2E test session (post BUG-4 fix verification)
closed_at: 2026-06-08
---

# Bug 5: E2E Test Environment Merge Prevents Removing Environment Variables

## 现象 (Symptoms)

Three E2E tests in `TestScenario4_MissingApiKey` (`test_feature_1_3_multi_llm.py`) fail with `DID NOT RAISE RuntimeError`. The tests expect the service to crash on startup when API keys are missing, but the service starts successfully instead.

**Root cause**: The `_start_service()` helper (and `ServiceProcess.start()`) uses a merge pattern that cannot remove environment variables:

```python
merged_env = os.environ.copy()
if env:
    merged_env.update(env)
```

`dict.update()` only adds/overwrites keys — it does NOT remove keys. When the test builds a `clean_env` without `MODEL_API_KEY`, the `update` preserves the key from `os.environ.copy()`.

This is compounded by `load_dotenv()` in `app/main.py`, which loads `.env` file values into the test process's `os.environ` during pytest collection (when `conftest.py` imports `app.main`).

## 复现步骤 (Reproduction Steps)

1. Ensure `.env` file exists in `personal-assistant-service/` with `MODEL_API_KEY` set
2. Run: `pytest personal-assistant-e2e/tests/features/test_feature_1_3_multi_llm.py::TestScenario4_MissingApiKey -v`
3. Observe all 3 tests fail: `DID NOT RAISE RuntimeError`

To confirm the actual application behavior is correct:
```bash
# Service DOES crash without API keys when .env is truly absent:
cd personal-assistant-service && mv .env .env.bak && mv config.yaml config.yaml.bak
# unset all API key env vars and start uvicorn → crashes with RuntimeError
```

## 预期 vs 实际 (Expected vs Actual)

| 场景 | 预期行为 | 实际行为 |
|------|---------|---------|
| Service started without any API key | Service exits with `RuntimeError("LLM 配置错误: ...")` | Service starts successfully (API keys leak via `os.environ.copy()`) |
| Service started with only DEEPSEEK_API_KEY when default is maas | Service exits with `RuntimeError` referencing MAAS_API_KEY | Service starts successfully (MODEL_API_KEY leaks via env merge) |
| Service started with no config.yaml, no .env, no API keys | Service exits with clear error about MODEL_API_KEY | Service starts successfully (MODEL_API_KEY leaks via env merge) |

## 环境 (Environment)

- Feature branch: `feat/web-chat-frontend`
- Service commit: `46d6b58`
- Client commit: `46d6b58`
- E2E test session: 2026-06-08 full suite run (53 tests)

## 影响 (Impact)

- **Blocking**: No — the application behavior is correct; the bug is in test infrastructure
- **Affected flows**: `TestScenario4_MissingApiKey` (3 tests) in `test_feature_1_3_multi_llm.py`
- **Affected functions**: 
  - `_start_service()` in `tests/features/test_feature_1_3_multi_llm.py`
  - `_start_service()` in `tests/features/test_feature_1_1_web_chat.py`
  - `ServiceProcess.start()` in `conftest.py`

## Suggested Fix (for reference only — not for E2E tester)

The env merge pattern should allow removal of variables. Two approaches:

**Option A**: Start from the caller's env, add missing OS-level vars:
```python
merged_env = dict(env) if env else {}
for k, v in os.environ.items():
    if k not in merged_env:
        merged_env[k] = v
```

**Option B**: Use a sentinel or explicit deletion list in the env dict.
