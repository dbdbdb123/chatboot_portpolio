"""HTTP 요청과 응답에 사용되는 Pydantic 스키마."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Ollama 대화 형식과 호환되는 단일 메시지."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatRequest(BaseModel):
    """클라이언트가 보내는 대화 요청."""
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    use_tools: bool = True
    model: str | None = None


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
    status: Literal["ok", "degraded"]
    ollama: bool
    mcp_servers: int
    model: str
