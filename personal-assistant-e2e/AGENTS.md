# personal-assistant-e2e

> 本文件是 `personal-assistant-e2e/` 目录的专用 instructions，仅适用于该目录下的相关工作。开始前先阅读项目根目录的 [`AGENTS.md`](../AGENTS.md)。

## Directory Guide

`personal-assistant-e2e/` 存放端到端测试脚本，覆盖跨进程、跨前后端、浏览器和真实环境验证场景。测试框架使用 pytest + pytest-asyncio + httpx；涉及浏览器交互时使用 Playwright。

## Directory Structure

```text
personal-assistant-e2e/
├── conftest.py             # 共享 fixtures（service/client 启停、health check 等）
├── pyproject.toml          # pytest markers、asyncio mode、依赖
├── uv.lock
├── tests/
│   ├── smoke/              # 稳定、轻量、可进入 PR gate 的跨边界冒烟
│   ├── browser/            # Playwright 用户路径测试
│   ├── full_stack/         # Client / proxy / Service 本地联调
│   └── manual/             # 真实账号 / OAuth / 云端验证，默认不自动运行
├── README.md
└── AGENTS.md
```

## Tech Stack

- **语言**: Python 3.12+
- **测试框架**: pytest, pytest-asyncio
- **HTTP 客户端**: httpx AsyncClient
- **浏览器测试**: Playwright
- **代码质量**: Ruff
- **依赖管理**: uv

## Build and Test Commands

```bash
cd personal-assistant-e2e
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pytest -m smoke
uv run pytest -m browser
uv run pytest -m full_stack
```

也可以从仓库根目录运行：

```bash
uv run --project personal-assistant-e2e pytest personal-assistant-e2e/
```

## Test Authoring Guidelines

- 测试文件以 `test_` 前缀命名，测试函数以 `test_` 前缀命名。
- 根据目录添加 `@pytest.mark.smoke`、`@pytest.mark.browser`、`@pytest.mark.full_stack` 或 `@pytest.mark.manual`；回归测试可额外使用 `@pytest.mark.regression`，功能测试可额外使用 `@pytest.mark.feature`，耗时测试使用 `@pytest.mark.slow`。
- 每个测试必须独立，不依赖执行顺序或其他测试留下的状态。
- 优先通过 fixtures 管理 Service/Client 启停、health check、base URL 和 session headers。
- 测试命名应包含 feature/bug 编号和可读 slug，例如 `test_bug_1_playground_trailing_slash_404.py`。
- 只验证 Service 内部行为的测试不得放入本目录；`FastAPI TestClient`、`ASGITransport`、Service 配置 contract 和 tool schema 应放入 `personal-assistant-service/tests/`。

## Testing Instructions

- 新 bug 修复必须根据测试边界添加到 `smoke/`、`browser/`、`full_stack/` 或相关子系统自己的 tests。
- 新 feature 的 Implementation Plan 应说明需要的测试归属：Service、Client、Infra、E2E smoke、E2E browser、E2E full_stack 或 manual。
- 涉及 SSE streaming、auth/session、Cloudflare Pages proxy 或 browser UI 的变更，应覆盖 Service + Client 的真实联调路径。
- 外部账号、OAuth token、云端 secrets 不得写入测试代码；通过环境变量或 test fixtures 注入。真实账号/OAuth 测试必须标记 `manual`，默认不进入 PR gate。

## Ownership

- **pa-e2e-tester**：发现 bug 后在 `tests/regression/` 添加回归用例，并在修复后重新执行验证。
- **pa-meta-dev**：在 Implementation Plan 中设计功能 E2E 用例。
- **service/client/infra implementer**：实现涉及联调风险的变更时，需同步更新或运行相关 E2E。
