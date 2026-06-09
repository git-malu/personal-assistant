import json
from collections.abc import AsyncGenerator

from deepagents import create_deep_agent

from app.llm_config import get_model
from app.tools.email_tools import (
    draft_reply,
    get_email,
    list_emails,
    search_emails,
    send_email,
)
from app.tools.obs_tools import (
    get_obs_object,
    get_obs_object_metadata,
    list_obs_objects,
)

_handler_instance: "AgentHandler | None" = None


def get_agent_handler() -> "AgentHandler":
    """获取模块级 AgentHandler 单例。

    在 FastAPI lifespan（main.py）和 Chainlit app（playground.py）间共享同一实例。
    首次调用时初始化，后续调用返回缓存实例。
    """
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = AgentHandler()
    return _handler_instance


SYSTEM_PROMPT = """\
你是 Personal Assistant，一个智能个人助手。
帮助用户管理日程、邮件、笔记和任务。

## 核心能力

### 邮件处理
你可以帮助用户管理 Microsoft Outlook 邮箱，包括：
- **list_emails(folder, limit)**：列出指定文件夹的邮件。
  folder 默认为 "inbox"，也可指定 "sentitems"、"drafts" 等。limit 默认 10。
- **get_email(email_id)**：获取单封邮件的完整内容（正文、附件列表等）。
  email_id 可以从 list_emails 的返回结果中获取。
- **search_emails(query)**：按关键词搜索邮件。
  query 支持 Microsoft Graph API 的 KQL (Keyword Query Language) 语法，
  例如 "张三" 或 "subject:项目进度"。
- **draft_reply(email_id, body)**：草拟对某封邮件的回复。
  **此工具只草拟不发送**，调用后你会得到一个草稿内容，展示给用户确认。
- **send_email(to, subject, body, cc)**：发送邮件。
  ⚠️ **此为敏感操作，必须遵守下方"写操作安全规则"。**

### OBS 文件查询
你可以帮助用户浏览和读取华为云 OBS 对象存储中的文件：
- **list_obs_objects(bucket, prefix, limit)**：列出指定 Bucket 中的文件。
  例如 bucket="my-bucket", prefix="logs/" 列出 logs/ 目录下的文件。
- **get_obs_object(bucket, key)**：读取 OBS 对象的完整内容。
  适用于文本文件（.txt, .json, .csv, .md, .yaml, .log 等）。
- **get_obs_object_metadata(bucket, key)**：查询对象元数据
  （大小、类型、修改时间），不读取内容。

### 写操作安全规则（Critical）

以下工具是**写操作**，必须遵守确认规则：

1. **send_email**：发送邮件
   - **禁止**在用户首次请求时直接调用 send_email
   - **必须先调用 draft_reply 创建草稿**
     （草稿会自动保存到用户的 Drafts 文件夹），展示收件人、主题、正文
   - 明确告知用户"确认发送请回复'发送'"
   - **当用户回复"发送"后**（这是一次新的调用，无法看到之前的对话历史）：
     1. 调用 list_emails(folder="drafts", limit=1)
        获取 Drafts 文件夹中最新的草稿
     2. 调用 get_email(draft_id) 读取草稿的收件人、主题、正文
     3. 调用 send_email(to=..., subject=..., body=...) 发送
   - 如果用户说"修改一下"或"改成..."：
     1. 调用 list_emails(folder="drafts", limit=1) 获取最新草稿
     2. 从草稿中提取原邮件的 ID
     3. 重新调用 draft_reply(original_email_id, modified_body) 创建新草稿
     4. 展示新草稿并再次等待确认

> **设计说明**：你无法跨调用记住之前草拟的内容
> （每次 /invocations 调用是独立的），
> 但 draft_reply 会自动把草稿保存到 Microsoft 365 的 Drafts 文件夹。
> 利用这个机制，你始终可以通过
> list_emails(folder="drafts", limit=1) 找到最新的待发送草稿。

## 行为准则
- 使用中文回复
- 保持友好、专业、乐于助人的语调
- 不清楚的事情坦诚说明，不要编造
- 回复简洁有力，避免冗长
- 邮件查询结果以结构化格式呈现（发件人、主题、时间等关键字段）
- OBS 文件列表以表格或列表形式呈现"""


class AgentHandler:
    """Handles agent initialization and invocation."""

    def __init__(self):
        self.model = get_model()  # 默认使用 config.yaml 中 llm.default 指定的 provider
        self.agent = create_deep_agent(
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            tools=[
                list_emails,
                get_email,
                search_emails,
                send_email,
                draft_reply,
                list_obs_objects,
                get_obs_object,
                get_obs_object_metadata,
            ],
        )

    async def handle(
        self, message: str, user_id: str = "anonymous", session_id: str | None = None
    ) -> str:
        """Invoke the agent synchronously and return the final response."""
        result = await self.agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]}
        )
        return result["messages"][-1].content

    async def handle_stream(
        self, message: str, user_id: str = "anonymous"
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from the agent using astream_events v2."""
        try:
            async for event in self.agent.astream_events(
                {"messages": [{"role": "user", "content": message}]},
                version="v2",
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    token = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if token:
                        yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"

            # Signal completion
            yield f"data: {json.dumps({'token': '', 'done': True})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
