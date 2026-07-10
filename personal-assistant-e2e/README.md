# Personal Assistant E2E

端到端测试，覆盖跨进程、跨前后端、浏览器和真实环境验证场景。使用 **pytest** + **pytest-asyncio** + **httpx**；涉及 UI 用户路径时使用 **Playwright**。

## 目录结构

```
personal-assistant-e2e/
├── conftest.py         # 共享 fixtures（service/client 启停、health check）
├── pyproject.toml      # pytest 配置 + 项目依赖
├── tests/
│   ├── smoke/          # 稳定、轻量、可进入 PR gate 的跨边界冒烟
│   ├── browser/        # Playwright 用户路径测试
│   ├── full_stack/     # Client / proxy / Service 本地联调
│   └── manual/         # 真实账号 / OAuth / 云端验证，默认不自动运行
├── AGENTS.md           # E2E 域专用 instructions
└── README.md           # 本文件
```

## 运行

```bash
# 全部可自动运行的 E2E 测试
uv run pytest

# PR gate 候选：稳定冒烟
uv run pytest -m smoke

# 浏览器用户路径
uv run pytest -m browser

# 本地全栈联调
uv run pytest -m full_stack

# 真实账号 / OAuth 测试只允许显式启用
uv run pytest -m manual
```

Service-only 的 `FastAPI TestClient`、`ASGITransport`、配置 contract、tool schema 等测试应放在 `personal-assistant-service/tests/`，不要放入本目录。
