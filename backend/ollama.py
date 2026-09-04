"""Ollama REST API의 비동기 클라이언트."""

from __future__ import annotations

from typing import Any
from collections.abc import AsyncIterator
import json

import httpx


class OllamaClient:
    """연결 재사용과 공통 제한 시간을 관리하는 얇은 HTTP 어댑터."""
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

    async def is_available(self) -> bool:
        """모델 목록 엔드포인트로 Ollama 프로세스의 응답 여부를 확인한다."""
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
    ) -> dict[str, Any]:
        """비스트리밍 채팅 요청을 보내고 assistant 메시지만 반환한다."""
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "think": think}
        if tools:
            payload["tools"] = tools
        response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()
        return dict(response.json()["message"])

    async def close(self) -> None:
        await self._client.aclose()

    async def stream_chat(
        self, model: str, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True, "think": think}
        if tools:
            payload["tools"] = tools
        async with self._client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise RuntimeError("Ollama stream failed")
                if chunk.get("message"):
                    yield chunk["message"]
                if chunk.get("done"):
                    return
        raise RuntimeError("Ollama stream ended before completion")
