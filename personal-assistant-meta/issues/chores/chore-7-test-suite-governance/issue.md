---
status: in_progress
---

# Chore 7: 测试体系治理与 E2E 分层落地

按照 [`architecture/devops/test/test-strategy.md`](../../../architecture/devops/test/test-strategy.md)
定义的测试分层和目录归属规则，整理当前 Service、Client、E2E 测试资产，修复
`personal-assistant-e2e` 可运行性，并建立最小 CI 门禁。

---

## 背景

当前仓库已经有较多测试，但边界混用明显：

- `personal-assistant-e2e/` 中存在多份 `TestClient + FakeAgentHandler` 风格的
  Service integration tests。
- `personal-assistant-e2e/pyproject.toml` 未声明 `fastapi`，但多份 E2E 测试在
  collection 阶段直接 `from fastapi.testclient import TestClient`。
- `personal-assistant-e2e/tests/` 目前按 `features/` 和 `regression/` 组织，
  无法直接看出哪些是 smoke、browser、full_stack、manual real-auth。
- GitHub Actions 尚未把稳定的 E2E smoke 作为 PR / main 门禁。

这导致两个问题：

1. 测试运行入口不稳定，新成员无法按 `personal-assistant-e2e/AGENTS.md` 的命令
   信心十足地运行全量 E2E。
2. “什么该放 E2E、什么该放 Service/Client tests”没有工程化落地，后续 issue
   容易继续把 service-level tests 堆进 E2E。

---

## 当前进展

更新日期：2026-07-09

- 已将导致 `personal-assistant-e2e` collection 失败的 `FastAPI TestClient`
  类测试迁入 `personal-assistant-service/tests/integration/`。
- 已将 configuration、structured logging、Agent Bundle、bug-4 CWD import
  等 Service contract / regression 测试迁入 `personal-assistant-service/tests/`。
- 已将 E2E 目录重组为 `smoke/`、`browser/`、`full_stack/`、`manual/`。
- 已补充 pytest markers：`smoke`、`browser`、`full_stack`、`manual`。
- 已更新 `personal-assistant-e2e/AGENTS.md`、`README.md` 和 manual real-auth
  目录说明。
- 已验证 `personal-assistant-e2e` collection 通过；`uv run pytest -m smoke -q`
  结果为 16 passed，smoke 目录无 skip。
- 已新增 `.github/workflows/ci.yml`，PR / main push 会运行 Service lint/tests、
  Client test/build 和 E2E smoke。
- 已拆除 `personal-assistant-e2e/tests/full_stack/test_feature_1_1_web_chat.py`
  legacy mixed file：Service-only `/invocations` SSE / validation / multi-turn
  覆盖迁入 `personal-assistant-service/tests/integration/test_web_chat_invocations.py`；
  E2E full_stack 仅保留 Vite proxy + Service subprocess 的真实联调哨兵。
- 已清理 smoke 中长期 skip：旧 `/playground` regression 改为当前
  `/invocations/playground` route；valid non-streaming `/invocations` smoke 改为
  不越过 Agent/LLM 边界的 content negotiation 检查。
- 已修复 E2E subprocess fixture 在 Windows 上只停止父进程导致 `uvicorn` /
  Vite 子进程残留的问题，并让 Vite dev proxy 支持测试时通过
  `PA_SERVICE_PROXY_TARGET` 使用动态 Service 端口。
- 遗留：Service 全量 `ruff format --check .` 当前会命中既有格式化债务；本次 CI
  先启用稳定的 `ruff check .` 和 `pytest tests/`，全量 format gate 需单独 cleanup
  后再开启。

---

## 目标

建立清晰、可运行、可逐步进入 CI 的测试体系：

1. [x] `personal-assistant-e2e` 在干净环境中 `collect-only` 稳定通过。
2. [x] Service-only integration / contract tests 迁回 `personal-assistant-service/tests/`。
3. [x] E2E 目录按 `smoke / browser / full_stack / manual` 分层。
4. [x] pytest markers 与目录分层一致。
5. [x] CI 至少能稳定运行 Service tests、Client tests/build 和 E2E smoke。
6. [x] Manual real-auth 测试默认不进入 PR gate，但有明确 runbook / skip 策略。

---

## 范围

### Service tests

- [x] 盘点 `personal-assistant-e2e/tests/` 中只验证 Service 内部行为的测试。
- [x] 将以下类别迁移或拆分到 `personal-assistant-service/tests/`：
  - Inbound Identity header / session extraction。
  - `/invocations` sync / SSE route contract。
  - `FakeAgentHandler` 邮件对话中只验证 Service route 与 handler 参数的部分。
  - configuration / logging / agent bundle contract tests。
- [x] 迁移后使用 Service project 环境运行相关 tests。

### Client tests

- [ ] 确认 `personal-assistant-client/functions/*.test.js` 覆盖 Pages Function proxy
      的 header allowlist、callback context cookie、error handling。
- [ ] 确认 chat client / auth lifecycle 的 unit tests 保留在 Client。
- [ ] 避免把只调用 JS function 或只 render component 的测试放入 E2E。

### E2E tests

- [x] 调整目录结构：
  ```text
  personal-assistant-e2e/tests/
  ├── smoke/
  ├── browser/
  ├── full_stack/
  └── manual/
  ```
- [x] 增加 / 调整 pytest markers：
  - `smoke`
  - `browser`
  - `full_stack`
  - `manual`
  - `slow`
- [ ] 保留或补齐真正跨边界的 E2E：
  - [x] Vite dev proxy + Service subprocess `/invocations` full_stack。
  - Pages Functions local dev + Service subprocess `/invocations` streaming pass-through。
  - Playwright ChatPage happy path：mock auth state，发送消息，观察 UI 收到回复。
  - token expiry browser regression。
  - reset session browser regression。
- [x] manual real-auth tests 默认 skip，必须显式环境变量启用。

### CI/CD

- [x] 新增或更新 GitHub Actions，使 PR 至少运行：
  - Service lint + affected tests。
  - Client tests + build。
  - E2E smoke。
- [ ] main 或 deployment 后运行关键 browser E2E / production smoke。
- [ ] 不把 manual real-auth 放入默认 PR gate。

### Documentation

- [x] 更新 `personal-assistant-e2e/AGENTS.md` 和 README，说明新目录和 markers。
- [ ] 如迁移大量测试，更新相关 issue / architecture 链接。
- [ ] 保持 [`test-strategy.md`](../../../architecture/devops/test/test-strategy.md)
      是测试归属规则的 source of truth。

---

## 非目标

- 不在本 issue 引入真实 Microsoft 测试账号或 secrets。
- 不要求一次性补齐所有真实 OAuth full flow 自动化。
- 不改变产品行为、API contract 或部署拓扑。
- 不删除仍有价值的测试；迁移前应先确认其覆盖意图。
- 不把 manual real-auth 伪装成默认 CI 测试。

---

## Implementation Plan 建议

### Phase 0: 测试资产盘点

- [x] 列出当前 `personal-assistant-e2e/tests/` 每个文件的实际测试层级：
  Service integration、Client contract、browser、full_stack、manual。
- [x] 标注迁移目标目录和保留理由。
- [x] 确认哪些 tests 当前 collection 失败及其原因。

### Phase 1: 修复可运行性

- [x] 保证 `cd personal-assistant-e2e && uv run pytest --collect-only` 通过。
- [x] 避免 E2E project 隐式依赖 Service dev dependency；确需调用 Service internals 的
      测试应迁移到 Service project。
- [x] 更新 `pyproject.toml` markers。

### Phase 2: 迁移 service-level tests

- [x] 将 `TestClient + FakeAgentHandler` 的 Service route tests 迁入 Service tests。
- [x] 保留一小组 process-level smoke 在 E2E。
- [x] 迁移后确保 Service tests 和 E2E tests 都能独立运行。

### Phase 3: 重组 E2E

- [x] 建立 `smoke/`、`browser/`、`full_stack/`、`manual/`。
- [x] 将现有 Playwright tests 迁入 `browser/`。
- [x] 将 Vite dev proxy + Service subprocess tests 迁入 `full_stack/`。
- [ ] 将 Pages Functions local dev + Service subprocess tests 迁入 `full_stack/`。
- [ ] 将部署健康检查迁入 `smoke/`。

### Phase 4: CI 门禁

- [x] 新增 E2E smoke job。
- [ ] 明确 browser tests 的触发条件。
- [ ] 部署后 production smoke 保持轻量、低 flake。

---

## 验收标准

- [x] `personal-assistant-e2e` 全量 collection 通过。
- [x] `personal-assistant-e2e/tests/` 已按 smoke / browser / full_stack / manual 分层。
- [x] Service-only integration tests 不再长期留在 E2E 目录。
- [x] `uv run pytest -m smoke` 可稳定运行。
- [ ] `uv run pytest -m browser` 可按需运行，缺 Playwright browser 时清晰 skip。
- [ ] manual real-auth tests 默认 skip，启用条件和 required env vars 清晰。
- [x] PR CI 至少包含 E2E smoke。
- [x] 文档与 [`test-strategy.md`](../../../architecture/devops/test/test-strategy.md) 一致。

---

## 风险与注意事项

| 风险 | 等级 | 缓解 |
|------|------|------|
| 迁移测试时误删有效覆盖 | 中 | 先做 inventory，迁移前记录覆盖意图和新位置 |
| Browser E2E flake 影响 CI | 中 | PR 只跑 smoke；browser subset 放 main 或改动触发 |
| E2E 依赖端口冲突 | 中 | 使用动态端口；只有确需 Vite 固定 proxy 时才占用 8080 / 5173 |
| manual real-auth 泄露凭据 | 高 | 默认 skip；仅用 CI secrets / 本地 env；不记录 token、code、password |
| 工作量扩散 | 中 | 按 Phase 推进，先可运行性，再迁移，再补覆盖 |

---

## Four-Question Gate

| Question | Answer | 论证 |
|----------|:------:|------|
| Is it best practice? | Yes | 按系统边界和测试金字塔治理测试资产，降低 E2E flake 和维护成本。 |
| Is it industry standard? | Yes | PR 跑 unit / integration / smoke，browser 与 real-auth 分层触发，是现代 Web 应用常见 CI 模式。 |
| Is it conventional? | Yes | 目录名和 markers 直接表达测试成本、依赖和适用场景，新成员容易理解。 |
| Is it modern? | Yes | 使用 Playwright、local Pages Functions、mock 外部依赖和受控 real-auth，符合当前前后端分离与 OAuth 应用测试实践。 |

四个 gate 均为 **Yes**。

---

## 参考

| 文档 | 路径 |
|------|------|
| 测试分层与归属规范 | `personal-assistant-meta/architecture/devops/test/test-strategy.md` |
| E2E 目录说明 | `personal-assistant-e2e/AGENTS.md` |
| Service 测试说明 | `personal-assistant-service/AGENTS.md` |
| Client 测试说明 | `personal-assistant-client/AGENTS.md` |
| CI/CD 架构 | `personal-assistant-meta/architecture/devops/cicd.md` |

