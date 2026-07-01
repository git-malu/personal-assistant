# AgentArts Outbound OAuth2 Scope 设计规范

本文档记录了在使用 AgentArts/AWS AgentCore Identity Service 进行第三方资源访问（Outbound 3LO / User Federation）时，关于 OAuth2 Scope 声明粒度的架构决策与最佳实践。

## 1. 背景：渐进式授权 vs 统一授权

在集成如 Microsoft 365 这样具有复杂权限体系的第三方服务时，通常会遇到以下两种 Scope 声明策略：

1. **接口级细分声明（渐进式授权 / Progressive Consent）**：
   - 读操作工具（如 `list_emails`）仅声明 `Mail.Read`。
   - 写操作工具（如 `send_email`）声明 `Mail.Send`。
   - **理想预期**：用户按需授权，做到极致的最小权限。

2. **领域级统一声明（Upfront Consent）**：
   - 在整个功能领域（如 `Email` 模块）内部的所有工具上，统一声明一个包含所有必需权限的“超集”（例如 `["Mail.Read", "Mail.ReadWrite", "Mail.Send"]`）。

## 2. 核心挑战：AgentArts Token Vault 机制限制

虽然 Microsoft Entra ID 原生支持智能合并新旧 Scope（渐进式授权），但在引入 **AgentArts Identity Token Vault** 作为中间网关后，采用“接口级细分声明”会导致严重的用户体验灾难与凭据状态紊乱。

具体原因如下：

- **Cache Miss 导致频繁弹窗**：Token Vault 缓存 Access Token 的主键是 `(Provider Name, User ID)`，匹配维度包含请求的 `scopes`。当用户调用读工具生成一个 `Mail.Read` 的缓存后，若切换调用写工具（请求 `Mail.Send`），Vault 会判定为缓存未命中（Cache Miss），从而直接向前端下发新的 Auth URL，打断对话心流。
- **凭据覆盖（Token Overwrite）**：用户完成第二次授权后，新获取的 Token 会直接覆盖 Vault 中的旧 Token。如果未来某个时刻由 `Mail.Read` 触发了 Token 刷新或重新授权，新存入的 Token 可能又会降级失去写权限，从而引发**授权死循环**。

## 3. 架构决策与最佳实践

基于 AgentCore/AgentArts 底层架构的设计哲学，本项目确立以下 Outbound OAuth2 最佳实践：

### 3.1 按业务领域拆分 Provider，领域内共享统一 Scopes
不要按读写操作拆分 Credential Provider，而应该按**功能领域（Domain）**拆分。
- 例如：`Email` 是一个独立的 Provider（包含邮件读写发），`Calendar` 是另一个独立的 Provider（仅包含日历读）。
- 在同一个 Domain 下的所有 Tool 源码中（如 `email_tools.py`），必须在 `@require_access_token` 装饰器中使用**完全相同**的 `scopes` 列表常量。

**示例：**
```python
EMAIL_OAUTH_SCOPES = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Mail.Send",
]

@require_access_token(
    provider_name="m365-provider-common",
    scopes=EMAIL_OAUTH_SCOPES, # 所有工具严格保持一致
    auth_flow="USER_FEDERATION",
    ...
)
```

### 3.2 权限控制上移：依赖 Guardrail 而非 Identity
既然为了架构妥协向用户超额申请了 `Mail.Send` 权限，系统应当如何在不打断连贯对话的前提下，保障高危操作的安全性？

**解决方案：将防御机制从 Identity 层面移到 Agent Runtime（应用层）层面。**
- **Token 允许发送，但 Agent 会拦截。** 在 LangGraph 编排层或 Tool Node 逻辑中，对于 `send_email` 等高危写操作工具，增加运行时 Guardrail（如发送前的二次用户确认机制）。
- 只有在用户于前端界面点击了“确认发送”按钮后，Tool 才会真正带着这个“万能” Access Token 调用 Graph API 执行发送动作。

## 4. 总结
在 AgentArts 架构下，**不要试图通过微调 Scope 列表来实现细粒度的安全管控**。应当在 Provider 级别采用 **Upfront Consent (超额统一声明)**，并在 Agent 业务逻辑层通过**运行态审批 (Guard)** 机制来防范高危操作。
