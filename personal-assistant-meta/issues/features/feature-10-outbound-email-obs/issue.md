---
status: backlog
parent: feature-10-outbound-email-obs
split_from: Feature 10 拆分 — 本 issue 仅覆盖邮件部分，OBS 部分见 Feature 10b（待 Feature 8 完成后创建）
---

# Feature 10a: Outbound Email — Microsoft 365 邮件处理

本 Phase 使用 AgentArts Python SDK 实现 Microsoft 邮件处理（User Federation 模式），补齐系统最核心的邮件 Agent 能力。用户通过自然语言对话即可查询 Outlook 邮件、草拟和发送回复。

---

## 背景

Personal Assistant 已完成 Feature 4（Inbound Identity — Microsoft Entra ID OAuth），建立了用户身份认证体系。本 Phase 在此基础上扩展 Outbound 能力：

- **邮件处理**：用户通过对话查询 Outlook 邮件、草拟和发送回复，让 Personal Assistant 成为真正的邮件 Agent
- **基础设施奠基**：引入 `agentarts-sdk` Python 包、建立 `app/tools/` 工具目录和 LangGraph ToolNode 注册模式，为后续 Outbound 工具（OBS、Calendar 等）铺路

底层复用 Feature 4（Inbound Identity）的 OAuth2 基础设施，依赖 Feature 1 的 Agent 骨架和 Web Chat。

## 范围

### Microsoft 邮件处理（User Federation）

- AgentArts Identity 创建 `m365-provider` OAuth2 Credential Provider
- `app/tools/email_tools.py` — Microsoft Graph API 邮件工具函数
  - `list_emails(folder, limit, access_token)` — 列出收件箱/指定文件夹邮件
  - `get_email(email_id, access_token)` — 获取单封邮件详情（正文、附件列表）
  - `send_email(to, subject, body, cc, attachments, access_token)` — 发送邮件（需 Guard 二次确认）
  - `reply_to_email(email_id, body, access_token)` — 直接回复邮件
  - `search_emails(query, access_token)` — 按关键词搜索邮件
- 工具注册到 LangGraph ToolNode，更新 system prompt
- 敏感操作 Guard：发送邮件→用户确认

### 基础设施（本 Feature Scope 内）

- `agentarts-sdk` 添加到 `pyproject.toml` 依赖
- `app/tools/__init__.py` — 工具目录初始化
- LangGraph ToolNode 工具注册模式建立
- AgentArts Identity SDK 凭证注入基础设施（`@require_access_token` 装饰器集成）

## 不涉及

- OBS 文件查询与读取（后续 Feature 10b）
- OfficeClaw / 飞书渠道适配（渠道无关，Agent 层复用）
- 邮件附件上传/下载（后续可扩展）
- Calendar 工具（后续可扩展）
- STS Provider / `@require_sts_token`（Feature 8 后续实现）

## 任务拆解

### 10a.1 基础设施准备

- [ ] `pyproject.toml` 添加 `agentarts-sdk` 依赖
- [ ] `app/tools/__init__.py` — 创建工具目录
- [ ] `app/handlers/agent_handler.py` — 引入 LangGraph ToolNode，支持动态工具注册
- [ ] 验证 `@require_access_token` 装饰器在当前代码库中的集成路径

### 10a.2 Microsoft 365 OAuth2 Provider

- [ ] Azure Portal → Microsoft Entra ID → 应用注册（或复用 Feature 4 的 App Registration）
  - 添加 Microsoft Graph API 权限：`Mail.Read`, `Mail.Send`
  - 获取 client_id / client_secret
- [ ] 通过 AgentArts Python SDK 创建 `m365-provider` OAuth2 Credential Provider
  ```python
  from agentarts.sdk import IdentityClient
  from agentarts.sdk.identity.types import OAuth2Vendor

  client = IdentityClient(region="cn-southwest-2")
  client.create_oauth2_credential_provider(
      name="m365-provider",
      vendor=OAuth2Vendor.MICROSOFTOAUTH2,
      client_id="<azure-app-client-id>",
      client_secret="<azure-app-client-secret>",
      tenant_id="<azure-tenant-id>",  # Microsoft OAuth2 必须提供 tenant_id
  )
  ```

### 10a.3 邮件工具实现

- [ ] `app/tools/email_tools.py`
  - 所有函数用 `@require_access_token` 装饰，token 自动注入到 `access_token` 参数
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
  - 读操作 scopes：`Mail.Read`；写操作 scopes：`Mail.Send`
- [ ] `list_emails` — 邮件列表（支持 folder、limit、$filter）
- [ ] `get_email` — 邮件详情（正文、发件人、收件人、附件列表）
- [ ] `search_emails` — 关键词搜索（Graph API `$search`）
- [ ] `send_email` — 发送邮件（写操作 + Guard 二次确认）
- [ ] `reply_to_email` — 直接回复邮件（返回回复预览，由 Agent 展示给用户）
- [ ] 单元测试：mock Graph API response

### 10a.4 工具注册与 System Prompt

- [ ] LangGraph ToolNode 注册 `list_emails`, `get_email`, `send_email`, `reply_to_email`, `search_emails`
- [ ] 更新 system prompt，新增邮件能力描述（Agent 知道何时/如何使用邮件工具）
- [ ] Guard 机制：`send_email` 标记为需要用户确认的写操作

### 10a.5 E2E 验证

- [ ] Web Chat：用户对话 "帮我看看收件箱" → Agent 返回邮件列表
- [ ] Web Chat：用户对话 "帮我查一下最近关于项目进度的邮件" → Agent 搜索并返回
- [ ] Web Chat：用户对话 "帮我回张三的邮件，说收到" → Agent 展示回复预览，用户确认后发送
- [ ] 写操作 Guard：发送邮件 → 弹出确认 → 用户确认后执行
- [ ] 跨 Session：第二次对话直接查邮件，无需重新授权

## 依赖

- Feature 1（Agent 骨架 + Web Chat）✅ — 已完成
- Feature 4（Inbound Identity — Microsoft Entra ID OAuth）✅ — 已完成
- Feature 1.2（PostgreSQL）— 可选，`tool_configs` 表如有则可复用，无则本 Phase 内不依赖
- Feature 2（Memory）— 可选，跨 Session Memory 如有则可复用，无则本 Phase 内不依赖

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
  from agentarts.sdk.identity.types import OAuth2Vendor, StsCredentials
  ```
- Microsoft Graph API: [List messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages)
