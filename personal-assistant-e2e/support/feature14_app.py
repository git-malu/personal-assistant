"""Production FastAPI app with a deterministic Agent for Feature 14 E2E."""

import asyncio
import os
from collections.abc import AsyncIterator

from app import main as production
from app.agent_handler import AgentHandler
from app.invocations.models import AgentEventType, AgentStreamEvent
from fastapi import Request
from fastapi.responses import JSONResponse


class DeterministicAgentHandler(AgentHandler):
    """Keep production persistence lifecycle while replacing external model I/O."""

    async def _delay(self) -> None:
        await asyncio.sleep(float(os.getenv("PA_E2E_AGENT_DELAY_SECONDS", "0.4")))

    async def handle(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
    ) -> str:
        del user_id, conversation_id
        await self._delay()
        return f"Echo: {message}"

    async def handle_stream(
        self,
        message: str,
        user_id: str,
        conversation_id: str,
    ) -> AsyncIterator[AgentStreamEvent]:
        del user_id, conversation_id
        await self._delay()
        yield AgentStreamEvent(
            type=AgentEventType.TOKEN,
            token=f"Echo: {message}",
        )
        if message == "cancel this response":
            await asyncio.sleep(5)


_handler: DeterministicAgentHandler | None = None


def _get_agent_handler() -> DeterministicAgentHandler:
    global _handler
    if _handler is None:
        _handler = DeterministicAgentHandler()
    return _handler


def _skip_local_workload_exchange(request: Request) -> None:
    del request


production.get_agent_handler = _get_agent_handler
production.prepare_jwt_workload_access_token = _skip_local_workload_exchange


@production.app.middleware("http")
async def capture_oauth_callback_context(request: Request, call_next):
    """Expose callback routing headers only for the explicit E2E capture state."""
    if (
        request.url.path == "/auth/oauth2/callback/m365-calendar"
        and request.query_params.get("state") == "e2e-capture"
    ):
        return JSONResponse(
            {
                "authorization": request.headers.get("authorization"),
                "runtime_session": request.headers.get("x-hw-agentarts-session-id"),
            }
        )
    return await call_next(request)


app = production.app
