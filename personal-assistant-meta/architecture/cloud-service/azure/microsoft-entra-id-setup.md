# DevOps — Microsoft Entra ID (OIDC) 配置指南

> 版本：v1.0 | 状态：Active | 关联文档：[`overall_architecture.md`](../overall_architecture.md), [`local-development.md`](local-development.md)

---

本指南详细说明了如何配置 **Microsoft Entra ID (原 Azure Active Directory)** 作为 Personal Assistant 的 Inbound/Outbound OIDC Identity Provider。

## 1. 门户入口

Microsoft 提供的 OAuth 2.0 / OIDC 应用注册界面统一收拢在 **Microsoft Entra** 体系中。开发人员可通过以下两个门户进行管理：

*   **官方推荐：Microsoft Entra 管理中心 (Entra Admin Center)**
    *   **访问地址**：[https://entra.microsoft.com/](https://entra.microsoft.com/)
    *   **登录账户**：使用您的 Microsoft 企业/学校账户或个人账户登录。
*   **备选入口：Azure Portal (传统 Azure 门户)**
    *   **访问地址**：[https://portal.azure.com/](https://portal.azure.com/)

---

## 2. 应用注册步骤 (App Registration)

### 2.1 路径导航
1. 登录 **Microsoft Entra 管理中心**。
2. 在左侧菜单栏中展开 **Identity**（标识）分类。
3. 点击 **Applications**（应用程序）-> **App registrations**（应用注册）。
4. 点击顶部菜单栏的 **New registration**（新注册）按钮。

### 2.2 基础信息配置
进入注册表单后，按以下参数配置：

*   **Name (名称)**: `personal-assistant-dev` (或根据部署环境命名)
*   **Supported account types (支持的账户类型)**:
    *   选择第三项：`Accounts in any organizational directory and personal Microsoft accounts`（即 **多租户 + 个人 Microsoft 账户**），允许任何人使用其微软个人/企业账号登录该 Agent。
*   **Redirect URI (重定向 URI)**:
    *   下拉框平台选择：**Web**（对应后端 FastAPI 处理 OIDC 回调流）。
    *   URL 填写：本地开发填 `http://localhost:8080/auth/callback`，生产部署填后端实际网关或代理的回调地址。
*   点击底部的 **Register**（注册）按钮完成创建。

---

## 3. 密钥与权限配置

注册完成后，进入该应用的详情页面。

### 3.1 客户端密码 (Client Secret)
对于后端的 Authorization Code Flow，需要生成密钥用于向 Microsoft 换取 `id_token`/`access_token`：
1. 点击左侧导航栏的 **Certificates & secrets**（证书和密码）。
2. 在 **Client secrets** 页签下，点击 **New client secret**（新建客户端密码）。
3. 填写 **Description**（例如 `pa-backend-dev-secret`）及 **Expires**（有效期建议选择 180 天），点击 **Add**。
4. **【强制安全要求】**：创建成功后，请立即复制其 **Value (值)** 并保存。离开此页面后该值将被永久隐藏，若丢失需重新生成。

### 3.2 API 权限 (API Permissions)
确保 OIDC 流程能正常获取用户标识和基础属性（如邮箱）：
1. 点击左侧导航栏的 **API permissions**（API 权限）。
2. 确保已默认添加 **Microsoft Graph** -> **User.Read** 权限。
3. 如果尚未添加，点击 **Add a permission** -> 选择 **Microsoft Graph** -> **Delegated permissions**，搜索并勾选 `openid`, `profile`, `email` 权限并保存。

---

## 4. 关键环境变量与 OIDC 端点

配置完成后，请从 **Overview (概述)** 页面中提取以下核心配置并写入项目 `.env` 配置文件：

### 4.1 核心配置字段对照表

| 配置项 | 平台显示名称 | 说明 | 示例值 |
|--------|--------------|------|--------|
| `MICROSOFT_CLIENT_ID` | Application (client) ID | 标识此应用的唯一 ID | `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `MICROSOFT_CLIENT_SECRET` | Secret Value | Step 3.1 生成的客户端密码 | `_xx~xxxxxxxxxxxxxxxxxxxxxxxxx` |
| `MICROSOFT_TENANT_ID` | Directory (tenant) ID | 多租户架构下可直接填写 `common` | `common` |

### 4.2 OIDC Discovery 端点
本系统通过 Microsoft 标准 OIDC 元数据发现端点获取公钥集和验证 URL：

```http
https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration
```

> **网络说明**：`login.microsoftonline.com` 在国内网络（包括华为内网）无任何 GFW 阻断，请求解析极为稳定。

---

## 5. 本地开发集成验证

1. 确保在后端 `personal-assistant-service/.env` 中正确配置了上述环境变量。
2. 运行 `uvicorn app.main:app --port 8080 --reload` 启动本地后端。
3. 引导用户访问前端 Web Chat，点击 **Sign in with Microsoft**。
3. 浏览器重定向至 Microsoft 登录页面，登录成功后，微软会将 `code` 返回至回调端点 `http://localhost:8080/auth/callback`，后端校验无误后颁发 JWT，建立安全 Session。

---

## 6. 常见错误排查 (Troubleshooting)

### 6.1 错误提示："The ability to create applications outside of a directory has been deprecated..."
**问题原因**：
微软已弃用“无目录（Directory-less）”的应用注册。如果您使用的是普通的个人微软账号（如 `@outlook.com`、`@hotmail.com`），默认情况下您不属于任何企业目录（Tenant），因此微软会限制您直接注册应用。

**第一推荐（极速绕过：在 Azure 中手动创建免费 Directory/Tenant）**：
由于微软自 2024 年起收紧了 M365 Developer E5 的申请门槛（个人新账号常提示 *“You don't currently qualify...”*），**在 Azure 中直接创建免费租户是目前最通用、最简单的解决手段**。
1. 登录 [Azure 门户](https://portal.azure.com/)（使用您的个人账号如 `windy005@outlook.com` 即可）。
2. 在上方搜索栏输入 **Microsoft Entra ID**（或 Azure Active Directory）并点击进入。
3. 在左侧菜单栏或顶部点击 **Manage tenants**（管理租户）-> 点击 **Create**（创建）。
4. 选择 **Microsoft Entra ID**，点击下一步（Next: Configuration）。
5. 配置以下基本信息：
   *   **Organization name**（组织名称）：例如 `Windy PA Dev`。
   *   **Initial domain name**（初始域名）：例如 `windypadev`（系统会自动生成 `windypadev.onmicrosoft.com`，这不要求您拥有真实域名）。
   *   **Country or region**（国家或地区）：选择您的所在地。
6. 点击 **Review + create** 并点击 **Create**。完成人机验证码校验，等待 1 分钟左右创建完毕。
7. **切换目录**：创建完成后，点击 Azure 门户右上角您的头像 -> 点击 **Switch directory**（切换目录），切换到您刚刚创建的 `Windy PA Dev` 租户下。
8. **注册应用**：此时，再次进入 [Microsoft Entra 管理中心](https://entra.microsoft.com/)，在 **App registrations**（应用注册）中点击 **New registration**，即可正常创建您的 OIDC 应用！

**备选方案（如果您拥有 Visual Studio / Partner 订阅）**：
如果您有付费的 Visual Studio 订阅，可以通过 [Microsoft 365 开发者计划](https://developer.microsoft.com/microsoft-365/dev-program) 申请免费的 E5 开发人员沙盒（此时您的个人账号即可自动 qualify）。

---

### 6.2 模拟与重置用户登录授权状态（测试场景专用）

在开发和集成 OIDC 登录时，测试人员和开发人员经常需要**扮演新用户**、**重置首次登录授权页面（Consent Screen）** 或 **测试 Token 过期/会话失效的异常流**。以下是针对不同测试需求的重置手段：

#### 1) 彻底重置：让用户重新展示首次“同意授权证书 (Consent Screen)”
一旦用户首次登录并点击了“同意读取邮箱和头像”，后续登录将不再展示此同意页面。
*   **方法一（代码层控制 - 推荐）**：前端调用 MSAL 登录时，配置 `prompt: "consent"` 参数，强制微软每次登录时都弹出该授权确认页。
    ```typescript
    msalInstance.loginPopup({
      scopes: ["openid", "profile", "user.read"],
      prompt: "consent"
    });
    ```
*   **方法二（用户侧撤销）**：测试用户登录 [微软应用管理中心](https://myapplications.microsoft.com/)，找到对应的应用 -> 点击 **Manage your application** -> 点击 **Revoke permissions**（撤销权限）进行彻底重置。

#### 2) 全局吊销：模拟用户被强制下线/会话被撤销
当需要测试“用户在其他设备被强制登出，或会话过期后，前端能否正确捕获 401 并自动跳转回登录页”的安全机制时，可在 Azure 控制台进行全局吊销：
*   **操作路径**：
    1. 登录 [Azure 门户](https://portal.azure.com/)。
    2. 进入 **Microsoft Entra ID** -> 选择左侧的 **Users**（用户）。
    3. 点击进入当前正在测试的外部或内部用户账号（如 `MA Lu`）。
    4. 在用户详情页顶部的工具栏中，点击带有禁用图标的 **Revoke sessions**（吊销会话）按钮。
*   **原理解析**：
    点击后，微软将在云端瞬间吊销该用户所有的 **Refresh Token (刷新令牌)** 和 SSO Cookie。此时：
    *   前端静默刷新 Token（即 `acquireTokenSilent()`）会**立刻失败**。
    *   **【避坑注意】**：由于已颁发的 **Access Token / ID Token** 属于短期无状态 JWT（通常有 1 小时有效期），若前端本地缓存未被清除，在这 1 小时内通过 Gateway 验签依然会成功。因此要完成**瞬间失效**测试，通常需要配合**清除浏览器 SessionStorage / LocalStorage**，或直接使用**无痕模式浏览器**。

### 6.3 错误提示："xxxx@qq.com from identity provider 'live.com' does not exist in tenant 'default directory'..."
**问题原因**：
当其他外部用户（如 QQ 邮箱、其他未注册在您当前 Directory 中的微软账号）尝试登录您的应用时，报错提示该账号在您的“默认租户”中不存在，必须先被添加为外部用户（Guest）。这通常是因为以下两种架构意图冲突：

#### 场景 A：您的意图是做【私有助手】（仅限您和您指定的测试人员登录）—— 推荐 🌟
如果您不希望任何陌生人都能登录您的应用、消耗您的 MaaS/DeepSeek 接口额度，那么保持“单租户/受控授权”是正确的。
*   **解决方法（手动拉入 Guest）**：
    1. 登录 [Azure 门户](https://portal.azure.com/) -> 选择 **Microsoft Entra ID**。
    2. 点击左侧 **Users**（用户） -> 点击顶部的 **New user** -> 选择 **Invite external user**（邀请外部用户）。
    3. 填入对方的邮箱（如 `xxxx@qq.com`），并发送邀请。
    4. 对方会收到一封微软发来的激活邮件，点击接受（Accept）后，即可顺利登录您的应用！

#### 场景 B：您的意图是做【公共应用】（任何拥有微软账号的人都能自由登录）
如果您希望它像一个公共 SaaS 一样，不需要您手动邀请任何用户：
*   **检查一：核对 App 注册时的“支持账户类型”**：
    *   在 Entra 门户进入您的应用 -> 点击左侧 **Authentication**（身份验证）。
    *   确保 **Supported account types**（支持的账户类型）选择的是：`Accounts in any organizational directory and personal Microsoft accounts`（多租户 + 个人账户）。如果是单租户，需在此处修改。
*   **检查二：前端 Authority 终结点配置（最易踩坑！）**：
    *   在您的前端 React / MSAL 初始化代码中，检查 `authority` 参数。
    *   ❌ 如果写的是 `https://login.microsoftonline.com/{您的Tenant_ID}`，那么微软会将其作为**单租户**验签，外部用户依然无法登录。
    *   ✅ 必须将 `authority` 更改为微软公共终结点：`https://login.microsoftonline.com/common`（或者 `https://login.microsoftonline.com/consumers` 仅限个人账号）。




