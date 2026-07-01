# HuaweiCloud IAM Tools Use Case

`iam_tools.py` 提供华为云 IAM 用户只读查询能力。该 tool 不使用 OAuth2 User Federation，而是通过 AgentArts Identity 的 STS Credential Provider 获取短期云凭证，再调用 Huawei Cloud IAM SDK。

## Tool 列表

| Tool | 用户意图 | 外部 API | Identity Provider |
|---|---|---|---|
| `huaweicloud_list_iam_users` | 查看华为云 IAM 用户 / 子用户列表 | Huawei Cloud IAM V5 `ListUsersV5` | `iam-users-readonly` |

## 典型 Use Case

### UC-IAM-01：列出 IAM 用户

```text
用户：帮我看一下华为云 IAM 子用户列表。
Agent：当前可见 IAM 用户如下：...
```

Agent 调用 `huaweicloud_list_iam_users`，返回用户 ID、用户名、启用状态、描述、是否 root user、创建时间和 URN。

### UC-IAM-02：分页查看 IAM 用户

```text
用户：列出前 20 个 IAM 用户。
Agent：以下是前 20 个 IAM 用户：...
```

Agent 使用 `limit` 和 `marker` 参数分页查询，响应中包含 `page_info.next_marker`。

### UC-IAM-03：按用户组过滤

```text
用户：帮我查看某个用户组下的 IAM 用户。
Agent：该用户组下的 IAM 用户如下：...
```

Agent 使用 `group_id` 参数调用 `huaweicloud_list_iam_users`。

## Agent Identity 能力映射

| 能力 | 在 IAM Tools 中的使用 |
|---|---|
| STS Credential Provider | `_list_iam_users` 使用 `@require_sts_token(provider_name="iam-users-readonly", agency_session_name=...)` |
| Temporary Credential | SDK 注入 `StsCredentials`，包含短期 `access_key_id`、`secret_access_key` 和 `security_token` |
| Least Privilege | Provider 语义是 `iam-users-readonly`，只用于 IAM 用户只读查询 |
| No Long-lived AK/SK | Service 代码和环境变量不保存长期 AK/SK |
| Workload Identity | Runtime 使用 Gateway 注入的 Workload Access Token 与 Identity Service 交换 STS 凭证 |

## 只读边界

当前 IAM Tool 仅支持：

- 列出 IAM 用户。
- 分页查询 IAM 用户。
- 按 group_id 查询 IAM 用户。

当前不支持：

- 创建、删除、禁用用户。
- 修改用户权限。
- 创建或管理 AK/SK。
- 修改 IAM policy 或 agency。

## 安全边界

- STS 凭证是短期凭证，不作为长期 secret 保存。
- Tool response 不返回 AK/SK/Token。
- Provider 应绑定只读权限，避免聊天请求触发云资源写操作。
- 如果后续新增写操作，必须另行引入 Guard 和更细的权限审计。
