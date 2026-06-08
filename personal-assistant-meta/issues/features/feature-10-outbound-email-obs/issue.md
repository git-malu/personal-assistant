---
status: backlog
---

# Feature 10: Outbound Email + OBS（AgentArts Python SDK）

本 Phase 使用 AgentArts Python SDK 实现两个 Outbound 场景：Microsoft 邮件处理（User Federation 模式）和华为云 OBS 文件查询与读取（STS 模式）。两个场景共享 AgentArts Identity SDK 的凭据管理基础设施，通过 `@require_access_token` / `@require_sts_token` 装饰器注入凭据。

---

## 背景

Personal Assistant 的 `@require_access_token` (User Federation) 和 `@require_sts_token` (STS) 装饰器模式已由 AgentArts Python SDK v0.1.3 提供标准支持。本 Phase 直接在这套基础设施上扩展两个高价值场景：

- **邮件处理**：用户通过对话查询 Outlook 邮件、草拟和发送回复，补齐系统最核心的邮件 Agent 能力
- **OBS 文件查询**：用户通过对话浏览和读取 OBS 对象存储中的文件内容，打通 Agent ↔ 云存储的"查看-理解"回路

本 Feature 自包含实现所有凭据管理——`m365-provider` 和 `huaweicloud-sts-provider` 均通过 AgentArts Python SDK 在 Step 1 中独立创建，不引入新的基础设施依赖。

## 范围

### 场景一：Microsoft 邮件处理（User Federation）

- AgentArts Identity 创建 `m365-provider` OAuth2 Credential Provider
- `app/tools/email_tools.py` — Microsoft Graph API 邮件工具函数
  - `list_emails(folder, limit, access_token)` — 列出收件箱/指定文件夹邮件
  - `get_email(email_id, access_token)` — 获取单封邮件详情（正文、附件列表）
  - `send_email(to, subject, body, cc, attachments, access_token)` — 发送邮件（需 Guard 二次确认）
  - `draft_reply(email_id, body, access_token)` — 草拟回复
  - `search_emails(query, access_token)` — 按关键词搜索邮件
- 工具注册到 LangGraph ToolNode，更新 system prompt
- 敏感操作 Guard：发送邮件→用户确认

### 场景二：华为云 OBS 文件查询与读取（STS）

- 本 Feature Step 1 中通过 AgentArts Python SDK 独立创建 `huaweicloud-sts-provider`（不依赖 Feature 8）
- `app/tools/obs_tools.py` — OBS 对象存储工具函数
  - `list_obs_objects(bucket, prefix, limit, sts_credentials)` — 列出 Bucket 内对象
  - `get_obs_object(bucket, key, sts_credentials)` — 读取对象内容（文本/JSON/CSV 等可读格式）
  - `get_obs_object_metadata(bucket, key, sts_credentials)` — 获取对象元数据（大小、类型、修改时间）
- 工具注册到 LangGraph ToolNode，更新 system prompt

## 不涉及

- OfficeClaw / 飞书渠道适配（渠道无关，Agent 层复用）
- OBS 文件写入/删除（只读场景，符合 MVP 最小权限原则）
- 邮件附件上传/下载（后续可扩展）
- Calendar 工具（后续可扩展）

## 任务拆解

### 10.1 Microsoft 365 OAuth2 Provider

- [ ] Azure Portal → Microsoft Entra ID → 应用注册（如已有 Feature 4 的 App Registration 可复用其 client_id/tenant_id，只需额外授予 Mail 权限）
  - 添加 Microsoft Graph API 权限：`Mail.Read`, `Mail.Send`, `Mail.ReadWrite`
  - 获取 client_id / client_secret
- [ ] 通过 AgentArts Python SDK 创建 `m365-provider` OAuth2 Credential Provider
  ```python
  from agentarts.sdk import IdentityClient
  from agentarts.sdk.identity import OAuth2Vendor

  client = IdentityClient(region="cn-southwest-2")
  client.create_oauth2_credential_provider(
      name="m365-provider",
      vendor=OAuth2Vendor.MICROSOFTOAUTH2,
      client_id="<azure-app-client-id>",
      client_secret="<azure-app-client-secret>",
      tenant_id="<azure-tenant-id>",  # Microsoft OAuth2 必须提供 tenant_id
  )
  ```

### 10.2 邮件工具实现

- [ ] `app/tools/email_tools.py`
  - 所有函数用 `@require_access_token` 装饰，token 自动注入到 `access_token` 参数（默认 `into="access_token"`）
  - Microsoft Graph API 基础 URL：`https://graph.microsoft.com/v1.0/me`
  - 使用 `httpx.AsyncClient` 调用 Graph API
  - 示例：
    ```python
    from agentarts.sdk import require_access_token
    import httpx

    @require_access_token(
        provider_name="m365-provider",
        scopes=["https://graph.microsoft.com/Mail.Read"],
        auth_flow="USER_FEDERATION",
    )
    async def list_emails(folder: str = "inbox", limit: int = 10, access_token: str | None = None):
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages?$top={limit}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            return resp.json()
    ```
  - 读操作 scopes：`Mail.Read`；写操作 scopes：`Mail.ReadWrite`, `Mail.Send`
- [ ] 邮件列表/详情/搜索（读操作）
- [ ] 邮件发送/草拟回复（写操作 + Guard）
- [ ] 单元测试：mock Graph API response

### 10.3 OBS 工具实现

- [ ] `app/tools/obs_tools.py`
  - 通过 Step 1 独立创建的 `huaweicloud-sts-provider`（自包含，不依赖 Feature 8）
  - `@require_sts_token(provider_name="huaweicloud-sts-provider", agency_session_name="personal-assistant-obs-session")`
  - 装饰器自动注入 `sts_credentials: StsCredentials`（含 `access_key_id`, `secret_access_key`, `security_token`, `expiration`）
  - 使用华为云 `obs` SDK（`ObsClient`）操作 OBS，通过 `sts_credentials` 初始化
  - 读取对象内容后自动检测文件类型，对文本/JSON/CSV 返回可读字符串
- [ ] OBS 对象列表/读取/元数据（读操作）
- [ ] 单元测试：mock OBS client response

### 10.4 工具注册与 System Prompt

- [ ] LangGraph ToolNode 注册 `list_emails`, `get_email`, `send_email`, `draft_reply`, `search_emails`
- [ ] LangGraph ToolNode 注册 `list_obs_objects`, `get_obs_object`, `get_obs_object_metadata`
- [ ] 更新 system prompt，新增邮件 + OBS 能力描述
- [ ] Guard：`send_email` 标记为需要用户确认的写操作

### 10.5 E2E 验证

- [ ] Web Chat：用户对话 "帮我看看收件箱" → Agent 返回邮件列表
- [ ] Web Chat：用户对话 "帮我查一下最近关于项目进度的邮件" → Agent 搜索并返回
- [ ] Web Chat：用户对话 "帮我回张三的邮件，说收到" → Agent 草拟回复内容，用户确认后发送
- [ ] Web Chat：用户对话 "my-bucket 里有哪些文件" → Agent 返回 OBS 对象列表
- [ ] Web Chat：用户对话 "帮我读一下 obs-report.json 的内容" → Agent 返回文件内容
- [ ] 写操作 Guard：发送邮件→弹出确认→用户确认后执行
- [ ] 跨 Session：第二次对话直接查邮件，无需重新授权

## 依赖

- Feature 1（Agent 骨架 + Web Chat）

> **自包含设计**：本 Feature 不依赖 Feature 2（Memory）— Guard 机制使用 Microsoft Graph Drafts 文件夹作为跨调用状态存储。不依赖 Feature 4（Inbound Identity）— 本地调试通过 Chainlit + 硬编码用户完成，生产环境通过 AgentArts Runtime 注入用户身份。不依赖 Feature 1.2（PostgreSQL）。不依赖 Feature 8（STS Tool）— `huaweicloud-sts-provider` 在本 Feature Step 1 中独立创建。

## 调试目标

- Chainlit 本地调试：`uv run chainlit run chainlit_app.py`，硬编码用户 `dev-user@personal-assistant.local`
- 邮件读写通过 DeviceCodeCredential 获取 token（需预先在 Azure Portal 注册应用）
- OBS 读取通过环境变量配置 AK/SK

## 参考

- AgentArts Python SDK（**v0.1.3**）：
  - PyPI：[pypi.org/project/agentarts-sdk](https://pypi.org/project/agentarts-sdk/)
  - 源码：`/Users/malu/Projects/github/agentarts-sdk-python`
  - Identity 装饰器：`src/agentarts/sdk/identity/auth.py`（`require_access_token` / `require_sts_token`）
  - Identity Client：`src/agentarts/sdk/service/identity/identity_client.py`
  - 类型定义：`src/agentarts/sdk/identity/types.py`（`OAuth2Vendor`, `StsCredentials`）
  - 工具集成示例：`examples/agent_tools/integrate_tools.py`
  - Identity 示例：`examples/agent_identity/`（oauth2 / api_key / sts_token / client_manual）
  - Memory + Agent 示例：`examples/memory_usage/agent_with_memory.py`
- SDK 导入：
  ```python
  from agentarts.sdk import IdentityClient, require_access_token, require_sts_token, require_api_key
  from agentarts.sdk.identity import OAuth2Vendor, StsCredentials
  ```
- Microsoft Graph API: [List messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages)
- 华为云 OBS Python SDK: [对象操作](https://support.huaweicloud.com/sdk-python-devg-obs/obs_22_0500.html)
