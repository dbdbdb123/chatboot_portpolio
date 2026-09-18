"""Chat completion and streaming HTTP routes."""

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from backend.api.deps import get_chat_service
from backend.api.streaming import chat_events
from backend.constants.chat import SSE_MEDIA_TYPE
from backend.constants.enums import MessageRole
from backend.mcp.validation import ToolValidationError
from backend.schemas import ChatMessage, ChatRequest, ChatResponse
from backend.services.chat import ChatService
from backend.services.history import RedisChatHistoryStore

router = APIRouter()
ChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]
logger = logging.getLogger(__name__)


async def _save_completed_exchange(
    store: RedisChatHistoryStore, payload: ChatRequest, response: ChatResponse,
) -> None:
    if payload.session_id is None:
        return
    try:
        await store.history(str(payload.session_id)).aadd_messages([
            HumanMessage(content=payload.messages[-1].content),
            AIMessage(content=response.message.content),
        ])
    except Exception:
        logger.exception("Failed to persist chat session %s", payload.session_id)


async def _hydrate_session_messages(
    store: RedisChatHistoryStore | None, payload: ChatRequest,
) -> ChatRequest:
    if store is None or payload.session_id is None:
        return payload
    try:
        history = await store.history(str(payload.session_id)).aget_messages()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="대화 세션을 찾을 수 없습니다.") from exc
    restored = [ChatMessage(
        role=(MessageRole.USER if message.type == "human" else MessageRole.ASSISTANT),
        content=message.text,
    ) for message in history if message.type in {"human", "ai"}]
    return payload.model_copy(update={"messages": [*restored[-99:], payload.messages[-1]]})


def _selected_service(request: Request, service: ChatService, use_knowledge: bool):
    return request.app.state.rag_service if use_knowledge else service


@router.post("/chat/stream")
async def stream_chat(
    payload: ChatRequest, service: ChatServiceDependency, request: Request,
) -> StreamingResponse:
    store = getattr(request.app.state, "history_store", None)
    payload = await _hydrate_session_messages(store, payload)
    selected = _selected_service(request, service, payload.use_knowledge)

    async def save_on_complete(response: ChatResponse) -> None:
        if store is not None:
            await _save_completed_exchange(store, payload, response)

    return StreamingResponse(
        chat_events(payload, selected, save_on_complete if store is not None else None),
        media_type=SSE_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest, service: ChatServiceDependency, request: Request,
) -> ChatResponse:
    try:
        store = getattr(request.app.state, "history_store", None)
        payload = await _hydrate_session_messages(store, payload)
        selected = _selected_service(request, service, payload.use_knowledge)
        response = await selected.run(
            messages=payload.messages, use_tools=payload.use_tools, model=payload.model,
            think=payload.think, image=payload.image,
        )
        if store is not None:
            await _save_completed_exchange(store, payload, response)
        return response
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Ollama is unavailable") from exc
    except (ToolValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Tool execution timed out") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
