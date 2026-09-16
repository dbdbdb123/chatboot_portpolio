"""Mori가 외부에 제공하는 HTTP API 라우터."""

from __future__ import annotations

from typing import Annotated
import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import AIMessage, HumanMessage
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.deps import get_chat_service
from backend.api.streaming import chat_events
from backend.constants.app import API_PREFIX
from backend.constants.chat import SSE_MEDIA_TYPE
from backend.constants.enums import HealthStatus, MessageRole
from backend.mcp.validation import ToolValidationError
from backend.schemas import ChatRequest, ChatResponse, HealthResponse
from backend.schemas.history import ChatSessionMessages, ChatSessionSummary
from backend.services.chat import ChatService
from backend.services.history import RedisChatHistoryStore
from backend.services.pdf_text import MAX_PDF_BYTES

router = APIRouter(prefix=API_PREFIX)
ChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]
logger = logging.getLogger(__name__)


def _history_store(request: Request) -> RedisChatHistoryStore:
    """Redis가 설정된 경우 저장소를 반환하고, 비활성 상태면 명확한 503 오류를 반환한다."""
    store = getattr(request.app.state, "history_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="대화 기록 저장소가 설정되지 않았습니다.")
    return store


async def _save_completed_exchange(
    store: RedisChatHistoryStore, payload: ChatRequest, response: ChatResponse,
) -> None:
    """세션 ID가 있는 정상 완료 응답만 저장하며 저장 장애가 모델 답변을 가리지 않게 한다."""
    if payload.session_id is None:
        return
    try:
        history = store.history(str(payload.session_id))
        await history.aadd_messages([
            HumanMessage(content=payload.messages[-1].content),
            AIMessage(content=response.message.content),
        ])
    except Exception:
        # 사용자는 이미 답변 생성을 기다렸으므로 Redis 장애 때문에 답변 전체를 폐기하지 않는다.
        # 예외 세부 정보는 서버 로그에 남겨 운영자가 저장 실패를 확인할 수 있게 한다.
        logger.exception("Failed to persist chat session %s", payload.session_id)


async def _hydrate_session_messages(
    store: RedisChatHistoryStore | None, payload: ChatRequest,
) -> ChatRequest:
    """세션 요청을 Redis의 LangChain 히스토리와 현재 사용자 메시지로 재구성한다.

    세션 ID가 없거나 Redis가 비활성화된 요청은 클라이언트가 보낸 전체 기록을 그대로
    사용한다. 세션 요청에서는 클라이언트 기록을 신뢰하지 않고 서버 저장 기록을 읽어
    세션 간 주입과 중복 전송을 방지한다.
    """
    if store is None or payload.session_id is None:
        return payload
    try:
        history = await store.history(str(payload.session_id)).aget_messages()
    except KeyError as exc:
        # 삭제됐거나 만료된 세션을 새 세션처럼 조용히 다시 만들면 사용자가 기록 유실을
        # 알아차리기 어렵다. 일반 응답과 SSE 모두 스트림 시작 전에 동일한 404를 돌려준다.
        raise HTTPException(status_code=404, detail="대화 세션을 찾을 수 없습니다.") from exc
    restored = [ChatMessage(
        role=(MessageRole.USER if message.type == "human" else MessageRole.ASSISTANT),
        content=message.text,
    ) for message in history if message.type in {"human", "ai"}]
    # 모델 문맥 상한과 기존 API 제한을 맞추고 현재 사용자 메시지는 항상 마지막에 둔다.
    messages = [*restored[-99:], payload.messages[-1]]
    return payload.model_copy(update={"messages": messages})


@router.post("/chat/stream")
async def stream_chat(payload: ChatRequest, service: ChatServiceDependency, request: Request) -> StreamingResponse:
    """대화 요청을 SSE 응답으로 제공하고 프록시 버퍼링을 비활성화한다."""

    if payload.use_knowledge:
        service = request.app.state.rag_service
    store = getattr(request.app.state, "history_store", None)
    payload = await _hydrate_session_messages(store, payload)

    async def save_on_complete(response: ChatResponse) -> None:
        if store is not None:
            await _save_completed_exchange(store, payload, response)

    return StreamingResponse(
        # Redis가 비활성화된 기존 실행에서는 저장 콜백 자체를 넘기지 않아
        # SSE 프로토콜과 기존 테스트용 최소 DONE 이벤트를 그대로 허용한다.
        chat_events(payload, service, save_on_complete if store is not None else None),
        media_type=SSE_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """웹 서버와 별개로 Ollama 연결 가능 여부를 확인한다."""
    ollama_ok = await request.app.state.ollama.is_available()
    return HealthResponse(
        status=HealthStatus.OK if ollama_ok else HealthStatus.DEGRADED,
        ollama=ollama_ok,
        mcp_servers=len(request.app.state.settings.mcp_servers),
        model=request.app.state.settings.ollama_model,
    )


@router.get("/mcp/tools")
async def list_mcp_tools(request: Request) -> dict[str, object]:
    """MCP 서버가 광고한 도구 중 허용 목록을 통과한 도구만 반환한다."""
    try:
        tools = await request.app.state.mcp.list_tools()
        return {
            "tools": [
                {
                    "server": tool.server,
                    "name": tool.name,
                    "qualified_name": tool.qualified_name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ]
        }
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"MCP unavailable: {exc}") from exc


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    service: ChatServiceDependency,
    request: Request,
) -> ChatResponse:
    """대화 요청을 처리하고 하위 서비스 오류를 적절한 HTTP 상태로 변환한다."""
    try:
        store = getattr(request.app.state, "history_store", None)
        payload = await _hydrate_session_messages(store, payload)
        if payload.use_knowledge:
            service = request.app.state.rag_service
        response = await service.run(
            messages=payload.messages,
            use_tools=payload.use_tools,
            model=payload.model,
            think=payload.think,
            image=payload.image,
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


@router.post("/chat/sessions", response_model=ChatSessionSummary)
async def create_chat_session(request: Request) -> ChatSessionSummary:
    """새 UUID 대화 세션을 만들고 프런트엔드가 이후 요청에 사용할 ID를 반환한다."""
    return await _history_store(request).create_session()


@router.get("/chat/sessions", response_model=list[ChatSessionSummary])
async def list_chat_sessions(request: Request) -> list[ChatSessionSummary]:
    """3일이 지난 메시지를 정리한 뒤 최근 활동 순서의 세션 목록을 반환한다."""
    return await _history_store(request).list_sessions()


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionMessages)
async def read_chat_session(session_id: str, request: Request) -> ChatSessionMessages:
    """선택한 세션에서 아직 보관 기간이 지나지 않은 메시지를 시간순으로 반환한다."""
    try:
        return await _history_store(request).get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str, request: Request) -> dict[str, str]:
    """사용자가 요청한 세션과 그 세션의 모든 메시지를 즉시 삭제한다."""
    if not await _history_store(request).delete_session(session_id):
        raise HTTPException(status_code=404, detail="대화 세션을 찾을 수 없습니다.")
    return {"deleted": session_id}


class DocumentUpload(BaseModel):
    name: str = Field(min_length=1, max_length=154)
    content: str = Field(min_length=1, max_length=200_000)


@router.post("/knowledge/pdf")
async def register_pdf(request: Request, name: str):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF는 10 MB 이하만 등록할 수 있습니다.")
        data.extend(chunk)
    try:
        return await request.app.state.rag_service.register_pdf(name, bytes(data))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "PDF 등록에 실패했습니다. Qdrant와 Ollama 실행 상태를 확인해 주세요.") from exc


@router.get("/knowledge/documents")
async def knowledge_documents(request: Request):
    try:
        return {"documents": await asyncio.to_thread(request.app.state.rag_service.store.documents)}
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Qdrant에 연결할 수 없습니다. 실행 상태를 확인해 주세요.") from exc


@router.post("/knowledge/documents")
async def register_document(payload: DocumentUpload, request: Request):
    try:
        return await request.app.state.rag_service.register(payload.name, payload.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "문서 등록에 실패했습니다. Qdrant와 Ollama·embeddinggemma 실행 상태를 확인해 주세요.") from exc


@router.get("/knowledge/documents/{document_id}")
async def read_document(document_id: str, request: Request):
    try:
        return await asyncio.to_thread(request.app.state.rag_service.store.read, document_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Qdrant에 연결할 수 없습니다.") from exc


@router.delete("/knowledge/documents/{document_id}")
async def delete_document(document_id: str, request: Request):
    rag = request.app.state.rag_service
    try:
        async with rag.index_lock:
            if not await asyncio.to_thread(rag.store.delete, document_id):
                raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Qdrant에 연결할 수 없습니다.") from exc
    return {"deleted": document_id}
