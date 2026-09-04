"""대화 조율에 필요한 최소 추론 인터페이스."""

from collections.abc import AsyncGenerator
from typing import Any, Protocol


class ChatModel(Protocol):
    """구체적인 HTTP 클라이언트와 무관하게 모델 응답 스트림을 제공한다."""

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """응답 조각을 생성하며 소비자가 종료 시 스트림을 닫을 수 있게 한다."""
        ...
