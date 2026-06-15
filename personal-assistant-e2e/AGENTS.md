# AGENTS.md

> 本文件是 **personal-assistant-e2e** 目录的专用 instructions，仅适用于该目录下的相关工作。

## Directory Guide

`personal-assistant-e2e/` 存放端到端测试脚本，覆盖 Service + Client 联调场景。测试框架使用 **pytest**。

开始前先阅读项目根目录的 [`AGENTS.md`](../AGENTS.md) 了解整体项目结构和规范。

## 目录结构

```
personal-assistant-e2e/
├── AGENTS.md               # 本文件
├── conftest.py             # 共享 fixtures（service/client 启停、health check 等）
├── pyproject.toml          # pytest 配置（markers、asyncio mode 等）+ 项目依赖
└── tests/
    ├── regression/         # 回归测试——每个 bug 一条用例，用于 bug 复现和修复验证
    │   └── test_bug_N_<slug>.py
    └── features/           # 功能 E2E 测试——按 feature 组织
        └── test_feature_N_<slug>.py
```

## 测试编写规范

- **框架**: pytest + pytest-asyncio（Service/Client 均为异步调用）
- **HTTP 客户端**: `httpx`（AsyncClient）
- **命名**: 测试文件以 `test_` 前缀，测试函数以 `test_` 前缀
- **Markers**: 使用 `@pytest.mark.regression` 标记回归测试，`@pytest.mark.feature` 标记功能测试
- **Fixtures**: 在 `conftest.py` 中定义 `service_url`、`client_url` 等共享 fixtures，负责启动/等待健康检查/停止
- **隔离**: 每个测试独立，不依赖执行顺序

## 运行

```bash
# 全部 E2E 测试
pytest personal-assistant-e2e/

# 仅回归测试
pytest personal-assistant-e2e/ -m regression

# 仅功能测试
pytest personal-assistant-e2e/ -m feature

# 指定 bug 回归
pytest personal-assistant-e2e/tests/regression/test_bug_1_playground_trailing_slash_404.py -v
```

## 谁来写测试

- **personal-assistant-e2e-tester**：发现 bug 后在 `tests/regression/` 添加回归用例
- **personal-assistant-meta-dev**：在 Implementation Plan 中设计功能 E2E 用例后，可放入 `tests/features/`
- 回归测试在 bug 修复后由 personal-assistant-e2e-tester 重新执行以验证修复
