"""LangChain ChatOllama 모델과 상태 확인용 HTTP 클라이언트를 조립한다."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_ollama import ChatOllama

from backend.schemas.generation import GenerationOptions


class OllamaClient:
    """프로젝트 설정을 공식 LangChain ``ChatOllama`` 호출로 변환하는 어댑터.

    서비스에는 표준 메시지만 노출한다. 상태 확인에는 작은 HTTP 클라이언트를 유지하지만,
    채팅 요청과 NDJSON 스트림 파싱은 모두 ``langchain-ollama``에 위임한다.
    """

    def __init__(self, base_url: str, timeout_seconds: float,
                 options: GenerationOptions | None = None,
                 callbacks: list[BaseCallbackHandler] | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._options = (options or GenerationOptions()).model_copy(deep=True)
        self._callbacks = list(callbacks or [])
        self._health_client = httpx.AsyncClient(
            base_url=self._base_url, timeout=timeout_seconds
        )

    @property
    def options(self) -> GenerationOptions:
        """호출자가 내부 설정을 변경하지 못하도록 생성 옵션 복사본을 반환한다."""
        return self._options.model_copy(deep=True)

    def _model(self, model: str, think: bool) -> ChatOllama:
        """요청별 모델명과 reasoning 선택을 반영한 LangChain 채팅 모델을 만든다."""
        return ChatOllama(
            model=model,
            base_url=self._base_url,
            reasoning=think,
            async_client_kwargs={"timeout": self._timeout_seconds},
            **self._options.model_dump(exclude_none=True),
        )

    async def is_available(self) -> bool:
        """Ollama 모델 목록 API가 응답하는지 확인한다."""
        try:
            response = await self._health_client.get("/api/tags")
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def chat(self, model: str, messages: list[BaseMessage],
                   tools: list[Any] | None = None, think: bool = False) -> AIMessage:
        """LangChain 모델을 비동기로 호출해 표준 ``AIMessage``를 반환한다."""
        runnable = self._model(model, think)
        if tools:
            runnable = runnable.bind_tools(tools)
        config = self._run_config()
        if config is None:
            return await runnable.ainvoke(messages)
        return await runnable.ainvoke(messages, config=config)

    async def stream_chat(
        self, model: str, messages: list[BaseMessage],
        tools: list[Any] | None = None, think: bool = False,
    ) -> AsyncIterator[AIMessageChunk]:
        """LangChain 네이티브 비동기 스트림에서 표준 메시지 조각을 전달한다."""
        runnable = self._model(model, think)
        if tools:
            runnable = runnable.bind_tools(tools)
        config = self._run_config()
        if config is None:
            async for chunk in runnable.astream(messages):
                yield chunk
        else:
            async for chunk in runnable.astream(messages, config=config):
                yield chunk

    def _run_config(self) -> dict[str, Any] | None:
        """LangChain 관측 콜백이 설정된 경우 요청별 실행 구성으로 전달한다."""
        if not self._callbacks:
            return None
        return {
            "callbacks": self._callbacks,
            "run_name": "mori-ollama-chat",
            "tags": ["mori", "ollama"],
        }

    async def close(self) -> None:
        """상태 확인에 사용하는 HTTP 연결 풀을 닫는다."""
        await self._health_client.aclose()
