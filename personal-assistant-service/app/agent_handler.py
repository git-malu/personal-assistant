import json
import os
from collections.abc import AsyncGenerator

from deepagents import create_deep_agent

from app.llm_config import get_model

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

## 核心能力（将陆续上线）
- 日程管理：创建、查询、修改和取消日程
- 邮件处理：阅读、撰写和回复邮件
- 笔记管理：创建和检索个人笔记
- 任务追踪：管理待办事项和项目进度

## 当前状态
你目前处于初始阶段，暂时无法调用外部工具（如日历、邮件、笔记等）。
你可以进行友好的对话，回答用户的问题，提供建议，并帮助用户梳理思路。
当用户询问与日程/邮件/笔记/任务相关的操作时，请友好地解释这些功能即将上线。

## 行为准则
- 使用中文回复
- 保持友好、专业、乐于助人的语调
- 不清楚的事情坦诚说明，不要编造
- 回复简洁有力，避免冗长"""


class AgentHandler:
    """Handles agent initialization and invocation."""

    def __init__(self):
        self.model = get_model()  # 默认使用 config.yaml 中 llm.default 指定的 provider
        self.checkpointer = self._init_checkpointer()
        self.agent = create_deep_agent(
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            tools=[],
            checkpointer=self.checkpointer,
        )

    def _init_checkpointer(self):
        """按环境变量选择 Checkpointer 后端。

        优先级: POSTGRES_DSN > SQLITE_DB_PATH > InMemorySaver（默认）
        """
        # PostgresSaver — 生产环境（留桩，未测试）
        if os.environ.get("POSTGRES_DSN"):
            from langgraph.checkpoint.postgres import PostgresSaver

            return PostgresSaver.from_conn_string(os.environ["POSTGRES_DSN"])

        # AsyncSqliteSaver — 本地持久化
        if os.environ.get("SQLITE_DB_PATH"):
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            return AsyncSqliteSaver.from_conn_string(os.environ["SQLITE_DB_PATH"])

        # InMemorySaver — 默认（开发/调试/测试）
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()

    @staticmethod
    def _build_config(user_id: str, session_id: str | None = None) -> dict:
        """构造 LangGraph config，thread_id = {user_id}:{session_id}。

        user-scoped thread_id 从源头防止跨用户 session 泄露。
        """
        sid = session_id or "default"
        return {"configurable": {"thread_id": f"{user_id}:{sid}"}}

    async def handle(
        self, message: str, user_id: str = "anonymous", session_id: str | None = None
    ) -> str:
        """Invoke the agent synchronously and return the final response."""
        config = self._build_config(user_id, session_id)
        result = await self.agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
        )
        messages = result.get("messages", [])
        if not messages:
            raise RuntimeError("Agent returned empty response")
        return messages[-1].content

    async def handle_stream(
        self, message: str, user_id: str = "anonymous",
        session_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from the agent using astream_events v2."""
        config = self._build_config(user_id, session_id)
        try:
            async for event in self.agent.astream_events(
                {"messages": [{"role": "user", "content": message}]},
                version="v2",
                config=config,
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
