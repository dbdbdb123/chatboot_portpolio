"""API와 내부 처리에서 공유하는 고정 선택값. 문자열 직렬화 값을 유지한다."""

from enum import StrEnum


class MessageRole(StrEnum):
    """모델 대화에 포함할 수 있는 메시지 역할."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class StreamEvent(StrEnum):
    """채팅 SSE가 클라이언트에 전달하는 이벤트 종류."""

    MODEL = "model"
    ROUND = "round"
    DELTA = "delta"
    TOOL = "tool"
    DONE = "done"
    ERROR = "error"


class MCPTransport(StrEnum):
    """지원하는 MCP 연결 방식."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class HealthStatus(StrEnum):
    """서비스 상태 응답에 사용하는 상태값."""

    OK = "ok"
    DEGRADED = "degraded"
