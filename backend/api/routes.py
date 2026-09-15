"""Mori가 외부에 제공하는 HTTP API 라우터."""

from __future__ import annotations

from typing import Annotated
import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.deps import get_chat_service
from backend.api.streaming import chat_events
from backend.constants.app import API_PREFIX
from backend.constants.chat import SSE_MEDIA_TYPE
from backend.constants.enums import HealthStatus
from backend.mcp.validation import ToolValidationError
from backend.schemas import ChatRequest, ChatResponse, HealthResponse
from backend.services.chat import ChatService
from backend.services.pdf_text import MAX_PDF_BYTES

router = APIRouter(prefix=API_PREFIX)
ChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]


@router.post("/chat/stream")
async def stream_chat(payload: ChatRequest, service: ChatServiceDependency, request: Request) -> StreamingResponse:
    """대화 요청을 SSE 응답으로 제공하고 프록시 버퍼링을 비활성화한다."""

    if payload.use_knowledge:
        service = request.app.state.rag_service
    return StreamingResponse(
        chat_events(payload, service),
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
        if payload.use_knowledge:
            service = request.app.state.rag_service
        return await service.run(
            messages=payload.messages,
            use_tools=payload.use_tools,
            model=payload.model,
            think=payload.think,
            image=payload.image,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Ollama is unavailable") from exc
    except (ToolValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Tool execution timed out") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
