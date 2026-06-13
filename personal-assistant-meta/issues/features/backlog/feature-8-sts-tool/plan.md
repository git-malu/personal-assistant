# Feature 8 Plan: OBS STS Outbound Tool

## Summary

本次将 Feature 8 收敛为一个可验证的 OBS read-only outbound 场景：Agent 通过 AgentArts Identity SDK 的 `require_sts_token` 获取华为云 STS 临时凭据，再用 OBS SDK 查询用户指定 bucket 的对象列表、对象元数据和文本对象内容。

## Key Changes

- Service 新增 `app/tools/obs_tools.py`，提供 `list_obs_objects`、`get_obs_object_metadata`、`read_obs_text_object` 三个 deepagents 工具，并注册到 `AgentHandler`。
- 工具使用 `huaweicloud-sts-provider` 和 `personal-assistant-obs-session`，由 AgentArts Identity 注入 `sts_credentials`；凭据参数通过 `InjectedToolArg` 从 tool schema 隐藏。
- OBS SDK 使用 `esdk-obs-python` 的 `from obs import ObsClient`；`huaweicloudsdkobs` 不提供该导入路径，不用于本工具。
- v1 只开放 read-only 操作；文本读取默认最多 1 MiB，二进制对象返回清晰错误并建议改查 metadata。
- Infra 侧新增 IAM Agency / OBS read-only custom policy；AgentArts STS Credential Provider 通过 `personal-assistant-service/scripts/create_sts_provider.py` 用 Agency URN 创建。

## Interfaces

- 不新增 HTTP route；用户仍通过 `POST /invocations` 发起自然语言请求。
- Tool 返回 JSON：
  - object list: `bucket/key/size/last_modified/etag/storage_class`
  - metadata: `bucket/key/size/content_type/last_modified/etag/storage_class/metadata`
  - text read: metadata 字段 + `content/truncated/encoding/bytes_read`
- 环境变量：`OBS_ENDPOINT` 可覆盖默认 `https://obs.cn-southwest-2.myhuaweicloud.com`。

## Test Plan

- Unit tests mock `ObsClient`，覆盖 list、metadata、text read、二进制拒绝、错误转换、schema 隐藏 STS credentials。
- Agent tests 验证 `create_deep_agent` 注册 GitHub + OBS tools，prompt 包含 OBS read-only 能力。
- Service checks：`uv sync`、`uv run ruff check app tests`、`uv run pytest tests -q`。
- Infra checks：`tofu fmt -check`、`tofu validate`；有华为云凭据时执行 `tofu plan`。
- Manual E2E：授权 STS Provider 后输入“帮我看看 <bucket>/<prefix> 下有哪些文件”和“读取 <bucket>/<key>”，返回实时 OBS 摘要或文本内容。

## Assumptions

- v1 允许用户指定任意 bucket，访问边界由 IAM Agency 的 OBS read-only custom policy 控制。
- Region 默认 `cn-southwest-2`。
- 不实现写入、删除、上传、复制、签名 URL 或二进制下载。
