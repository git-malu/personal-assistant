from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.auth import extract_authenticated_user_id, extract_gateway_session_id
from app.conversations.locks import ConversationBusyError, ConversationLock
from app.conversations.models import (
    ApiError,
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationMessageListResponse,
    ConversationPatchRequest,
    ConversationResponse,
    ConversationStatus,
)
from app.conversations.service import (
    CheckpointDeleteError,
    ConversationNotFoundError,
    ConversationService,
    InvalidCursorError,
)
from app.conversations.store import ConversationStore
from app.database import Database
from app.invocations.registry import InvocationKey, InvocationRegistry

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _service(request: Request) -> ConversationService:
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None or not database.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is not configured",
        )
    handler = getattr(request.app.state, "agent_handler", None)
    checkpointer = getattr(handler, "checkpointer", None)
    return ConversationService(
        ConversationStore(database),
        lock=ConversationLock(database),
        checkpointer=checkpointer,
    )


def _user_id(request: Request) -> str:
    return extract_authenticated_user_id(request)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="conversation not found",
    )


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    service: Annotated[ConversationService, Depends(_service)],
    user_id: Annotated[str, Depends(_user_id)],
    conversation_status: Annotated[
        ConversationStatus,
        Query(alias="status"),
    ] = ConversationStatus.ACTIVE,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ConversationListResponse:
    try:
        return await service.list(
            user_id=user_id,
            status=conversation_status,
            cursor=cursor,
            limit=limit,
        )
    except InvalidCursorError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    body: ConversationCreateRequest,
    service: Annotated[ConversationService, Depends(_service)],
    user_id: Annotated[str, Depends(_user_id)],
) -> ConversationResponse:
    return await service.create(user_id=user_id, request=body)


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    service: Annotated[ConversationService, Depends(_service)],
    user_id: Annotated[str, Depends(_user_id)],
) -> ConversationResponse:
    try:
        return await service.get(
            user_id=user_id,
            conversation_id=conversation_id,
        )
    except ConversationNotFoundError as error:
        raise _not_found() from error


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def patch_conversation(
    conversation_id: UUID,
    body: ConversationPatchRequest,
    service: Annotated[ConversationService, Depends(_service)],
    user_id: Annotated[str, Depends(_user_id)],
) -> ConversationResponse:
    try:
        return await service.patch(
            user_id=user_id,
            conversation_id=conversation_id,
            request=body,
        )
    except ConversationNotFoundError as error:
        raise _not_found() from error


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
    responses={409: {"model": ApiError}},
)
async def delete_conversation(
    conversation_id: UUID,
    service: Annotated[ConversationService, Depends(_service)],
    user_id: Annotated[str, Depends(_user_id)],
) -> Response:
    try:
        await service.delete(user_id=user_id, conversation_id=conversation_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ConversationBusyError:
        return JSONResponse(
            status_code=409,
            content=ApiError(
                code="conversation_busy",
                detail="conversation is busy",
            ).model_dump(),
        )
    except CheckpointDeleteError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post(
    "/{conversation_id}/invocations/{client_message_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        204: {"description": "The Invocation is cancelled or already finished."},
    },
)
async def cancel_conversation_invocation(
    request: Request,
    conversation_id: UUID,
    client_message_id: UUID,
) -> Response:
    user_id = extract_authenticated_user_id(request)
    extract_gateway_session_id(request)
    registry: InvocationRegistry = request.app.state.invocation_registry
    await registry.cancel(
        key=InvocationKey(
            user_id=user_id,
            conversation_id=conversation_id,
            client_message_id=client_message_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessageListResponse,
)
async def list_conversation_messages(
    conversation_id: UUID,
    service: Annotated[ConversationService, Depends(_service)],
    user_id: Annotated[str, Depends(_user_id)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ConversationMessageListResponse:
    try:
        return await service.list_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            cursor=cursor,
            limit=limit,
        )
    except ConversationNotFoundError as error:
        raise _not_found() from error
    except InvalidCursorError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
