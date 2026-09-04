"""API와 내부 처리에서 공유하는 고정 선택값. 문자열 직렬화 값을 유지한다."""

from enum import StrEnum


class MessageRole(StrEnum):
    """대화 메시지에서 허용하는 system·user·assistant·tool 역할.

    Pydantic 요청 검증과 모델 입력 구성에 공통으로 사용한다.
    StrEnum이므로 JSON 직렬화 값은 기존 역할 문자열과 동일하다.
    멤버 값을 변경하면 외부 API 계약도 달라진다.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class StreamEvent(StrEnum):
    """채팅 SSE의 모델·추론 라운드·답변 조각·도구·완료·오류 이벤트 종류.

    서비스는 이벤트를 생성하고 전송 계층은 문자열 값으로 프레임을 구성한다.
    외부 프로토콜 값이므로 변경 시 프런트엔드 constants.js와 소비 코드를 함께 확인한다.
    done을 받기 전 연결 종료는 클라이언트에서 미완료로 취급한다.
    """

    MODEL = "model"
    ROUND = "round"
    DELTA = "delta"
    TOOL = "tool"
    DONE = "done"
    ERROR = "error"


class MCPTransport(StrEnum):
    """설정에서 선택할 수 있는 stdio와 Streamable HTTP 전송 방식.

    MCPServerConfig가 입력 문자열을 이 Enum으로 정규화한다.
    게이트웨이는 선택한 방식에 맞는 연결을 만들며 각 방식의 필수 설정은
    설정 객체에서 별도로 검증한다. 새로운 값 추가만으로 전송 구현이 생기지는 않는다.
    """

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class HealthStatus(StrEnum):
    """상태 조회 API가 사용하는 ok와 degraded 상태 구분.

    현재는 Ollama 모델 목록 API의 접근 가능 여부로 결정한다.
    전체 시스템의 준비 상태나 MCP의 정상 동작을 나타내는 종합 상태는 아니다.
    StrEnum을 사용해 응답의 기존 문자열 값을 유지한다.
    """

    OK = "ok"
    DEGRADED = "degraded"
