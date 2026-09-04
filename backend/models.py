"""HTTP 요청과 응답에 사용되는 Pydantic 스키마."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from backend.constants.chat import MAX_CHAT_MESSAGES
from backend.constants.enums import HealthStatus, MessageRole
from backend.images import ImageAttachment


class ChatMessage(BaseModel):
    """Ollama 대화 형식과 호환되는 단일 메시지."""

    role: MessageRole
    content: str


class ChatRequest(BaseModel):
    """클라이언트가 보내는 대화 요청."""

    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    use_tools: bool = True
    think: bool = False
    model: str | None = None
    image: ImageAttachment | None = None

    @model_validator(mode="after")
    def image_requires_user(self) -> Self:
        """이미지가 마지막 사용자 메시지에만 연결되도록 요청 조합을 검증한다."""
        if self.image and self.messages[-1].role != MessageRole.USER:
            raise ValueError("이미지는 마지막 사용자 메시지에 첨부해야 합니다.")
        return self


class ToolActivity(BaseModel):
    """UI에 표시할 MCP 도구 실행 요약."""

    server: str
    name: str
    arguments: dict[str, Any]
    is_error: bool = False


class ChatResponse(BaseModel):
    """최종 모델 응답과 그 과정에서 실행된 도구 목록."""

    message: ChatMessage
    model: str
    tools: list[ToolActivity] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """외부 추론 서버를 포함한 서비스 상태."""

    status: HealthStatus
    ollama: bool
    mcp_servers: int
    model: str
