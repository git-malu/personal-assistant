"""Unit tests for app.agent_handler.AgentHandler."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure MODEL_API_KEY is available for AgentHandler.__init__
os.environ["MODEL_API_KEY"] = "test-key"

from app.agent_handler import SYSTEM_PROMPT, AgentHandler


@pytest.fixture
def mock_deps():
    """Mock init_chat_model and create_deep_agent to avoid real API calls."""
    with (
        patch("app.agent_handler.init_chat_model") as mock_init_chat,
        patch("app.agent_handler.create_deep_agent") as mock_create_agent,
    ):
        mock_model = MagicMock()
        mock_init_chat.return_value = mock_model

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent

        yield mock_init_chat, mock_create_agent, mock_model, mock_agent


class TestAgentHandlerInit:
    """Tests for AgentHandler.__init__."""

    def test_initializes_with_correct_model_config(self, mock_deps):
        mock_init_chat, mock_create_agent, mock_model, mock_agent = mock_deps

        handler = AgentHandler()

        # Verify init_chat_model was called with OpenAI-compatible prefix
        mock_init_chat.assert_called_once()
        call_args = mock_init_chat.call_args[0]
        assert call_args[0].startswith("openai:")
        assert "deepseek-v4-pro" in call_args[0]

        # Verify create_deep_agent was called with model and system prompt
        mock_create_agent.assert_called_once()
        kwargs = mock_create_agent.call_args[1]
        assert kwargs["model"] is mock_model
        assert kwargs["system_prompt"] == SYSTEM_PROMPT
        assert kwargs["tools"] == []

        # Verify handler stores model and agent references
        assert handler.model is mock_model
        assert handler.agent is mock_agent

    def test_uses_custom_model_name_from_env(self, mock_deps):
        mock_init_chat, _, _, _ = mock_deps

        with patch.dict(os.environ, {"MODEL_NAME": "custom-model"}, clear=False):
            AgentHandler()

        call_args = mock_init_chat.call_args[0]
        assert "custom-model" in call_args[0]

    def test_uses_custom_model_url_from_env(self, mock_deps):
        mock_init_chat, _, _, _ = mock_deps

        with patch.dict(
            os.environ, {"MODEL_URL": "https://custom.api.com/v1"}, clear=False
        ):
            AgentHandler()

        kwargs = mock_init_chat.call_args[1]
        assert kwargs["base_url"] == "https://custom.api.com/v1"


class TestHandle:
    """Tests for AgentHandler.handle()."""

    @pytest.mark.asyncio
    async def test_handle_returns_agent_response(self, mock_deps):
        _, _, _, mock_agent = mock_deps

        handler = AgentHandler()

        # Configure mock agent.ainvoke to return a messages list
        mock_message = MagicMock()
        mock_message.content = "你好！有什么可以帮助你的？"
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_message]})

        result = await handler.handle(
            message="你好",
            user_id="user-123",
            session_id="session-abc",
        )

        assert result == "你好！有什么可以帮助你的？"
        mock_agent.ainvoke.assert_called_once()
        # Verify the input message structure
        call_arg = mock_agent.ainvoke.call_args[0][0]
        assert call_arg["messages"][0]["role"] == "user"
        assert call_arg["messages"][0]["content"] == "你好"

    @pytest.mark.asyncio
    async def test_handle_default_user_id(self, mock_deps):
        _, _, _, mock_agent = mock_deps

        handler = AgentHandler()

        mock_message = MagicMock()
        mock_message.content = "response"
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_message]})

        result = await handler.handle(message="test")

        assert result == "response"
        mock_agent.ainvoke.assert_called_once()


class TestHandleStream:
    """Tests for AgentHandler.handle_stream()."""

    @pytest.mark.asyncio
    async def test_handle_stream_yields_sse_events(self, mock_deps):
        _, _, _, mock_agent = mock_deps

        handler = AgentHandler()

        # Mock astream_events to yield streaming chunks
        async def mock_astream_events(_input, version="v2"):
            chunk1 = MagicMock()
            chunk1.content = "Hello"
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk1}}

            chunk2 = MagicMock()
            chunk2.content = " world"
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk2}}

            # Non-stream event — should be skipped by the handler
            yield {"event": "on_chain_end", "data": {}}

        mock_agent.astream_events = mock_astream_events

        events = [data async for data in handler.handle_stream(message="Hi")]

        # Should have at least 2 token events + 1 done event
        assert len(events) >= 3

        # Parse SSE data to verify content
        parsed = []
        for event in events:
            assert event.startswith("data: ")
            parsed.append(json.loads(event[6:]))

        tokens = [p["token"] for p in parsed if not p.get("done")]
        assert "Hello" in tokens
        assert " world" in tokens

        # Last event should signal completion
        assert parsed[-1]["done"] is True

    @pytest.mark.asyncio
    async def test_handle_stream_skips_empty_tokens(self, mock_deps):
        _, _, _, mock_agent = mock_deps

        handler = AgentHandler()

        async def mock_astream_events(_input, version="v2"):
            # Empty token should be skipped
            chunk_empty = MagicMock()
            chunk_empty.content = ""
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": chunk_empty},
            }

            chunk_good = MagicMock()
            chunk_good.content = "real"
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": chunk_good},
            }

        mock_agent.astream_events = mock_astream_events

        events = [data async for data in handler.handle_stream(message="Hi")]

        # Only the non-empty token + the completion should appear
        token_events = [
            json.loads(e[6:]) for e in events if not json.loads(e[6:]).get("done")
        ]
        assert len(token_events) == 1
        assert token_events[0]["token"] == "real"

    @pytest.mark.asyncio
    async def test_handle_stream_error_yields_sse_error_event(self, mock_deps):
        _, _, _, mock_agent = mock_deps

        handler = AgentHandler()

        async def mock_astream_events_error(_input, version="v2"):
            raise ConnectionError("API connection failed")
            yield  # unreachable

        mock_agent.astream_events = mock_astream_events_error

        events = [data async for data in handler.handle_stream(message="Hi")]

        # Should have exactly one event — the error event
        assert len(events) == 1
        parsed = json.loads(events[0][6:])
        assert "error" in parsed
        assert "API connection failed" in parsed["error"]
        assert parsed["done"] is True

    @pytest.mark.asyncio
    async def test_handle_stream_fallback_when_chunk_has_no_content_attr(
        self, mock_deps
    ):
        """Test that handle_stream uses str(chunk) when chunk lacks .content."""
        _, _, _, mock_agent = mock_deps

        handler = AgentHandler()

        async def mock_astream_events(_input, version="v2"):
            # Chunk without .content attribute (will use str(chunk))
            chunk_no_content = object()  # has no .content
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": chunk_no_content},
            }

        mock_agent.astream_events = mock_astream_events

        events = [data async for data in handler.handle_stream(message="Hi")]

        # Should have the token event + done event
        assert len(events) == 2
        parsed = [json.loads(e[6:]) for e in events]
        token_event = parsed[0]
        assert not token_event["done"]
        assert token_event["token"]  # str() representation is non-empty

    @pytest.mark.asyncio
    async def test_handle_stream_ignores_non_stream_events(self, mock_deps):
        """Test that only on_chat_model_stream events produce SSE data."""
        _, _, _, mock_agent = mock_deps

        handler = AgentHandler()

        async def mock_astream_events(_input, version="v2"):
            # Various non-stream events
            yield {"event": "on_chain_start", "data": {}}
            yield {"event": "on_tool_start", "data": {}}
            yield {"event": "on_tool_end", "data": {}}
            yield {"event": "on_chain_end", "data": {}}

        mock_agent.astream_events = mock_astream_events

        events = [data async for data in handler.handle_stream(message="Hi")]

        # Only the completion event should appear (no token events)
        assert len(events) == 1
        parsed = json.loads(events[0][6:])
        assert parsed["done"] is True
        assert "token" not in parsed or parsed["token"] == ""
