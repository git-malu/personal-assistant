"""Unit tests for app.agent_handler.AgentHandler and get_agent_handler singleton."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_handler import SYSTEM_PROMPT, AgentHandler, get_agent_handler
from app.tools.github_tools import GITHUB_TOOLS
from app.tools.obs_tools import OBS_TOOLS


@pytest.fixture
def mock_deps():
    """Mock get_model, create_deep_agent, and _init_checkpointer.

    Avoids real API calls and real checkpointer initialization.
    """
    with (
        patch("app.agent_handler.get_model") as mock_get_model,
        patch("app.agent_handler.create_deep_agent") as mock_create_agent,
        patch.object(
            AgentHandler, "_init_checkpointer", return_value=MagicMock()
        ) as mock_init_cp,
    ):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent

        yield mock_get_model, mock_create_agent, mock_model, mock_agent, mock_init_cp


class TestAgentHandlerInit:
    """Tests for AgentHandler.__init__."""

    def test_initializes_with_correct_model_config(self, mock_deps):
        mock_get_model, mock_create_agent, mock_model, mock_agent, mock_init_cp = (
            mock_deps
        )

        handler = AgentHandler()

        # Verify get_model was called (no args, using default provider)
        mock_get_model.assert_called_once()

        # Verify create_deep_agent was called with model and system prompt
        mock_create_agent.assert_called_once()
        kwargs = mock_create_agent.call_args[1]
        assert kwargs["model"] is mock_model
        assert kwargs["system_prompt"] == SYSTEM_PROMPT
        assert kwargs["tools"] == GITHUB_TOOLS + OBS_TOOLS
        assert "checkpointer" in kwargs
        assert kwargs["checkpointer"] is mock_init_cp.return_value

        # Verify handler stores model and agent references
        assert handler.model is mock_model
        assert handler.agent is mock_agent

    def test_system_prompt_mentions_github_project_tools(self):
        assert "git-malu/personal-assistant" in SYSTEM_PROMPT
        assert "Issues" in SYSTEM_PROMPT
        assert "Pull Requests" in SYSTEM_PROMPT

    def test_system_prompt_mentions_obs_tools(self):
        assert "OBS" in SYSTEM_PROMPT
        assert "bucket" in SYSTEM_PROMPT
        assert "只读" in SYSTEM_PROMPT

    def test_agent_handler_uses_get_model(self, mock_deps):
        mock_get_model, mock_create_agent, mock_model, mock_agent, _ = mock_deps

        AgentHandler()

        # Verify get_model was called to obtain the model
        mock_get_model.assert_called_once()
        # Verify the returned model was passed to create_deep_agent
        mock_create_agent.assert_called_once()
        assert mock_create_agent.call_args[1]["model"] is mock_model


class TestHandle:
    """Tests for AgentHandler.handle()."""

    @pytest.mark.asyncio
    async def test_handle_returns_agent_response(self, mock_deps):
        _, _, _, mock_agent, _ = mock_deps

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
        _, _, _, mock_agent, _ = mock_deps

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
        _, _, _, mock_agent, _ = mock_deps

        handler = AgentHandler()

        # Mock astream_events to yield streaming chunks
        async def mock_astream_events(_input, version="v2", config=None):
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
        _, _, _, mock_agent, _ = mock_deps

        handler = AgentHandler()

        async def mock_astream_events(_input, version="v2", config=None):
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
        _, _, _, mock_agent, _ = mock_deps

        handler = AgentHandler()

        async def mock_astream_events_error(_input, version="v2", config=None):
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
        _, _, _, mock_agent, _ = mock_deps

        handler = AgentHandler()

        async def mock_astream_events(_input, version="v2", config=None):
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
        _, _, _, mock_agent, _ = mock_deps

        handler = AgentHandler()

        async def mock_astream_events(_input, version="v2", config=None):
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


# ---------------------------------------------------------------------------
# get_agent_handler() — Singleton behavior (Feature 1.4)
# ---------------------------------------------------------------------------


class TestGetAgentHandlerSingleton:
    """Tests for get_agent_handler() module-level singleton (Feature 1.4)."""

    def test_get_agent_handler_returns_same_instance(self, mock_deps):
        """Calling get_agent_handler() twice returns the same object (is check)."""
        # Reset the module-level singleton to ensure a clean test state
        import app.agent_handler

        app.agent_handler._handler_instance = None

        try:
            h1 = get_agent_handler()
            h2 = get_agent_handler()

            assert h1 is h2, (
                f"Expected same instance, but got different objects: "
                f"{id(h1)} vs {id(h2)}"
            )
            assert isinstance(h1, AgentHandler), (
                f"Expected AgentHandler instance, got {type(h1)}"
            )
        finally:
            # Clean up: reset the singleton so other tests are not affected
            app.agent_handler._handler_instance = None

    def test_get_agent_handler_creates_only_one_instance(self, mock_deps):
        """get_agent_handler() creates AgentHandler only once across multiple calls."""
        import app.agent_handler

        app.agent_handler._handler_instance = None

        try:
            with patch.object(AgentHandler, "__init__", return_value=None) as mock_init:
                get_agent_handler()
                get_agent_handler()
                get_agent_handler()

                # __init__ should be called exactly once, not three times
                assert mock_init.call_count == 1, (
                    f"Expected AgentHandler.__init__ to be called once, "
                    f"got {mock_init.call_count}"
                )
        finally:
            app.agent_handler._handler_instance = None
