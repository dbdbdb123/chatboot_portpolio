"""MCP SDK 타입을 애플리케이션 내부 표현으로 변환한 데이터 클래스."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.constants.app import TOOL_NAME_SEPARATOR


@dataclass(frozen=True, slots=True)
class MCPTool:
    """SDK와 독립적으로 도구의 서버·이름·설명·입력 스키마를 표현한다.

    qualified_name은 서버와 도구 이름을 결합해 서버 간 이름 충돌을 구분한다.
    as_ollama_tool은 모델이 사용할 function-tool 구조를 생성한다.
    서버 원본 스키마와 정책이 변환한 모델용 스키마는 별도 객체로 관리한다.
    필드는 재할당할 수 없지만 input_schema 내부 사전은 변경 가능하므로
    공유된 원본 스키마를 직접 수정하지 않는다.
    """

    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """서버와 도구 이름을 공통 구분자로 결합한 모델용 식별자를 반환한다.

        예를 들어 docs 서버의 search는 docs__search로 표현된다.
        원본 server·name 필드를 수정하거나 서버 이름의 유일성을 검증하지 않는다.
        게이트웨이 캐시와 모델 호출 색인에서 같은 식별자를 사용한다.
        """
        return f"{self.server}{TOOL_NAME_SEPARATOR}{self.name}"

    def as_ollama_tool(self) -> dict[str, Any]:
        """현재 도구를 Ollama의 function-tool 입력 사전으로 표현한다.

        qualified_name·description·input_schema를 각각 이름·설명·parameters에 넣는다.
        외부 사전은 새로 만들지만 parameters는 기존 스키마 객체를 참조한다.
        원본 필드를 변경하지 않으며 도구 허용 여부나 입력 스키마를 검증하지 않는다.
        """
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


@dataclass(frozen=True, slots=True)
class MCPToolResult:
    """MCP 전송 방식과 SDK 표현을 숨긴 공통 도구 실행 결과.

    content는 일반 콘텐츠 블록, structured_content는 선택적인 구조화 결과다.
    실행기는 구조화 결과가 비어 있지 않으면 이를 사용하고 그 외에는 content를
    모델에 전달한다. is_error는 도구가 보고한 실패이며 Python 예외와는 구분된다.
    이 객체 자체가 결과 내용을 정제하거나 민감 정보를 제거하지는 않는다.
    """

    content: list[dict[str, Any]] = field(default_factory=list)
    structured_content: dict[str, Any] | None = None
    is_error: bool = False
