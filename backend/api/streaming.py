"""대화 이벤트를 HTTP Server-Sent Events 형식으로 변환한다."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, suppress

from backend.constants.chat import (
    SSE_KEEP_ALIVE_FRAME,
    SSE_KEEP_ALIVE_SECONDS,
    STREAM_ERROR_MESSAGE,
)
from backend.constants.enums import StreamEvent
from backend.models import ChatRequest
from backend.services.chat import ChatService

logger = logging.getLogger(__name__)


async def chat_events(payload: ChatRequest, service: ChatService) -> AsyncIterator[str]:
    """대화 이벤트를 SSE로 직렬화하고 대기 신호·오류·취소 정리를 처리한다."""
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
