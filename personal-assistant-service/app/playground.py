"""Chainlit Playground — Agent 调试 UI。

与 main.py 共享同一 FastAPI 进程内的 AgentHandler。
通过 Chainlit 原生 WebSocket + LangchainCallbackHandler 直接展示 Agent 推理步骤。
"""

import chainlit as cl
from langchain_core.runnables import RunnableConfig

from app.agent_handler import get_agent_handler


@cl.on_chat_start
async def on_chat_start():
    """初始化 session：注入欢迎消息，确保 agent_handler 可用。"""
    handler = get_agent_handler()
    cl.user_session.set("agent_handler", handler)

    await cl.Message(
        content="👋 欢迎使用 **Personal Assistant Playground**！\n\n"
        "这是一个 Agent 调试工具，你可以在这里与 Agent 对话，\n"
        "观察每一步推理过程（think → act → observe）。\n\n"
        "试试输入：*帮我安排明天下午三点的会议*"
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    """处理用户消息：调用 Agent，通过 callback 可视化推理步骤。"""
    handler = get_agent_handler()

    # 创建 Chainlit 消息对象，用于输出最终回复
    response_msg = cl.Message(content="")
    await response_msg.send()

    # 使用 LangchainCallbackHandler 捕获并可视化中间步骤
    callback = cl.LangchainCallbackHandler()

    try:
        # Generate or retrieve session_id from Chainlit session
        session_id = cl.user_session.get("id")  # Chainlit built-in session ID

        config = RunnableConfig(
            callbacks=[callback],
            configurable={"thread_id": f"playground:{session_id}"},
        )

        # 使用 ainvoke 获取完整结果，callback 自动捕获中间步骤
        result = await handler.agent.ainvoke(
            {"messages": [{"role": "user", "content": message.content}]},
            config=config,
        )

        # 输出最终回复
        final_content = result["messages"][-1].content if result.get("messages") else ""
        response_msg.content = final_content
        await response_msg.update()

    except Exception as e:
        response_msg.content = f"❌ Agent 调用失败: {str(e)}"
        await response_msg.update()
