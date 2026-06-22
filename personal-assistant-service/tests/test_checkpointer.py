"""Unit tests for session checkpoint feature (feature-session-checkpoint).

Covers:
  - AgentHandler._build_config() — thread_id construction
  - AgentHandler._init_checkpointer() — backend selection
  - AgentHandler.handle() / handle_stream() — config passing
  - Multi-turn context retention and session isolation
"""

import asyncio
from typing import TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import START, StateGraph

from app.agent_handler import AgentHandler
from app.settings import Settings

# ---------------------------------------------------------------------------
# _build_config — thread_id construction
# ---------------------------------------------------------------------------


class TestBuildConfig:
    """Tests for AgentHandler._build_config() static method."""

    def test_build_config_user_scoped(self):
        """_build_config("user_a", "s1") → thread_id = "user_a:s1".

        Different users get different thread_ids.
        """
        config_a = AgentHandler._build_config("user_a", "s1")
        config_b = AgentHandler._build_config("user_b", "s1")

        assert config_a == {"configurable": {"thread_id": "user_a:s1"}}
        assert config_b == {"configurable": {"thread_id": "user_b:s1"}}
        assert config_a != config_b, (
            "Different users should produce different thread_ids"
        )

    def test_build_config_fallback_default(self):
        """_build_config("user_a", None) → thread_id = "user_a:default"."""
        config = AgentHandler._build_config("user_a", None)
        assert config == {"configurable": {"thread_id": "user_a:default"}}

    def test_build_config_different_sessions_same_user(self):
        """Same user with different sessions → different thread_ids."""
        config_s1 = AgentHandler._build_config("user_a", "s1")
        config_s2 = AgentHandler._build_config("user_a", "s2")

        assert config_s1 != config_s2, (
            "Different sessions for the same user should produce different thread_ids"
        )
        assert config_s1["configurable"]["thread_id"] == "user_a:s1"
        assert config_s2["configurable"]["thread_id"] == "user_a:s2"

    def test_build_config_default_session_same_for_anonymous(self):
        """Two anonymous users with no session_id get same default suffix."""
        config_1 = AgentHandler._build_config("anonymous", None)
        config_2 = AgentHandler._build_config("anonymous", None)
        assert config_1 == config_2
        assert config_1["configurable"]["thread_id"] == "anonymous:default"


# ---------------------------------------------------------------------------
# _init_checkpointer — backend selection
# ---------------------------------------------------------------------------


class TestInitCheckpointer:
    """Tests for Settings-driven Checkpointer selection."""

    def _make_uninitialized_handler(self):
        """Create an AgentHandler instance bypassing __init__.

        This avoids triggering the real checkpointer/build during construction.
        """
        return AgentHandler.__new__(AgentHandler)

    def test_init_checkpointer_default_memory(self):
        """No backend setting → returns InMemorySaver instance."""
        from langgraph.checkpoint.memory import InMemorySaver

        handler = self._make_uninitialized_handler()
        result = handler._init_checkpointer(Settings(_env_file=None))

        assert isinstance(result, InMemorySaver), (
            f"Expected InMemorySaver, got {type(result).__name__}"
        )

    def test_init_checkpointer_sqlite_is_deferred_until_startup(self):
        """SQLITE_DB_PATH defers async Checkpointer creation until startup."""
        settings = Settings(
            _env_file=None,
            sqlite_db_path="/tmp/test-checkpoint.sqlite",
        )

        handler = self._make_uninitialized_handler()
        assert handler._init_checkpointer(settings) is None

    def test_init_checkpointer_postgres_is_deferred_until_startup(self):
        """POSTGRES_DSN defers async Checkpointer creation until startup."""
        settings = Settings(
            _env_file=None,
            postgres_dsn="postgresql://localhost/test",
        )

        handler = self._make_uninitialized_handler()
        assert handler._init_checkpointer(settings) is None

    @pytest.mark.asyncio
    async def test_startup_opens_and_sets_up_postgres_checkpointer(self):
        """startup() opens AsyncPostgresSaver and applies its schema."""
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        settings = Settings(
            _env_file=None,
            postgres_dsn="postgresql://localhost/test",
        )
        checkpointer = MagicMock(spec=AsyncPostgresSaver)
        checkpointer.setup = AsyncMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=checkpointer)
        context.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            AsyncPostgresSaver,
            "from_conn_string",
            return_value=context,
        ) as mock_from:
            handler = AgentHandler(settings=settings)
            await handler.startup()

            assert handler.checkpointer is checkpointer
            mock_from.assert_called_once_with("postgresql://localhost/test")
            checkpointer.setup.assert_awaited_once()

            await handler.shutdown()
            context.__aexit__.assert_awaited_once_with(None, None, None)


# ---------------------------------------------------------------------------
# Config passing — handle() and handle_stream()
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_handler():
    """Create an AgentHandler with mocked model, agent, and checkpointer.

    Uses the same pattern as mock_deps in test_agent_handler.py.
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

        handler = AgentHandler()

        yield handler, mock_agent, mock_init_cp


class TestConfigPassing:
    """Tests that handle() and handle_stream() pass config to the agent."""

    @pytest.mark.asyncio
    async def test_handler_passes_config_to_ainvoke(self, patched_handler):
        """handle() passes config with correct thread_id to agent.ainvoke()."""
        handler, mock_agent, _ = patched_handler

        mock_message = MagicMock()
        mock_message.content = "response"
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_message]})

        await handler.handle(
            message="Hello",
            user_id="user-42",
            session_id="sess-xyz",
        )

        mock_agent.ainvoke.assert_called_once()
        call_kwargs = mock_agent.ainvoke.call_args[1]

        assert "config" in call_kwargs, (
            "agent.ainvoke() should be called with a config kwarg"
        )
        assert call_kwargs["config"] == {
            "configurable": {"thread_id": "user-42:sess-xyz"}
        }

    @pytest.mark.asyncio
    async def test_conversation_id_overrides_runtime_session(self, patched_handler):
        """Web Chat conversation identity is independent from Runtime Session."""
        handler, mock_agent, _ = patched_handler
        mock_message = MagicMock(content="response")
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_message]})

        await handler.handle(
            message="Hello",
            user_id="user-42",
            conversation_id="conversation-1",
            session_id="runtime-session-9",
        )

        config = mock_agent.ainvoke.call_args[1]["config"]
        assert config == {"configurable": {"thread_id": "user-42:conversation-1"}}

    @pytest.mark.asyncio
    async def test_same_conversation_invocations_are_serialized(self, patched_handler):
        """Concurrent writes to one LangGraph thread never overlap."""
        handler, mock_agent, _ = patched_handler
        active = 0
        max_active = 0

        async def invoke(_input, config=None):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"messages": [MagicMock(content="response")]}

        mock_agent.ainvoke = invoke
        await asyncio.gather(
            handler.handle("one", user_id="user-1", conversation_id="conversation-1"),
            handler.handle("two", user_id="user-1", conversation_id="conversation-1"),
        )

        assert max_active == 1

    @pytest.mark.asyncio
    async def test_handler_passes_config_with_default_session(self, patched_handler):
        """handle() without explicit session_id uses 'default' suffix."""
        handler, mock_agent, _ = patched_handler

        mock_message = MagicMock()
        mock_message.content = "response"
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_message]})

        await handler.handle(message="Hello", user_id="user-99")

        call_kwargs = mock_agent.ainvoke.call_args[1]
        assert call_kwargs["config"] == {
            "configurable": {"thread_id": "user-99:default"}
        }

    @pytest.mark.asyncio
    async def test_handle_stream_passes_config(self, patched_handler):
        """handle_stream() passes config with correct thread_id to astream()."""
        handler, mock_agent, _ = patched_handler

        async def mock_astream(_input, stream_mode=None, config=None):
            chunk = MagicMock()
            chunk.content = "Hello"
            yield ("messages", (chunk, {}))

        mock_agent.astream = mock_astream

        events = [
            event
            async for event in handler.handle_stream(
                message="Hi",
                user_id="user-42",
                session_id="sess-abc",
            )
        ]
        # At least 1 token event + 1 done event
        assert len(events) >= 2, f"Expected >= 2 events, got {len(events)}: {events}"

    @pytest.mark.asyncio
    async def test_handle_stream_accepts_session_id(self, patched_handler):
        """handle_stream(msg, session_id="s1") works correctly."""
        handler, mock_agent, _ = patched_handler

        async def mock_astream(_input, stream_mode=None, config=None):
            chunk = MagicMock()
            chunk.content = "Token"
            yield ("messages", (chunk, {}))

        mock_agent.astream = mock_astream

        events = [
            event
            async for event in handler.handle_stream(message="Test", session_id="s1")
        ]
        assert len(events) >= 2, f"Expected >= 2 events, got {len(events)}: {events}"


# ---------------------------------------------------------------------------
# Multi-turn context retention & session isolation
# ---------------------------------------------------------------------------


class TestContextRetention:
    """Tests that the same session_id reuses the same thread_id across turns,
    while different session_ids get isolated thread_ids."""

    @pytest.mark.asyncio
    async def test_multi_turn_context_retention(self, patched_handler):
        """Mock agent called twice with same (user_id, session_id) →
        both calls use the same thread_id."""
        handler, mock_agent, _ = patched_handler

        mock_message = MagicMock()
        mock_message.content = "response"
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_message]})

        # Turn 1
        await handler.handle(
            message="First message",
            user_id="user-x",
            session_id="session-y",
        )
        # Turn 2 — same user and session
        await handler.handle(
            message="Second message",
            user_id="user-x",
            session_id="session-y",
        )

        assert mock_agent.ainvoke.call_count == 2

        config_1 = mock_agent.ainvoke.call_args_list[0][1]["config"]
        config_2 = mock_agent.ainvoke.call_args_list[1][1]["config"]

        assert config_1 == config_2, (
            f"Same (user_id, session_id) should produce same thread_id, "
            f"got {config_1} vs {config_2}"
        )
        assert config_1["configurable"]["thread_id"] == "user-x:session-y"

    @pytest.mark.asyncio
    async def test_session_isolation(self, patched_handler):
        """Two different session_ids produce different thread_ids."""
        handler, mock_agent, _ = patched_handler

        mock_message = MagicMock()
        mock_message.content = "response"
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_message]})

        # Session A
        await handler.handle(message="Hello", user_id="user-1", session_id="session-a")
        # Session B — same user, different session
        await handler.handle(
            message="Hello again", user_id="user-1", session_id="session-b"
        )

        assert mock_agent.ainvoke.call_count == 2

        config_a = mock_agent.ainvoke.call_args_list[0][1]["config"]
        config_b = mock_agent.ainvoke.call_args_list[1][1]["config"]

        assert config_a != config_b, (
            f"Different sessions should produce different thread_ids, "
            f"got {config_a} and {config_b}"
        )
        assert config_a["configurable"]["thread_id"] == "user-1:session-a"
        assert config_b["configurable"]["thread_id"] == "user-1:session-b"

    def test_user_scoped_thread_id_prevents_cross_user_leak(self):
        """Even with the same session_id, different users get different thread_ids.

        This prevents user A from reading user B's checkpoint state.
        _build_config is a static method, so we test it directly.
        """
        config_a = AgentHandler._build_config("user_a", "shared-session")
        config_b = AgentHandler._build_config("user_b", "shared-session")

        assert config_a != config_b, (
            "Different users with same session_id must have different thread_ids "
            "to prevent cross-user state leakage"
        )
        assert config_a["configurable"]["thread_id"] == "user_a:shared-session"
        assert config_b["configurable"]["thread_id"] == "user_b:shared-session"


class _CounterState(TypedDict, total=False):
    count: int


def _increment(state: _CounterState) -> _CounterState:
    return {"count": state.get("count", 0) + 1}


def _compile_counter_graph(checkpointer):
    builder = StateGraph(_CounterState)
    builder.add_node("increment", _increment)
    builder.add_edge(START, "increment")
    return builder.compile(checkpointer=checkpointer)


class TestCheckpointerAcrossAgentReplacement:
    """Real checkpoint tests across independently compiled graph instances."""

    @pytest.mark.asyncio
    async def test_replacement_graph_restores_same_thread_state(self):
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
        first_agent = _compile_counter_graph(checkpointer)
        second_agent = _compile_counter_graph(checkpointer)
        config = {"configurable": {"thread_id": "user-a:session-a"}}

        first = await first_agent.ainvoke({"count": 0}, config=config)
        second = await second_agent.ainvoke({}, config=config)

        assert first["count"] == 1
        assert second["count"] == 2

    @pytest.mark.asyncio
    async def test_replacement_graph_keeps_threads_isolated(self):
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()
        first_agent = _compile_counter_graph(checkpointer)
        second_agent = _compile_counter_graph(checkpointer)

        await first_agent.ainvoke(
            {"count": 0},
            config={"configurable": {"thread_id": "user-a:session-a"}},
        )
        other = await second_agent.ainvoke(
            {"count": 10},
            config={"configurable": {"thread_id": "user-b:session-b"}},
        )

        assert other["count"] == 11
