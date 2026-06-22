# Personal Assistant E2E

端到端测试，覆盖 Service + Client 联调场景。使用 **pytest** + **pytest-asyncio** + **httpx**。

Feature 14 测试覆盖 durable `conversation_id` 与 replaceable Runtime Session 的
identity 分离，以及同一用户多个 Conversation 共享 Runtime 时的上下文隔离。

## 目录结构

```
personal-assistant-e2e/
├── conftest.py         # 共享 fixtures（service/client 启停、health check）
├── pyproject.toml      # pytest 配置 + 项目依赖
├── tests/
│   ├── regression/     # 回归测试（按 bug 组织）
│   └── features/       # 功能 E2E 测试（按 feature 组织）
├── AGENTS.md           # E2E 域专用 instructions
└── README.md           # 本文件
```

## 运行

```bash
# 全部 E2E 测试
pytest personal-assistant-e2e/

# 仅回归测试
pytest personal-assistant-e2e/ -m regression

# 仅功能测试
pytest personal-assistant-e2e/ -m feature
```
