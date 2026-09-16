"""대화 조율 계층에서 사용하는 LangChain 모델 인터페이스."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage


class ChatModel(Protocol):
    """ChatService가 공급자 구현과 분리된 채 LangChain 메시지로 추론하는 계약."""

    async def chat(
        self, model: str, messages: list[BaseMessage],
        tools: list[Any] | None = None, think: bool = False,
    ) -> AIMessage: ...

    def stream_chat(
        self, model: str, messages: list[BaseMessage],
        tools: list[Any] | None = None, think: bool = False,
    ) -> AsyncIterator[AIMessageChunk]: ...
