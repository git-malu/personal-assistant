"""Tests for app.playground — Chainlit Playground module (Feature 1.4)."""

import inspect

# ---------------------------------------------------------------------------
# Module import and handler registration
# ---------------------------------------------------------------------------


def test_playground_module_can_be_imported():
    """app.playground module imports without errors."""
    import app.playground  # noqa: F401

    assert app.playground is not None


def test_on_chat_start_is_registered():
    """on_chat_start is a callable coroutine function in app.playground."""
    import app.playground

    assert hasattr(app.playground, "on_chat_start"), (
        "app.playground should have on_chat_start function"
    )
    func = app.playground.on_chat_start
    assert callable(func), f"on_chat_start should be callable, got {type(func)}"
    assert inspect.iscoroutinefunction(func), (
        f"on_chat_start should be a coroutine function, got {type(func)}"
    )


def test_on_message_is_registered():
    """on_message is a callable coroutine function in app.playground."""
    import app.playground

    assert hasattr(app.playground, "on_message"), (
        "app.playground should have on_message function"
    )
    func = app.playground.on_message
    assert callable(func), f"on_message should be callable, got {type(func)}"
    assert inspect.iscoroutinefunction(func), (
        f"on_message should be a coroutine function, got {type(func)}"
    )


def test_on_chat_start_and_on_message_are_distinct():
    """on_chat_start and on_message are different function objects."""
    import app.playground

    assert app.playground.on_chat_start is not app.playground.on_message, (
        "on_chat_start and on_message should be distinct functions"
    )


def test_on_chat_start_uses_get_agent_handler():
    """on_chat_start references get_agent_handler (via closure or import)."""
    import app.playground

    source = inspect.getsource(app.playground.on_chat_start)
    assert "get_agent_handler" in source, (
        "on_chat_start should call get_agent_handler()"
    )


def test_on_message_uses_get_agent_handler():
    """on_message references get_agent_handler (via closure or import)."""
    import app.playground

    source = inspect.getsource(app.playground.on_message)
    assert "get_agent_handler" in source, "on_message should call get_agent_handler()"
