# Email Tools Use Case

`email_tools.py` 提供 Microsoft 365 Outlook 邮件处理能力，是 Personal Assistant 当前最核心的 User Federation 场景之一。用户通过自然语言查询、搜索、阅读、发送和回复邮件；凭据由 AgentArts Identity 管理，Service 不保存 Microsoft Graph access token。

## Tool 列表

| Tool | 用户意图 | 外部 API | Identity Provider |
|---|---|---|---|
| `list_emails` | 查看收件箱、已发送、草稿箱或指定 folder 的邮件列表 | Microsoft Graph `/me/mailFolders/{folder}/messages` | `m365-email-provider` |
| `get_email` | 查看单封邮件详情、正文、收件人、抄送和附件摘要 | Microsoft Graph `/me/messages/{id}` | `m365-email-provider` |
| `search_emails` | 按关键词搜索邮件 | Microsoft Graph `/me/messages?$search=...` | `m365-email-provider` |
| `send_email` | 发送新邮件 | Microsoft Graph `/me/sendMail` | `m365-email-provider` |
| `reply_to_email` | 回复已有邮件 | Microsoft Graph `/me/messages/{id}/reply` | `m365-email-provider` |

## 典型 Use Case

### UC-Email-01：查看最近邮件

```text
用户：帮我看看最近 10 封收件箱邮件。
Agent：我需要访问你的 Microsoft 365 邮件。请点击授权卡片完成授权。
用户完成授权后重试。
Agent：最近 10 封邮件如下：...
```

Agent 调用 `list_emails(folder="inbox", limit=10)`，返回邮件主题、发件人、接收时间、是否已读、重要性和正文预览。

### UC-Email-02：查看邮件详情

```text
用户：打开刚才张三那封项目进度邮件。
Agent：这封邮件的主题是“项目进度同步”，正文摘要如下：...
```

Agent 先从列表或搜索结果中定位 `email_id`，再调用 `get_email(email_id=...)` 读取正文、收件人、抄送和附件摘要。

### UC-Email-03：搜索特定邮件

```text
用户：帮我找一下最近关于 demo 排期的邮件。
Agent：找到 3 封相关邮件：...
```

Agent 调用 `search_emails(query="demo 排期")`，通过 Microsoft Graph `$search` 搜索用户邮箱。

### UC-Email-04：发送新邮件

```text
用户：给李四发邮件，说今天下午 3 点开 demo 评审。
Agent：我将发送以下邮件：
收件人：李四
主题：Demo 评审安排
正文：李四你好，今天下午 3 点开 demo 评审。
是否确认发送？
用户：确认发送。
Agent：已发送。
```

`send_email` 是敏感写操作。当前实现依赖 Agent system prompt 中的 Guard 规则：Agent 必须先展示完整预览，用户明确确认后才调用 `send_email` 执行真实发送。

### UC-Email-05：回复邮件

```text
用户：帮我回复张三，说 demo 改到周五下午。
Agent：我会回复这封邮件：
正文：张三你好，demo 改到周五下午，具体时间我稍后同步。
是否确认发送？
用户：确认。
Agent：已回复。
```

Agent 应先用 `get_email` 获取上下文，再展示回复内容。用户确认后，调用 `reply_to_email(email_id=..., body=...)`。

## Agent Identity 能力映射

| 能力 | 在 Email Tools 中的使用 |
|---|---|
| OAuth2 User Federation | 所有 Email tools 通过 `@require_access_token(provider_name="m365-email-provider", auth_flow="USER_FEDERATION")` 获取用户委托 token |
| Token Vault | Microsoft Graph access token 由 AgentArts Identity 保存，不写入 Service 数据库、日志或浏览器 storage |
| AuthCard | 用户首次使用邮件功能且未授权时，`handle_auth_url` 通过 SSE custom stream 推送授权卡片 |
| Upfront Consent | 邮件领域统一使用 `Mail.Read`、`Mail.ReadWrite`、`Mail.Send`，避免读写工具切换时反复触发授权 |
| Runtime Guard | `send_email` 和 `reply_to_email` 需要用户明确确认后执行 |
| Workload Identity | 生产环境通过 Gateway 注入的 Workload Access Token 向 Identity Service 换取 Microsoft Graph token |

## Scope 策略

Email Tools 统一使用以下 Microsoft Graph scopes：

```text
https://graph.microsoft.com/Mail.Read
https://graph.microsoft.com/Mail.ReadWrite
https://graph.microsoft.com/Mail.Send
```

该策略是为了适配 AgentArts Identity Token Vault 的缓存模型：同一业务领域内保持一致 scope，避免读写工具之间出现重复授权或 token 覆盖。高风险写操作由 Runtime Guard 控制，而不是通过拆分 scope 处理。

## 安全边界

- Agent 不接触用户密码或 Microsoft refresh token。
- access token 只作为 tool 参数注入，不能写入日志或返回给 LLM 可见的业务响应。
- 邮件发送和回复必须先展示预览，再等待用户确认。
- 未授权时 tool 返回 `auth_required`，用户通过 AuthCard 完成授权后再重试。
