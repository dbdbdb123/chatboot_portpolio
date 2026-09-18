"""Knowledge document registration and management HTTP routes."""

import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.services.pdf_text import MAX_PDF_BYTES

router = APIRouter()


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
        documents = await asyncio.to_thread(request.app.state.rag_service.store.documents)
        return {"documents": documents}
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
