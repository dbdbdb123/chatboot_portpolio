"""대화 조율에 필요한 최소 추론 인터페이스."""

from collections.abc import AsyncGenerator
from typing import Any, Protocol


class ChatModel(Protocol):
    """대화 서비스가 사용하는 최소 모델 스트리밍 인터페이스.

    모델명·대화·도구 스키마·Thinking 선택을 받아 메시지 조각을 생성한다.
    서비스는 조각의 content·thinking·tool_calls를 누적하며 소비 중단 시 생성기를 닫는다.
    구현체는 닫을 수 있는 비동기 생성기와 적절한 오류·자원 정리 동작을 제공해야 한다.
    HTTP 클라이언트 생성이나 앱 종료용 close는 이 계약에 요구하지 않는다.
    """

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """입력 대화에 대한 모델 메시지 조각을 생성하는 추론 계약.

        model·messages·tools·think를 받아 content·thinking·tool_calls를 포함할 수 있는
        메시지 사전을 순차적으로 제공한다. 도구 선택은 모델 결과로 표현한다.
        구현체는 소비자가 aclose할 수 있는 비동기 생성기를 반환하고 중단 시 자원을 정리한다.
        HTTP 프레임 대신 모델 메시지를 전달하며 추론 실패는 호출부가 처리하도록 알린다.
        """
        ...
