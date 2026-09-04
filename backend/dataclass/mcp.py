"""MCP SDK 타입을 애플리케이션 내부 표현으로 변환한 데이터 클래스."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.constants.app import TOOL_NAME_SEPARATOR


@dataclass(frozen=True, slots=True)
class MCPTool:
    """서버 정보와 입력 스키마가 결합된 호출 가능한 MCP 도구."""

    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """서로 다른 서버의 동명 도구가 충돌하지 않는 모델 노출 이름."""
        return f"{self.server}{TOOL_NAME_SEPARATOR}{self.name}"

    def as_ollama_tool(self) -> dict[str, Any]:
        """Ollama `/api/chat`이 받는 function-tool 형식으로 변환한다."""
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
    """전송 방식이나 SDK 버전에 의존하지 않는 도구 실행 결과."""

    content: list[dict[str, Any]] = field(default_factory=list)
    structured_content: dict[str, Any] | None = None
    is_error: bool = False
