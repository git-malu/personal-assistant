# AgentArts Agent Identity 参考资料

本文档记录 AgentArts Agent Identity 能力的外部参考资料，便于后续实现
LLM credential provider、第三方服务凭据托管、用户委托等身份相关能力时查阅。

## 官方示例与文档

| 类型 | 位置 | 用途 |
|------|------|------|
| SDK 示例 | `https://github.com/huaweicloud/agentarts-sdk-python/tree/main/examples/agent_identity` | 查看 Agent Identity 的可运行示例、provider 配置方式与典型调用模式 |
| SDK 使用指南 | `https://github.com/huaweicloud/agentarts-sdk-python/blob/main/docs/cn/sdk_user_guide/agent_identity_guide.md` | 阅读 Agent Identity 的概念说明、API 使用方式和端到端配置流程 |

## 已知排障记录：service-created Workload Identity WAT 404

`agent-personal-assistant` 是 AgentArts / AgentNetwork 创建的 service-owned
Workload Identity：

```text
name: agent-personal-assistant
authorizer_type: CUSTOM_JWT
created_by: SERVICE service.AgentNetwork
```

它可以通过 Console、`list_workload_identities` 和 `get_workload_identity`
看到，但当前不能作为本地代码主动调用 `create_workload_access_token()` 的目标。

主动 mint WAT 时会返回：

```text
status_code: 404
error_code: AgentIdentityDirectoryService.1002
error_msg: workload identity not found
```

已排除 region、AK/SK、workload name、Microsoft Entra ID `aud` / `iss`、
JWKS `kid` 等问题。同一套凭据对 customer-owned `workload-*` identities
可以成功主动创建 basic WAT；对 `authorizer_type=NONE` workload 调用 JWT WAT
也会返回预期的 `400 AgentIdentityDirectoryService.2001 authorizer type mismatch`。
因此当前判断是：WAT exchange 后端不能解析
`created_by=SERVICE service.AgentNetwork` 的 workload identity。

不要把 `workload_name` 改成完整 URN。WAT exchange endpoint 的
`workload_name` 只接受短名称格式：

```text
^[a-zA-Z0-9_-]{1,56}$
```

推荐处理：为本地开发、非 Gateway 路径或手动 SDK 调试创建 customer-owned
`CUSTOM_JWT` Workload Identity，并配置相同 Microsoft Entra ID authorizer；
本地默认使用 `pa-local-jwt-workload`，也可将
`AGENT_IDENTITY_LOCAL_JWT_WORKLOAD_NAME` 指向其他 customer-owned workload。

已验证可工作的 local workload raw authorizer shape 是：

```text
custom_jwt:
  discovery_url: https://login.microsoftonline.com/2a1d3739-88c5-4314-b921-acbeac0abbfa/v2.0/.well-known/openid-configuration
  allowed_audience:
    - 3a99a511-926c-475c-b6bc-325a037f574d
```

注意：`allowed_clients`、`allowed_scopes`、`custom_claims` 为空时必须省略字段。
Agent Identity 后端不会把省略字段和显式空数组当成等价配置。对 Microsoft
Entra ID token，如果发送 `allowed_clients: []`，即使 token 的 `aud`、`iss`、
`ver` 都正确，JWT WAT exchange 仍会返回：

```text
status_code: 400
error_code: AgentIdentityDirectoryService.2007
error_msg: invalid JWT client ID
```

因此 helper 构造 `CustomJWTAuthorizerConfiguration` 时，optional list 为空必须传
`None`，不能传 `[]`。

Infra helper 提供该 local workload 的 read-only 检查和显式 bootstrap：

```bash
cd personal-assistant-infra
uv run python scripts/ensure_local_jwt_workload_identity.py
uv run python scripts/ensure_local_jwt_workload_identity.py --apply
```

Production Gateway 路径继续优先使用 Gateway 注入的
`X-HW-AgentGateway-Workload-Access-Token`，不依赖本地代码主动 mint WAT。

完整复现命令与实验记录见
[`architecture/devops/troubleshooting/agent-identity-service-created-workload-wat-404.md`](../../devops/troubleshooting/agent-identity-service-created-workload-wat-404.md)。

