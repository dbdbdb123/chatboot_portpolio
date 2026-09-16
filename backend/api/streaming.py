"""대화 이벤트를 HTTP Server-Sent Events 형식으로 변환한다."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, suppress
from typing import Awaitable, Callable

from backend.constants.chat import (
    SSE_KEEP_ALIVE_FRAME,
    SSE_KEEP_ALIVE_SECONDS,
    STREAM_ERROR_MESSAGE,
)
from backend.constants.enums import StreamEvent
from backend.schemas import ChatRequest, ChatResponse
from backend.services.chat import ChatService

logger = logging.getLogger(__name__)


async def chat_events(
    payload: ChatRequest,
    service: ChatService,
    on_complete: Callable[[ChatResponse], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    """대화 이벤트를 SSE로 직렬화하고 완료 답변의 선택적 저장 콜백을 실행한다."""
    pending = None
    async with aclosing(
        service.stream(
            payload.messages, payload.use_tools, payload.model, payload.think, payload.image
        )
    ) as stream:
        try:
            pending = asyncio.create_task(anext(stream))
            while True:
                ready, _ = await asyncio.wait({pending}, timeout=SSE_KEEP_ALIVE_SECONDS)
                if not ready:
                    yield SSE_KEEP_ALIVE_FRAME
                    continue
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    break
                # DONE은 완성된 답변이 확정된 시점이다. 스트리밍 중간 조각은 저장하지 않아
                # 연결이 끊긴 불완전한 답변이 세션 기록에 남지 않도록 한다.
                if event["event"] == StreamEvent.DONE and on_complete is not None:
                    await on_complete(ChatResponse.model_validate(event["data"]))
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                pending = asyncio.create_task(anext(stream))
        except Exception:
            logger.exception("Chat stream failed")
            error_data = json.dumps({"detail": STREAM_ERROR_MESSAGE}, ensure_ascii=False)
            yield f"event: {StreamEvent.ERROR}\ndata: {error_data}\n\n"
        finally:
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await pending
