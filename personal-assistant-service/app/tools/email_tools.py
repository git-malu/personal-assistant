"""Microsoft Graph API 邮件工具函数。

提供 5 个异步邮件工具，通过双路径 auth 支持：
- Production: @require_access_token 装饰器注入 access_token
- Local Dev: DeviceCodeCredential fallback（当 access_token 为 None 时）

所有函数返回结构化 dict，错误信息包含在返回 dict 中，不抛出异常。
"""

import os

import httpx
from agentarts.sdk import require_access_token

# ---------------------------------------------------------------------------
# list_emails
# ---------------------------------------------------------------------------


@require_access_token(
    provider_name="m365-provider",
    scopes=["https://graph.microsoft.com/Mail.Read"],
    auth_flow="USER_FEDERATION",
)
async def list_emails(
    folder: str = "inbox", limit: int = 10, access_token: str | None = None
) -> dict:
    """列出指定文件夹的邮件。

    Args:
        folder: 邮件文件夹名称，默认 "inbox"。可选 "sentitems", "drafts" 等。
        limit: 返回数量上限，默认 10。
        access_token: Microsoft Graph API 访问令牌。Production 环境由装饰器注入，
                      Local Dev 传入 None 时自动 fallback 到 DeviceCodeCredential。

    Returns:
        dict: {"emails": [{"id", "subject", "from", ...}], ...}
              错误时返回 {"error": "...", "status_code": N}
    """
    if access_token is None:
        access_token = await _get_device_code_token()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "$top": limit,
                    "$select": (
                        "subject,from,receivedDateTime,isRead,"
                        "bodyPreview,conversationId"
                    ),
                },
            )
            if resp.status_code >= 400:
                return _graph_error(resp)

            data = resp.json()
            emails = []
            for msg in data.get("value", []):
                sender_info = _extract_sender(msg.get("from"))
                emails.append(
                    {
                        "id": msg.get("id"),
                        "subject": msg.get("subject"),
                        "from": sender_info,
                        "received": msg.get("receivedDateTime"),
                        "is_read": msg.get("isRead"),
                        "preview": _truncate_preview(msg.get("bodyPreview", "")),
                        "conversation_id": msg.get("conversationId"),
                    }
                )
            return {"emails": emails}

    except httpx.RequestError as e:
        return {"error": f"HTTP 请求失败: {str(e)}"}
    except Exception as e:
        return {"error": f"查询邮件失败: {str(e)}"}


# ---------------------------------------------------------------------------
# get_email
# ---------------------------------------------------------------------------


@require_access_token(
    provider_name="m365-provider",
    scopes=["https://graph.microsoft.com/Mail.Read"],
    auth_flow="USER_FEDERATION",
)
async def get_email(email_id: str, access_token: str | None = None) -> dict:
    """获取单封邮件的完整内容。

    Args:
        email_id: 邮件 ID（可从 list_emails 返回结果中获取）。
        access_token: Microsoft Graph API 访问令牌。Production 环境由装饰器注入，
                      Local Dev 传入 None 时自动 fallback 到 DeviceCodeCredential。

    Returns:
        dict: {"id", "subject", "from", "to", "cc", "body", ...}
              HTTP 错误时返回 {"error": "...", "status_code": N}
    """
    if access_token is None:
        access_token = await _get_device_code_token()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/me/messages/{email_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code >= 400:
                return _graph_error(resp)

            msg = resp.json()
            return {
                "id": msg.get("id"),
                "subject": msg.get("subject"),
                "from": _extract_sender(msg.get("from")),
                "to": _extract_recipients(msg.get("toRecipients", [])),
                "cc": _extract_recipients(msg.get("ccRecipients", [])),
                "body": _extract_body(msg.get("body", {})),
                "received": msg.get("receivedDateTime"),
                "conversation_id": msg.get("conversationId"),
                "attachments": msg.get("hasAttachments", False)
                and [
                    {
                        "name": att.get("name"),
                        "content_type": att.get("contentType"),
                        "size": att.get("size"),
                    }
                    for att in msg.get("attachments", [])
                ],
            }

    except httpx.RequestError as e:
        return {"error": f"HTTP 请求失败: {str(e)}"}
    except Exception as e:
        return {"error": f"获取邮件详情失败: {str(e)}"}


# ---------------------------------------------------------------------------
# search_emails
# ---------------------------------------------------------------------------


@require_access_token(
    provider_name="m365-provider",
    scopes=["https://graph.microsoft.com/Mail.Read"],
    auth_flow="USER_FEDERATION",
)
async def search_emails(query: str, access_token: str | None = None) -> dict:
    """按关键词搜索邮件。

    支持 Microsoft Graph API 的 KQL (Keyword Query Language) 语法，
    例如 "张三" 或 "subject:项目进度"。

    Args:
        query: 搜索关键词（KQL 语法）。
        access_token: Microsoft Graph API 访问令牌。Production 环境由装饰器注入，
                      Local Dev 传入 None 时自动 fallback 到 DeviceCodeCredential。

    Returns:
        dict: 同 list_emails 返回格式。无结果时 emails 列表为空。
    """
    if access_token is None:
        access_token = await _get_device_code_token()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "$search": query,
                    "$select": "subject,from,receivedDateTime,isRead,bodyPreview",
                },
            )
            if resp.status_code >= 400:
                return _graph_error(resp)

            data = resp.json()
            emails = []
            for msg in data.get("value", []):
                sender_info = _extract_sender(msg.get("from"))
                emails.append(
                    {
                        "id": msg.get("id"),
                        "subject": msg.get("subject"),
                        "from": sender_info,
                        "received": msg.get("receivedDateTime"),
                        "is_read": msg.get("isRead"),
                        "preview": _truncate_preview(msg.get("bodyPreview", "")),
                    }
                )
            return {"emails": emails}

    except httpx.RequestError as e:
        return {"error": f"HTTP 请求失败: {str(e)}"}
    except Exception as e:
        return {"error": f"搜索邮件失败: {str(e)}"}


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------


@require_access_token(
    provider_name="m365-provider",
    scopes=["https://graph.microsoft.com/Mail.Send"],
    auth_flow="USER_FEDERATION",
)
async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    access_token: str | None = None,
) -> dict:
    """发送邮件。⚠️ 此为敏感操作，需遵守 write operation Guard 规则。

    .. note:: 附件功能尚未实现，attachments 参数当前被忽略。

    Args:
        to: 收件人邮箱地址。
        subject: 邮件主题。
        body: 邮件正文（纯文本）。
        cc: 抄送邮箱地址（可选）。
        access_token: Microsoft Graph API 访问令牌。Production 环境由装饰器注入，
                      Local Dev 传入 None 时自动 fallback 到 DeviceCodeCredential。

    Returns:
        dict: 成功返回 {"sent": true}，失败返回 {"error": "...", "status_code": N}
    """
    if access_token is None:
        access_token = await _get_device_code_token()

    try:
        message = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [
                {"emailAddress": {"address": addr.strip()}}
                for addr in to.split(",")
                if addr.strip()
            ],
        }
        if cc:
            message["ccRecipients"] = [
                {"emailAddress": {"address": addr.strip()}}
                for addr in cc.split(",")
                if addr.strip()
            ]

        payload = {"message": message}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://graph.microsoft.com/v1.0/me/sendMail",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code >= 400:
                return _graph_error(resp)

            return {"sent": True}

    except httpx.RequestError as e:
        return {"error": f"HTTP 请求失败: {str(e)}"}
    except Exception as e:
        return {"error": f"发送邮件失败: {str(e)}"}


# ---------------------------------------------------------------------------
# draft_reply
# ---------------------------------------------------------------------------


@require_access_token(
    provider_name="m365-provider",
    scopes=["https://graph.microsoft.com/Mail.ReadWrite"],
    auth_flow="USER_FEDERATION",
)
async def draft_reply(
    email_id: str, body: str, access_token: str | None = None
) -> dict:
    """草拟对某封邮件的回复，只草拟不发送。

    调用 Microsoft Graph createReply API，回复会自动保存到 Drafts 文件夹。

    Args:
        email_id: 要回复的原邮件 ID。
        body: 回复正文（纯文本）。
        access_token: Microsoft Graph API 访问令牌。Production 环境由装饰器注入，
                      Local Dev 传入 None 时自动 fallback 到 DeviceCodeCredential。

    Returns:
        dict: {"draft": {"to", "subject", "body", "original_email_id",
               "conversation_id", "cc", "note"}}
              HTTP 错误时返回 {"error": "...", "status_code": N}
    """
    if access_token is None:
        access_token = await _get_device_code_token()

    try:
        payload = {
            "message": {
                "body": {"contentType": "Text", "content": body},
            }
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://graph.microsoft.com/v1.0/me/messages/{email_id}/createReply",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code >= 400:
                return _graph_error(resp)

            msg = resp.json()
            draft_body = _extract_body(msg.get("body", {}))
            return {
                "draft": {
                    "to": _extract_recipients(msg.get("toRecipients", [])),
                    "subject": msg.get("subject"),
                    "body": draft_body,
                    "original_email_id": email_id,
                    "conversation_id": msg.get("conversationId"),
                    "cc": [],
                    "note": "草稿已保存到 Drafts 文件夹",
                }
            }

    except httpx.RequestError as e:
        return {"error": f"HTTP 请求失败: {str(e)}"}
    except Exception as e:
        return {"error": f"创建草稿失败: {str(e)}"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_device_code_token() -> str:
    """Local Dev fallback: 使用 DeviceCodeCredential 获取 Graph API token。

    仅在 access_token 为 None 时调用（即未运行在 AgentArts Runtime 的本地调试场景）。
    """
    from azure.identity import DeviceCodeCredential

    credential = DeviceCodeCredential(
        tenant_id=os.environ.get("AZURE_TENANT_ID", ""),
        client_id=os.environ.get("AZURE_CLIENT_ID", ""),
    )
    token = credential.get_token("https://graph.microsoft.com/.default")
    return token.token


def _extract_sender(sender_obj: dict | None) -> str:
    """从 Graph API 的 from 字段提取发送者信息。"""
    if not sender_obj:
        return "未知"
    addr = sender_obj.get("emailAddress", {})
    name = addr.get("name", "")
    email = addr.get("address", "")
    if name and email:
        return f"{name} <{email}>"
    return email or name or "未知"


def _extract_recipients(recipients: list[dict]) -> list[dict]:
    """从 Graph API 的 toRecipients/ccRecipients 提取收件人列表。"""
    result = []
    for r in recipients:
        addr = r.get("emailAddress", {})
        result.append(
            {
                "name": addr.get("name", ""),
                "email": addr.get("address", ""),
            }
        )
    return result


def _extract_body(body_obj: dict) -> str:
    """从 Graph API 的 body 字段提取正文。"""
    if not body_obj:
        return ""
    content = body_obj.get("content", "")
    content_type = body_obj.get("contentType", "text")
    return f"[{content_type}] {content}" if content_type.lower() == "html" else content


def _truncate_preview(preview: str, max_len: int = 150) -> str:
    """截取邮件预览至指定长度。"""
    if not preview:
        return ""
    preview = preview.strip()
    if len(preview) <= max_len:
        return preview
    return preview[:max_len] + "..."


def _graph_error(resp) -> dict:
    """构造 Graph API 错误返回 dict。"""
    try:
        detail = resp.json()
        error_msg = detail.get("error", {}).get("message", resp.text)
    except Exception:
        error_msg = resp.text
    return {"error": error_msg, "status_code": resp.status_code}
