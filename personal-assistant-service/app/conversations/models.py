from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_CONVERSATION_TITLE = "新对话"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class TextMessagePart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"] = "text"
    text: str


class MessageContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    parts: list[TextMessagePart] = Field(min_length=1)


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        title = value.strip()
        if not title:
            return None
        if len(title) > 200:
            raise ValueError("title must be at most 200 characters")
        return title


class ConversationPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    status: ConversationStatus | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        if "title" in self.model_fields_set:
            if self.title is None or not self.title.strip():
                raise ValueError("title must not be blank")
            self.title = self.title.strip()
            if len(self.title) > 200:
                raise ValueError("title must be at most 200 characters")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status must be active or archived")
        return self


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    next_cursor: str | None = None


class ConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    id: UUID
    role: MessageRole
    content: MessageContent
    client_message_id: UUID | None
    reply_to_message_id: UUID | None
    created_at: datetime


class ConversationMessageListResponse(BaseModel):
    items: list[ConversationMessageResponse]
    next_cursor: str | None = None


class ApiError(BaseModel):
    code: str
    detail: str
