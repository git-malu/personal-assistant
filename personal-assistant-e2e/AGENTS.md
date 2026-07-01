# personal-assistant-e2e

> 本文件是 `personal-assistant-e2e/` 目录的专用 instructions，仅适用于该目录下的相关工作。开始前先阅读项目根目录的 [`AGENTS.md`](../AGENTS.md)。

## Directory Guide

`personal-assistant-e2e/` 存放端到端测试脚本，覆盖 Service + Client 联调场景。测试框架使用 pytest + pytest-asyncio + httpx；涉及浏览器交互时使用 Playwright。

## Directory Structure

```text
personal-assistant-e2e/
├── conftest.py             # 共享 fixtures（service/client 启停、health check 等）
├── pyproject.toml          # pytest markers、asyncio mode、依赖
├── uv.lock
├── tests/
│   ├── regression/         # 每个 bug 一条回归用例
│   │   └── test_bug_N_<slug>.py
│   └── features/           # 按 feature 组织的功能 E2E
│       └── test_feature_N_<slug>.py
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
uv run pytest -m regression
uv run pytest -m feature
```

也可以从仓库根目录运行：

```bash
uv run --project personal-assistant-e2e pytest personal-assistant-e2e/
```

## Test Authoring Guidelines

- 测试文件以 `test_` 前缀命名，测试函数以 `test_` 前缀命名。
- 回归测试使用 `@pytest.mark.regression`，功能测试使用 `@pytest.mark.feature`，耗时测试使用 `@pytest.mark.slow`。
- 每个测试必须独立，不依赖执行顺序或其他测试留下的状态。
- 优先通过 fixtures 管理 Service/Client 启停、health check、base URL 和 session headers。
- 测试命名应包含 feature/bug 编号和可读 slug，例如 `test_bug_1_playground_trailing_slash_404.py`。

## Testing Instructions

- 新 bug 修复必须在 `tests/regression/` 添加或更新回归用例。
- 新 feature 的 Implementation Plan 应说明需要的 E2E 覆盖，并在 `tests/features/` 添加对应测试。
- 涉及 SSE streaming、auth/session、Cloudflare Pages proxy 或 browser UI 的变更，应覆盖 Service + Client 的真实联调路径。
- 外部账号、OAuth token、云端 secrets 不得写入测试代码；通过环境变量或 test fixtures 注入。

## Ownership

- **personal-assistant-e2e-tester**：发现 bug 后在 `tests/regression/` 添加回归用例，并在修复后重新执行验证。
- **personal-assistant-meta-dev**：在 Implementation Plan 中设计功能 E2E 用例。
- **service/client/infra implementer**：实现涉及联调风险的变更时，需同步更新或运行相关 E2E。
