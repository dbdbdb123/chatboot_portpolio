"""Ollama REST API의 비동기 클라이언트."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx


class OllamaClient:
    """Ollama REST API와 NDJSON 스트리밍을 감싸는 비동기 HTTP 클라이언트.

    기본 주소와 요청 제한 시간을 적용한 httpx.AsyncClient를 재사용한다.
    chat은 완성된 모델 메시지를, stream_chat은 생성 중인 메시지 조각을 반환한다.
    스트림의 오류 또는 완료 표시 없는 종료는 예외로 전달하며,
    소비자가 생성기를 닫으면 진행 중인 HTTP 응답도 정리된다.
    클라이언트 연결 풀의 최종 close 호출은 앱 수명주기 관리자가 담당한다.
    """

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        """Ollama 요청에 사용할 재사용 비동기 HTTP 클라이언트를 생성한다.

        base_url 끝의 슬래시를 정리하고 timeout_seconds를 HTTP 제한 시간으로 적용한다.
        이 시점에는 모델 상태 조회나 추론 요청을 보내지 않는다.
        생성한 연결 풀은 이후 요청들이 공유하며 사용 종료 시 close로 정리해야 한다.
        """
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

    async def is_available(self) -> bool:
        """Ollama의 모델 목록 API가 정상 HTTP 응답을 반환하는지 확인한다.

        GET /api/tags 요청과 상태 코드 검사가 성공하면 True를 반환한다.
        httpx.HTTPError는 False로 변환하며 그 외 예외는 그대로 전달한다.
        특정 모델의 설치 여부, 로딩 완료 또는 실제 추론 성공은 확인하지 않는다.
        """
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
        """완성된 응답을 기다리는 일반 채팅 요청을 보낸다.

        model·messages·think와 stream=False를 전달하며 tools가 비어 있지 않을 때만
        도구 스키마를 요청에 포함한다. 성공 응답에서 message 객체를 사전으로 반환한다.
        HTTP 오류와 응답 파싱 오류는 호출부로 전달하며 재시도를 수행하지 않는다.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": think,
        }
        if tools:
            payload["tools"] = tools
        response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()
        return dict(response.json()["message"])

    async def close(self) -> None:
        """재사용 HTTP 클라이언트와 연결 풀을 비동기로 종료한다.

        앱 수명주기 관리자가 최종 정리에 사용하며 반환값은 없다.
        종료 과정의 예외를 삼키지 않고 호출부로 전달한다.
        종료 후 새 요청을 처리하려면 새로운 클라이언트를 구성해야 한다.
        """
        await self._client.aclose()

    async def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Ollama의 NDJSON 응답을 읽어 모델 메시지 조각을 차례로 생성한다.

        model·messages·think와 stream=True를 전송하고 비어 있지 않은 tools를 포함한다.
        빈 줄은 건너뛰고 message가 있으면 먼저 전달한 뒤 done 여부를 확인한다.
        서버 error 또는 done 없이 끝난 연결은 RuntimeError로 처리하며,
        HTTP·JSON 파싱 오류는 그대로 전달한다. 생성기를 닫거나 오류가 발생하면
        진행 중인 HTTP 응답 컨텍스트가 정리된다. thinking 필터링은 상위 계층 책임이다.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": think,
        }
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
