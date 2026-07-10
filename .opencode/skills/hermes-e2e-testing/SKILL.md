---
name: hermes-e2e-testing
description: "Use when the E2E tester needs to invoke Hermes CLI for end-to-end testing — starting services, running browser/API tests, and collecting structured reports. Covers correct CLI flags, prompt templates, toolset selection, error handling, and output parsing."
---

# Hermes E2E Testing

This skill teaches the E2E tester how to invoke **Hermes** as a child process to orchestrate
full-stack integration tests (start Service + Client, run browser/API scenarios, stop, report).

## 1. Correct CLI Invocation

The flag is **`-q` / `--query`** — there is no `--prompt` flag.

```bash
hermes chat -q "<test instructions>" \
  --yolo \
  --quiet \
  --toolsets terminal,file,web,browser,todo \
  --max-turns 120
```

| Flag | Why |
|------|-----|
| `-q` / `--query` | Non-interactive single query (required) |
| `--yolo` | Skip destructive-command approval prompts (Hermes is starting/stopping servers) |
| `--quiet` / `-Q` | Suppress banner, spinner, tool previews — only the final response is printed |
| `--toolsets` | Explicitly scope Hermes to only the tools needed for testing |
| `--max-turns` | Cap at ~120 turns; default 90 may be too low for startup + multi-scenario tests |

**Workdir:** Always run from the project root:

```bash
cd /Users/malu/Projects/github/personal-assistant && hermes chat -q "..." ...
```

## 2. Toolset Selection by Test Type

| Toolset | When needed |
|---------|-------------|
| `terminal` | **Always** — starting/stopping servers, running commands |
| `file` | **Always** — reading configs, checking build artifacts |
| `web` | API endpoint testing (curl-like), health checks |
| `browser` | Web Chat UI testing (navigate, click, type, snapshot) |
| `todo` | Structured multi-step test execution |
| `vision` | Screenshot-based UI verification (adds latency, use sparingly) |

**For API-only tests** (no browser): omit `browser` and `vision`.
**For Web Chat tests**: include `browser`; add `vision` only when text snapshots are insufficient.

## 3. E2E Test Prompt Template

### Standard Template (Web Chat + API)

```
Run E2E tests for the personal-assistant application:

## Setup
1. cd /Users/malu/Projects/github/personal-assistant
2. Start the backend service from personal-assistant-service/:
   - Identify the startup command (check package.json, Makefile, or docker-compose.yml)
   - Start it in background, wait for it to be healthy (poll the health endpoint)
   - If it fails to start after 60s, report FAIL and stop
3. Start the frontend from personal-assistant-client/:
   - Identify the dev server command (check package.json)
   - Start it in background, wait for the dev server to respond on its port
   - If it fails to start after 60s, report FAIL, stop backend, and stop

## Test Scenarios
<INSERT SPECIFIC SCENARIOS HERE>

## Teardown
4. Stop the frontend process
5. Stop the backend process
6. Verify no leftover processes on the service ports

## Report Format
Provide a structured report:
### Status: PASSED / FAILED
| # | Scenario | Expected | Actual | Result |
|---|----------|----------|--------|--------|
### Failures (if any)
### Environment: service status, client status, any errors
```

### API-Only Variant

Replace the browser test sections with `curl`/`web` tool calls:

```
## Test Scenarios (API)
- POST /api/health → expect 200
- GET /api/... → expect { ... }
```

## 4. Writing Test Scenarios

Each scenario must include **exact expected behavior** so Hermes can unambiguously judge PASS/FAIL:

**Good:**
```
- Navigate to http://localhost:5173, type "Hello" in the chat input, click Send.
  Expect: a new message bubble appears with the text "Hello" within 10 seconds.
```

**Bad:**
```
- Test the chat functionality.
```

For each scenario, specify:
- **Action**: exact steps (URL, input text, button to click)
- **Expected result**: concrete, verifiable outcome
- **Timeout**: if response is async (e.g., "within 10 seconds")

## 5. Interpreting Hermes Output

With `--quiet`, Hermes prints only the final assistant response. Parse this for:

- **`Status: PASSED`** or **`Status: FAILED`** — overall result
- **Result table** — per-scenario ✅/❌
- **Failures section** — details to include in your E2E test report
- **Blocking issues** — service startup failures, port conflicts, build errors

The E2E tester wraps this in its own structured report format (see agent file).

## 6. Error Handling Patterns

| Hermes issue | Likely cause | What to do |
|-------------|-------------|-------------|
| Hermes times out (no response after 10 min) | `--max-turns` exhausted or LLM stuck | Increase `--max-turns` to 150, reduce scenario count |
| "command not found: hermes" | Hermes not in PATH | Ensure Hermes is installed and in the agent's shell environment |
| Service fails to start | Port conflict, missing deps, config error | Hermes output should include the error. Extract and include in your report as a BLOCKING issue. |
| Browser tests fail but API passes | Frontend JS error, CORS, build issue | Check browser console output (Hermes captures it with `browser_console`) |
| Hermes output truncated | Response too long for `--quiet` buffer | Remove `--quiet`, use full output; or split into two Hermes calls |

## 7. Parallel vs Sequential Hermes Calls

**One comprehensive Hermes call is preferred** — it handles setup → test → teardown atomically. This matches the agent rule "One test session per task."

Split into multiple calls only when:
- The first call's output is needed to construct the second call's prompt
- A scenario requires human-like iterative interaction that Hermes can't plan ahead

## 8. Quick Health Check (Pre-Test)

Before sending the full E2E test prompt, verify Hermes is functional:

```bash
hermes chat -q "Run: echo 'hermes is working' and report the result." --yolo --quiet --toolsets terminal
```

If this fails (exit code ≠ 0 or no output), do not proceed with the full test — report the Hermes availability issue to pa-e2e-manager.

## 9. Timeout & Resource Limits

| Constraint | Default | Recommendation |
|-----------|---------|----------------|
| `--max-turns` | 90 | 120 for simple tests, 150 for 3+ browser scenarios |
| Hermes process timeout | None (terminal tool) | Set 600s (10 min) for full E2E suite |
| Service startup wait | — | 60s per service, then fail |

## Pitfalls

- **Wrong flag**: `hermes --prompt` does NOT exist. Use `hermes chat -q`.
- **Missing `--yolo`**: Hermes will prompt for approval on `kill`, `rm`, `npm install` — blocking non-interactive execution.
- **Missing `--quiet`**: Tool preview and spinner output mixes with the test report, making parsing fragile.
- **Wrong workdir**: Always `cd` to project root before calling Hermes. Hermes inherits the shell's CWD.
- **Browser not available**: The `browser` toolset requires a configured browser backend (Browserbase, Camofox, or local Chromium). If unconfigured, Hermes will fail silently or error. Verify with the health check first.
- **Port conflicts**: If a previous test session left processes running, new startups will fail. The teardown step (kill all service processes) is critical.
