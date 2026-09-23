# AgentCore Identity — 3LO OAuth 最佳实践

> 来源：[Implementing User Delegated Authorization (3LO) with Amazon Bedrock AgentCore Identity to Access Google Drive](https://dev.classmethod.jp/en/articles/amazon-bedrock-agentcore-identity-3lo-google-drive/)（Classmethod DevelopersIO, 2026-01-14）
> 参考实现：[AWS 官方 Samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/01-tutorials/03-AgentCore-identity/05-Outbound_Auth_3lo)

---

## 1. 核心组件

AgentCore Identity 的 3LO（Three-Legged OAuth）流程涉及三个核心组件：

| 组件 | 角色 | 类比 |
|------|------|------|
| **Workload Identity** | Agent 的身份标识，部署时自动创建 | Agent 的身份证 |
| **Token Vault** | 安全存储用户的外部服务 Access Token | 保险库 |
| **Credential Provider** | 外部服务（如 Google）的连接配置注册处 | 连接方式登记簿 |

### 1.1 Workload Identity

- 部署 Agent 到 Runtime 时**自动创建**
- 包含：ID、ARN、`allowedResourceOauth2ReturnUrls`（OAuth 回调 URL 白名单）
- Agent 通过 Workload Identity 换取 **Workload Access Token**，再凭此访问 Token Vault
- 本地环境：首次运行时创建，存储在 `.agentcore.json`；后续复用
- Runtime 环境：部署时自动关联

```python
# SDK 内部调用的 API
dp_client.get_workload_access_token_for_jwt(workloadName, userToken)   # JWT 模式
dp_client.get_workload_access_token_for_user_id(workloadName, userId)  # user_id 模式
```

### 1.2 Token Vault

- 按 `user_id × agent × Provider` 三元组区分存储 Token
- Agent 不直接持有 Token；通过 `@requires_access_token` 装饰器自动按需检索
- 使用 Workload Access Token 鉴权访问

```python
@requires_access_token(
    provider_name="my-google-provider",
    scopes=["https://www.googleapis.com/auth/drive.metadata.readonly"],
    auth_flow="USER_FEDERATION",
    callback_url="http://localhost:9090/callback",
)
async def access_google_drive(*, access_token: str) -> dict:
    ...
```

### 1.3 Credential Provider

注册外部 OAuth 服务的连接信息：

| 字段 | 说明 |
|------|------|
| Name | Provider 标识名（如 `google-drive-provider`） |
| Client ID | Google OAuth client ID |
| Client Secret | Google OAuth client secret |
| Discovery URL | OpenID Connect 配置 URL |
| Scopes | 资源访问范围 |

创建后将返回的 **Callback URL** 注册到 Google Cloud Console 的 Authorized Redirect URIs。

---

## 2. 3LO 流程（4 阶段）

```
Phase 1: 首次调用 → 获取认证 URL
    User → Agent (invoke with JWT)
      → AgentCore Identity (换取 Workload Access Token)
      → Token Vault (查无 Token)
      → Identity (生成 OAuth 认证 URL)
      → 返回 auth_url 给 User

Phase 2: 浏览器认证
    User → Google OAuth (浏览器认证)
      → Google 回调到 Identity (authorization code)
      → Identity 用 code 换 access_token + refresh_token
      → Identity 重定向到 Callback Server (?session_id=xxx)

Phase 3: Session Binding
    Callback Server → Identity.complete_resource_token_auth(session_id, JWT)
      → Identity 验证 JWT 的 sub 与 session 的 sub 一致
      → Token Vault 保存 token
      → 返回成功页面

Phase 4: 再次调用（已持有 Token）
    User → Agent (invoke with same JWT)
      → Token Vault 查到 Access Token
      → Agent 直接调用 Google Drive API
```

---

## 3. Session Binding — 关键步骤

3LO 流程中浏览器认证与 Agent 执行发生在**不同上下文**，必须通过 **Session Binding** 将两者关联：

```python
from bedrock_agentcore.services.identity import IdentityClient, UserTokenIdentifier

identity_client = IdentityClient(region="us-west-2")

identity_client.complete_resource_token_auth(
    session_uri=session_id,
    user_identifier=UserTokenIdentifier(user_token=cognito_access_token)
)
```

**`session_id` 从回调 URL 的 query string 中获取。如果 Session Binding 失败，Token 不会被保存到 Vault。**

---

## 4. 踩坑记录

### 4.1 必须使用 `BedrockAgentCoreApp`

❌ 错误：定义独立函数

```python
async def main():
    result = await access_google_drive(access_token="")
```

✅ 正确：使用 `BedrockAgentCoreApp`

```python
app = BedrockAgentCoreApp()

@app.entrypoint
async def agent_invocation(payload):
    ...
```

否则 SDK 会创建独立的 Workload Identity，导致 Callback Server 中 JWT 验证时 user_id 不匹配。

### 4.2 Workload Identity 的 Callback URL 安全策略

```python
# 空列表 = 所有 URL 都允许（开发便利，不安全）
allowed_resource_oauth_2_return_urls=[]

# 显式设置后，只有列表中的 URL 被允许
allowed_resource_oauth_2_return_urls=["http://localhost:9090/callback"]
```

**一旦显式设置了任何值，未列出的 URL 全部被拒绝。** 生产环境必须显式配置。

### 4.3 部署后更新 Workload Identity

Credential Provider 创建后才知道 Callback URL → 部署后再更新 Workload Identity：

```python
identity_client.update_workload_identity(
    name=agent_id,
    allowed_resource_oauth_2_return_urls=["http://localhost:9090/callback"],
)
```

---

## 5. 生产环境安全考量

| 风险 | 对策 |
|------|------|
| 认证 URL 泄露，攻击者绑定自己的 Token | 使用 Cookie 等仅合法用户浏览器持有的信息做二次验证 |
| Callback URL 未限制 | 显式配置 `allowedResourceOauth2ReturnUrls`，不要留空 |
| 手动配置步骤多、易出错 | 使用 IaC（Terraform/CDK）统一创建和配置 Workload Identity + Credential Provider + Runtime |
| Access Token 过期 | Token Vault 自动使用 Refresh Token 续期 |

---

## 6. 与 AgentArts Identity 对应关系

| AgentCore (AWS) | AgentArts (华为云) | 说明 |
|------------------|-------------------|------|
| Workload Identity | Agent Runtime Identity | Agent 的身份标识 |
| Token Vault | Identity Token Store | 外部服务 Token 的安全存储 |
| Credential Provider | m365-provider / 外部 OAuth Provider 配置 | 外部服务 OAuth 连接配置 |
| Session Binding (`complete_resource_token_auth`) | `handle_auth_url` + Poller 模式 | 关联浏览器认证与 Agent Session |
| `@requires_access_token` | `CheckOnlyPoller` + `get_stream_writer()` | 声明式 Token 需求，自动检索/触发认证 |
| Cognito User Pool | AgentArts IAM | 用户认证 |

> AgentArts 借鉴了 AgentCore 的 Identity 架构，核心概念一一对应。Personal Assistant 当前使用的 stream_mode + CheckOnlyPoller 模式本质上是 Session Binding 的变体实现。
