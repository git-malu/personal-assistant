from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class InvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID = Field(description="Conversation receiving the message.")
    client_message_id: UUID = Field(
        description="Client-generated idempotency key for the user message."
    )
    message: str = Field(description="User message sent to the Agent.")
    stream: StrictBool = Field(
        default=False,
        description="Return a Server-Sent Events stream instead of JSON.",
    )


class InvocationResponse(BaseModel):
    response: str


class AgentEventType(StrEnum):
    TOKEN = "token"
    CUSTOM = "custom"
    AUTH_CARD = "auth_card"


@dataclass(frozen=True)
class AgentStreamEvent:
    type: AgentEventType
    token: str | None = None
    data: Any = None
