"""Tools package — factory for building the LangGraph ToolNode with registered tools.

This module provides build_tools(), called by AgentHandler to dynamically
assemble the tool list. Each sub-module (email_tools.py, github_tools.py, etc.)
registers its tools via a module-level list.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_tools() -> list[Any]:
    """Build the list of tools for deepagents/LangGraph ToolNode.

    Collects tools from all registered sub-modules. Each sub-module
    must expose a module-level list of callable tool functions.
    """
    tools: list[Any] = []

    # ── Email tools (Feature 10a) — always register ──
    try:
        from app.tools.email_tools import EMAIL_TOOLS, ensure_provider_sync

        tools.extend(EMAIL_TOOLS)
        logger.info("Email tools registered (%d tools).", len(EMAIL_TOOLS))

        # Pre-create the OAuth2 credential provider on AgentArts Identity.
        # Don't gate tool registration on this — tools are always available
        # to the LLM. If provider creation fails, the _handle_provider_error
        # wrapper on each tool catches it and returns a user-friendly error
        # instead of crashing.
        ensure_provider_sync()
    except ImportError as e:
        logger.warning(
            "Email tools not available (import failed): %s. "
            "Email functionality will be disabled for this session.",
            e,
            exc_info=True,
        )

    # ── GitHub tools — always register ──
    try:
        from app.tools.github_tools import github_tools

        tools.extend(github_tools)
        logger.info("GitHub tools registered (%d tools).", len(github_tools))
    except ImportError as e:
        logger.warning(
            "GitHub tools not available (import failed): %s. "
            "GitHub functionality will be disabled for this session.",
            e,
            exc_info=True,
        )

    # ── Future tool modules go here ──

    return tools
