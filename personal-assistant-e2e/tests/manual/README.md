# Manual Real-Auth Tests

本目录预留给真实账号、真实 OAuth、真实云环境相关的 E2E 验证。

默认规则：

- 不提交账号、密码、token、OAuth code 或任何 secret。
- 不进入默认 `uv run pytest` / PR gate。
- 测试必须使用 `@pytest.mark.manual`，并通过显式环境变量启用。
- 优先把可自动化且不需要真实账号的覆盖放入 `smoke/`、`browser/` 或 `full_stack/`。

## Feature 14 Gateway G1 Probe

```bash
set PA_E2E_DEPLOYED_BASE_URL=https://agentarts-personal-assistant.pages.dev
set PA_E2E_BEARER_TOKEN=<entra-id-token>
uv run pytest -m manual tests/manual/test_feature_14_gateway_probe.py -vv
```

该 probe 验证 deployed Pages/Gateway 的 Conversation GET/POST/PATCH/DELETE、Runtime Cookie、
同一 HTTPS Cookie 的连续复用、caller Session/User header 无法影响浏览器侧 resolver，以及
archived Invocation 的稳定 409。它不会执行模型，也不暴露 Runtime 内部 routing key。

Gateway 实际收到 resolver Session header、Runtime instance 回收后复用同一 ID、真实 OAuth
complete 和 warm-up p50/p95 仍需要部署侧日志或人工/测量流程，不能由这个黑盒 probe 或
本地 deterministic Agent 代替。
