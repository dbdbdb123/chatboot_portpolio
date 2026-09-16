"""저장된 대화 세션과 메시지를 외부 API에 전달하는 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field

from backend.constants.enums import MessageRole


class StoredChatMessage(BaseModel):
    """Redis에 저장하고 세션 조회 API로 반환하는 단일 메시지다."""

    id: str
    role: MessageRole
    content: str
    created_at: datetime


class ChatSessionSummary(BaseModel):
    """사이드바 목록에 필요한 세션 메타데이터와 현재 메시지 수다."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = Field(ge=0)


class ChatSessionMessages(BaseModel):
    """선택한 세션 정보와 보관 기간 안에 남아 있는 메시지 목록이다."""

    session: ChatSessionSummary
    messages: list[StoredChatMessage]
