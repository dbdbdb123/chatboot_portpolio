"""Mori가 외부에 제공하는 HTTP API 라우터."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import aclosing, suppress

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.deps import get_chat_service
from backend.constants.app import API_PREFIX
from backend.mcp.validation import ToolValidationError
from backend.models import ChatRequest, ChatResponse, HealthResponse
from backend.services.chat import ChatService

router = APIRouter(prefix=API_PREFIX)


@router.post("/chat/stream")
async def stream_chat(payload: ChatRequest, service: ChatService = Depends(get_chat_service)):
    async def events():
        pending = None
        async with aclosing(service.stream(payload.messages, payload.use_tools, payload.model)) as stream:
            try:
                pending = asyncio.create_task(anext(stream))
                while True:
                    ready, _ = await asyncio.wait({pending}, timeout=15)
                    if not ready:
                        yield ": keep-alive\n\n"
                        continue
                    try:
                        event = pending.result()
                    except StopAsyncIteration:
                        break
                    yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                    pending = asyncio.create_task(anext(stream))
            except Exception:
                logging.getLogger(__name__).exception("Chat stream failed")
                yield 'event: error\ndata: {"detail":"응답 생성 중 오류가 발생했습니다. 다시 시도해 주세요."}\n\n'
            finally:
                if pending is not None:
                    pending.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await pending

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """웹 서버와 별개로 Ollama 연결 가능 여부를 확인한다."""
    ollama_ok = await request.app.state.ollama.is_available()
    return HealthResponse(
        status="ok" if ollama_ok else "degraded",
        ollama=ollama_ok,
        mcp_servers=len(request.app.state.settings.mcp_servers),
        model=request.app.state.settings.ollama_model,
    )


@router.get("/mcp/tools")
async def list_mcp_tools(request: Request) -> dict[str, object]:
    """MCP 서버가 광고한 도구 중 허용 목록을 통과한 도구만 반환한다."""
    try:
        tools = await request.app.state.mcp.list_tools()
        return {"tools": [{
            "server": tool.server,
            "name": tool.name,
            "qualified_name": tool.qualified_name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        } for tool in tools]}
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"MCP unavailable: {exc}") from exc


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    """대화 요청을 처리하고 하위 서비스 오류를 적절한 HTTP 상태로 변환한다."""
    try:
        return await service.run(payload.messages, payload.use_tools, payload.model)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Ollama is unavailable") from exc
    except (ToolValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="Tool execution timed out") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
