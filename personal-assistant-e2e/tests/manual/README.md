# Manual Real-Auth Tests

本目录预留给真实账号、真实 OAuth、真实云环境相关的 E2E 验证。

默认规则：

- 不提交账号、密码、token、OAuth code 或任何 secret。
- 不进入默认 `uv run pytest` / PR gate。
- 测试必须使用 `@pytest.mark.manual`，并通过显式环境变量启用。
- 优先把可自动化且不需要真实账号的覆盖放入 `smoke/`、`browser/` 或 `full_stack/`。
