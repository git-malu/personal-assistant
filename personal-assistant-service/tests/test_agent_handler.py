"""Unit tests for app.agent_handler.AgentHandler and get_agent_handler singleton."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_handler import (
    SYSTEM_PROMPT,
    AgentBundle,
    AgentHandler,
    get_agent_handler,
)
from app.settings import Settings


def _fake_chunk(content: str):
    """Create a mock chunk object with a .content attribute."""
    chunk = MagicMock()
    chunk.content = content
    return chunk


@pytest.fixture
def mock_deps():
    """Mock get_model, create_deep_agent, build_tools, and _init_checkpointer.

    Avoids real API calls and real checkpointer initialization.
    """
    with (
        patch("app.agent_handler.get_model") as mock_get_model,
        patch("app.agent_handler.create_deep_agent") as mock_create_agent,
        patch("app.agent_handler.build_tools") as mock_build_tools,
        patch.object(
            AgentHandler, "_init_checkpointer", return_value=MagicMock()
        ) as mock_init_cp,
    ):
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent

        mock_build_tools.return_value = ["mock_tool_1", "mock_tool_2"]

        yield (
            mock_get_model,
            mock_create_agent,
            mock_model,
            mock_agent,
            mock_init_cp,
            mock_build_tools,
        )


class TestAgentHandlerInit:
    """Tests for AgentHandler.__init__."""

    def test_initializes_with_correct_model_config(self, mock_deps):
        (
            mock_get_model,
            mock_create_agent,
            _mock_model,
            _mock_agent,
            mock_init_cp,
            mock_build_tools,
        ) = mock_deps

        handler = AgentHandler()

        mock_get_model.assert_not_called()
        mock_create_agent.assert_not_called()
        mock_build_tools.assert_called_once()
        assert handler.checkpointer is mock_init_cp.return_value
        assert handler.tools == mock_build_tools.return_value
        assert handler._bundle is None

    @pytest.mark.asyncio
    async def test_agent_handler_uses_get_model(self, mock_deps):
        mock_get_model, mock_create_agent, mock_model, mock_agent, _, _ = mock_deps

        handler = AgentHandler()
        agent = await handler.get_agent()

        mock_get_model.assert_called_once_with(settings=handler.settings)
        mock_create_agent.assert_called_once()
        assert mock_create_agent.call_args[1]["model"] is mock_model
        assert handler._bundle is not None
        assert handler._bundle.agent is mock_agent
        assert agent is mock_agent

    @pytest.mark.asyncio
    async def test_agent_created_with_tools_from_build_tools(self, mock_deps):
        """UT-AH-01: Agent creation uses build_tools() result for tools kwarg."""
        _, mock_create_agent, _, _, _, mock_build_tools = mock_deps

        handler = AgentHandler()
        await handler.get_agent()

        mock_build_tools.assert_called_once()
        kwargs = mock_create_agent.call_args[1]
        assert kwargs["tools"] is mock_build_tools.return_value

    def test_system_prompt_mentions_email_capabilities(self):
        """UT-AH-02: SYSTEM_PROMPT contains names of all 5 email tools."""
        assert "list_emails" in SYSTEM_PROMPT
        assert "get_email" in SYSTEM_PROMPT
        assert "search_emails" in SYSTEM_PROMPT
        assert "send_email" in SYSTEM_PROMPT
        assert "reply_to_email" in SYSTEM_PROMPT

    def test_system_prompt_mentions_github_capabilities(self):
        """UT-AH-04: SYSTEM_PROMPT contains names of all GitHub tools."""
        assert "github_list_repositories" in SYSTEM_PROMPT
        assert "github_list_repo_contents" in SYSTEM_PROMPT
        assert "github_get_file_content" in SYSTEM_PROMPT
        assert "github_search_code" in SYSTEM_PROMPT
        assert "github_star_repository" in SYSTEM_PROMPT

    def test_system_prompt_mentions_gitee_capabilities(self):
        """UT-AH-05: SYSTEM_PROMPT contains Gitee tool names."""
        assert "gitee_list_repositories" in SYSTEM_PROMPT

    def test_system_prompt_mentions_huaweicloud_iam_capabilities(self):
        """UT-AH-06: SYSTEM_PROMPT contains Huawei Cloud IAM tool names."""
        assert "huaweicloud_list_iam_users" in SYSTEM_PROMPT

    def test_system_prompt_contains_guard_instruction(self):
        """UT-AH-03: SYSTEM_PROMPT contains Guard instructions for sensitive ops."""
        assert (
            "必须先确认" in SYSTEM_PROMPT or "必须先向用户展示预览" in SYSTEM_PROMPT
        ), "SYSTEM_PROMPT missing confirmation guard instruction"


class TestAgentBundleLifecycle:
    """Tests for lazy, renewable process-scoped Agent Bundles."""

    @pytest.mark.asyncio
    async def test_reuses_agent_within_ttl(self, mock_deps):
        mock_get_model, mock_create_agent, _, mock_agent, _, _ = mock_deps
        handler = AgentHandler()

        first = await handler.get_agent()
        second = await handler.get_agent()

        assert first is mock_agent
        assert second is mock_agent
        mock_get_model.assert_called_once()
        mock_create_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_refreshes_agent_after_expiry(self, mock_deps):
        mock_get_model, mock_create_agent, _, first_agent, _, _ = mock_deps
        handler = AgentHandler()

        assert await handler.get_agent() is first_agent
        assert handler._bundle is not None
        handler._bundle = AgentBundle(agent=first_agent, expires_at=0.0)

        second_agent = MagicMock()
        mock_create_agent.return_value = second_agent

        assert await handler.get_agent() is second_agent
        assert mock_get_model.call_count == 2
        assert mock_create_agent.call_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_cold_start_builds_once(self, mock_deps):
        _, mock_create_agent, _, mock_agent, _, _ = mock_deps
        handler = AgentHandler()

        async def delayed_to_thread(func):
            await asyncio.sleep(0.01)
            return func()

        with patch(
            "app.agent_handler.asyncio.to_thread", side_effect=delayed_to_thread
        ) as mock_to_thread:
            agents = await asyncio.gather(
                handler.get_agent(),
                handler.get_agent(),
                handler.get_agent(),
            )

        assert agents == [mock_agent, mock_agent, mock_agent]
        mock_to_thread.assert_called_once()
        mock_create_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_build_does_not_publish_bundle(self, mock_deps):
        mock_get_model, _, mock_model, mock_agent, _, _ = mock_deps
        handler = AgentHandler()
        mock_get_model.side_effect = [RuntimeError("identity unavailable"), mock_model]

        with pytest.raises(RuntimeError, match="identity unavailable"):
            await handler.get_agent()

        assert handler._bundle is None
        assert await handler.get_agent() is mock_agent
        assert mock_get_model.call_count == 2

    @pytest.mark.asyncio
    async def test_invalidation_forces_next_request_to_refresh(self, mock_deps):
        _, mock_create_agent, _, first_agent, _, _ = mock_deps
        handler = AgentHandler()
        assert await handler.get_agent() is first_agent

        await handler.invalidate_agent_bundle()
        second_agent = MagicMock()
        mock_create_agent.return_value = second_agent

        assert await handler.get_agent() is second_agent
        assert mock_create_agent.call_count == 2

    @pytest.mark.asyncio
    async def test_refresh_reuses_same_checkpointer(self, mock_deps):
        _, mock_create_agent, _, first_agent, mock_init_cp, _ = mock_deps
        handler = AgentHandler()
        await handler.get_agent()
        handler._bundle = AgentBundle(agent=first_agent, expires_at=0.0)
        mock_create_agent.return_value = MagicMock()

        await handler.get_agent()

        first_kwargs = mock_create_agent.call_args_list[0].kwargs
        second_kwargs = mock_create_agent.call_args_list[1].kwargs
        assert first_kwargs["checkpointer"] is mock_init_cp.return_value
        assert second_kwargs["checkpointer"] is mock_init_cp.return_value

    @pytest.mark.asyncio
    async def test_worker_thread_receives_runtime_context(self, mock_deps):
        from agentarts.sdk.runtime.context import AgentArtsRuntimeContext

        mock_get_model, _, _, _, _, _ = mock_deps
        handler = AgentHandler()

        def assert_context(*, settings):
            assert settings is handler.settings
            assert (
                AgentArtsRuntimeContext.get_workload_access_token() == "workload-token"
            )
            return MagicMock()

        mock_get_model.side_effect = assert_context
        AgentArtsRuntimeContext.set_workload_access_token("workload-token")
        try:
            await handler.get_agent()
        finally:
            AgentArtsRuntimeContext.set_workload_access_token(None)


class TestHandle:
    """Tests for AgentHandler.handle()."""

    @pytest.mark.asyncio
    async def test_handle_returns_agent_response(self, mock_deps):
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler()

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
        call_arg = mock_agent.ainvoke.call_args[0][0]
        assert call_arg["messages"][0]["role"] == "user"
        assert call_arg["messages"][0]["content"] == "你好"

    @pytest.mark.asyncio
    async def test_handle_default_user_id(self, mock_deps):
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler()

        mock_message = MagicMock()
        mock_message.content = "response"
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_message]})

        result = await handler.handle(message="test")

        assert result == "response"
        mock_agent.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_restarts_checkpointer_and_retries_idle_timeout(
        self, mock_deps
    ):
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler(
            settings=Settings(
                _env_file=None,
                postgres_dsn="postgresql://localhost/test",
            )
        )
        recovered_message = MagicMock()
        recovered_message.content = "recovered"
        mock_agent.ainvoke = AsyncMock(
            side_effect=[
                RuntimeError("terminating connection due to idle-session timeout"),
                {"messages": [recovered_message]},
            ]
        )

        with patch.object(
            handler, "_restart_checkpointer", new_callable=AsyncMock
        ) as mock_restart:
            result = await handler.handle(
                message="继续",
                user_id="user-1",
                session_id="session-1",
            )

        assert result == "recovered"
        assert mock_agent.ainvoke.await_count == 2
        mock_restart.assert_awaited_once()


class TestHandleStream:
    """Tests for AgentHandler.handle_stream() using stream_mode."""

    @pytest.mark.asyncio
    async def test_handle_stream_yields_sse_events(self, mock_deps):
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler()

        async def mock_astream(_input, stream_mode=None, config=None):
            chunk1 = MagicMock()
            chunk1.content = "Hello"
            yield ("messages", (chunk1, {}))

            chunk2 = MagicMock()
            chunk2.content = " world"
            yield ("messages", (chunk2, {}))

        mock_agent.astream = mock_astream

        events = [data async for data in handler.handle_stream(message="Hi")]

        assert len(events) >= 3

        parsed = []
        for event in events:
            assert event.startswith("data: ")
            parsed.append(json.loads(event[6:]))

        tokens = [p["token"] for p in parsed if not p.get("done")]
        assert "Hello" in tokens
        assert " world" in tokens

        assert parsed[-1]["done"] is True

    @pytest.mark.asyncio
    async def test_handle_stream_skips_empty_tokens(self, mock_deps):
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler()

        async def mock_astream(_input, stream_mode=None, config=None):
            chunk_empty = MagicMock()
            chunk_empty.content = ""
            yield ("messages", (chunk_empty, {}))

            chunk_good = MagicMock()
            chunk_good.content = "real"
            yield ("messages", (chunk_good, {}))

        mock_agent.astream = mock_astream

        events = [data async for data in handler.handle_stream(message="Hi")]

        token_events = [
            json.loads(e[6:]) for e in events if not json.loads(e[6:]).get("done")
        ]
        assert len(token_events) == 1
        assert token_events[0]["token"] == "real"

    @pytest.mark.asyncio
    async def test_handle_stream_error_yields_sse_error_event(self, mock_deps):
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler()

        async def mock_astream_error(_input, stream_mode=None, config=None):
            raise ConnectionError("API connection failed")
            yield  # unreachable

        mock_agent.astream = mock_astream_error

        events = [data async for data in handler.handle_stream(message="Hi")]

        assert len(events) == 1
        parsed = json.loads(events[0][6:])
        assert "error" in parsed
        assert "API connection failed" in parsed["error"]
        assert parsed["done"] is True

    @pytest.mark.asyncio
    async def test_handle_stream_restarts_checkpointer_and_retries_before_output(
        self, mock_deps
    ):
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler(
            settings=Settings(
                _env_file=None,
                postgres_dsn="postgresql://localhost/test",
            )
        )
        calls = 0

        async def mock_astream(_input, stream_mode=None, config=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("the connection is closed")
            yield ("messages", (_fake_chunk("Recovered"), {}))

        mock_agent.astream = mock_astream

        with patch.object(
            handler, "_restart_checkpointer", new_callable=AsyncMock
        ) as mock_restart:
            events = [data async for data in handler.handle_stream(message="Hi")]

        parsed = [json.loads(event[6:]) for event in events]
        assert parsed[0]["token"] == "Recovered"
        assert parsed[-1]["done"] is True
        assert calls == 2
        mock_restart.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_stream_does_not_retry_after_output(self, mock_deps):
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler(
            settings=Settings(
                _env_file=None,
                postgres_dsn="postgresql://localhost/test",
            )
        )

        async def mock_astream(_input, stream_mode=None, config=None):
            yield ("messages", (_fake_chunk("Partial"), {}))
            raise RuntimeError("the connection is closed")

        mock_agent.astream = mock_astream

        with patch.object(
            handler, "_restart_checkpointer", new_callable=AsyncMock
        ) as mock_restart:
            events = [data async for data in handler.handle_stream(message="Hi")]

        parsed = [json.loads(event[6:]) for event in events]
        assert parsed[0]["token"] == "Partial"
        assert parsed[1]["error"] == "the connection is closed"
        assert parsed[1]["done"] is True
        mock_restart.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_stream_skips_chunk_without_content_attr(self, mock_deps):
        """Chunks without .content are treated as empty and skipped."""
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler()

        async def mock_astream(_input, stream_mode=None, config=None):
            chunk_no_content = object()
            yield ("messages", (chunk_no_content, {}))

        mock_agent.astream = mock_astream

        events = [data async for data in handler.handle_stream(message="Hi")]

        # Only the completion event — chunk without .content → empty → skipped
        assert len(events) == 1
        parsed = json.loads(events[0][6:])
        assert parsed["done"] is True


# ═══════════════════════════════════════════════════════════════
# handle_stream with stream_mode=["messages", "custom"]
# ═══════════════════════════════════════════════════════════════


class TestHandleStreamWithCustomEvent:
    """Tests for handle_stream() custom mode (auth URL delivery)."""

    @pytest.mark.asyncio
    async def test_custom_event_yields_system_message(self, mock_deps):
        """UT-HSM-01: auth_required custom events emit named 'auth_card' SSE."""
        _, _, _, mock_agent, _, _ = mock_deps

        handler = AgentHandler()

        async def mock_astream(_input, stream_mode=None, config=None):
            yield (
                "custom",
                {
                    "system_message": "Please authorize",
                    "auth_url": "https://auth.example.com",
                    "auth_required": True,
                },
            )
            yield ("messages", (_fake_chunk("Hello"), {}))

        mock_agent.astream = mock_astream

        events = [
            data
            async for data in handler.handle_stream(
                message="Hi",
            )
        ]

        # Parse both named SSE (event: X\ndata: Y) and plain data: lines
        parsed = []
        for sse in events:
            lines = sse.strip().split("\n")
            data_line = None
            for line in lines:
                if line.startswith("data: "):
                    data_line = line
            if data_line:
                parsed.append(json.loads(data_line[6:]))

        system_msgs = [p for p in parsed if "system_message" in p]
        assert len(system_msgs) == 1
        assert system_msgs[0]["system_message"] == "Please authorize"
        assert system_msgs[0]["auth_url"] == "https://auth.example.com"
        assert system_msgs[0]["auth_required"] is True

        tokens = [p for p in parsed if "token" in p and not p.get("done")]
        assert len(tokens) == 1
        assert tokens[0]["token"] == "Hello"


# ---------------------------------------------------------------------------
# get_agent_handler() — Singleton behavior (Feature 1.4)
# ---------------------------------------------------------------------------


class TestGetAgentHandlerSingleton:
    """Tests for get_agent_handler() module-level singleton (Feature 1.4)."""

    def test_get_agent_handler_returns_same_instance(self, mock_deps):
        """Calling get_agent_handler() twice returns the same object (is check)."""
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

                assert mock_init.call_count == 1, (
                    f"Expected AgentHandler.__init__ to be called once, "
                    f"got {mock_init.call_count}"
                )
        finally:
            app.agent_handler._handler_instance = None
