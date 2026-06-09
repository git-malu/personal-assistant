"""Chainlit local debug entry point for Feature 10 development.

Usage: uv run chainlit run chainlit_app.py

Independent of FastAPI/mount_chainlit — uses AgentHandler directly
with a hardcoded test user and local auth fallback in tool functions.
"""

import chainlit as cl

from app.agent_handler import AgentHandler

TEST_USER_ID = "dev-user@personal-assistant.local"


@cl.on_chat_start
async def start():
    agent = AgentHandler()
    cl.user_session.set("agent", agent)
    cl.user_session.set("user_id", TEST_USER_ID)
    await cl.Message(
        content=(
            "👋 欢迎使用 **Personal Assistant 本地调试模式**！\n\n"
            "用户：dev-user@personal-assistant.local\n"
            "可用工具：邮件（list_emails, get_email, search_emails, "
            "draft_reply, send_email）"
            " + OBS（list_obs_objects, get_obs_object, "
            "get_obs_object_metadata）"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    agent: AgentHandler = cl.user_session.get("agent")
    user_id = cl.user_session.get("user_id")
    response = await agent.handle(message.content, user_id=user_id)
    await cl.Message(content=response).send()
