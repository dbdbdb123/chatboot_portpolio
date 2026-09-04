"""HTTP 요청과 응답에 사용되는 Pydantic 스키마."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from backend.constants.chat import MAX_CHAT_MESSAGES
from backend.constants.enums import HealthStatus, MessageRole
from backend.images import ImageAttachment


class ChatMessage(BaseModel):
    """대화 이력에 포함되는 역할과 텍스트를 담는 단일 메시지 모델.

    role은 MessageRole로 검증하고 외부 JSON에는 기존 문자열 값으로 직렬화한다.
    content는 메시지 본문이며 이미지 데이터나 도구 호출 세부 정보는 담지 않는다.
    첨부는 ChatRequest에서 받고 모델 입력을 구성할 때 별도로 연결한다.
    """

    role: MessageRole
    content: str


class ChatRequest(BaseModel):
    """일반 응답 API와 SSE API가 공유하는 채팅 요청 계약.

    messages는 클라이언트가 보낸 대화 이력이며 공통 최대 개수 제한을 적용한다.
    use_tools는 도구 사용, think는 모델 추론 모드를 선택하고 model 생략 시
    서비스의 기본 모델을 사용한다. image는 현재 요청에 포함할 단일 첨부다.
    첨부가 있으면 마지막 메시지는 사용자 역할이어야 한다.
    이 모델은 대화 저장이나 요청 모델의 별도 허용 목록 검증을 수행하지 않는다.
    """

    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    use_tools: bool = True
    think: bool = False
    model: str | None = None
    image: ImageAttachment | None = None

    @model_validator(mode="after")
    def image_requires_user(self) -> Self:
        """첨부가 마지막 사용자 메시지에 연결되는 요청인지 확인한다.

        messages의 최소 개수 검증이 끝난 뒤 마지막 역할을 확인한다.
        첨부가 없거나 마지막 역할이 USER이면 현재 요청 객체를 반환하고,
        첨부가 있는데 다른 역할이면 ValueError를 발생시킨다.
        메시지 순서를 변경하거나 첨부를 다른 메시지로 이동하지 않는다.
        """
        if self.image and self.messages[-1].role != MessageRole.USER:
            raise ValueError("이미지는 마지막 사용자 메시지에 첨부해야 합니다.")
        return self


class ToolActivity(BaseModel):
    """도구 실행 후 사용자 화면에 공개할 요약 데이터.

    server와 name은 실행 대상을 식별하고 arguments는 정책이 정한 공개용 인자다.
    OCR의 경우 실제 Base64 대신 파일명과 MIME만 기록한다.
    is_error는 도구 결과의 실패 상태이며 전체 대화의 완료 여부를 의미하지 않는다.
    모델 자체가 인자를 마스킹하지 않으므로 생성자가 안전한 공개값을 제공해야 한다.
    """

    server: str
    name: str
    arguments: dict[str, Any]
    is_error: bool = False


class ChatResponse(BaseModel):
    """채팅 처리가 완료됐을 때 반환하는 최종 결과 모델.

    message는 최종 모델 답변, model은 실제 선택한 모델명,
    tools는 해당 요청에서 실행된 도구의 공개용 요약 목록이다.
    일반 API는 이 객체를 반환하고 SSE는 같은 구조를 done 이벤트에 포함한다.
    중간 추론 문장이나 thinking 원문 전체를 반환하는 데이터 구조는 아니다.
    """

    message: ChatMessage
    model: str
    tools: list[ToolActivity] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """웹 앱에서 확인한 추론 서버 응답 여부와 구성 상태를 표현한다.

    ollama는 모델 목록 API의 접근 가능 여부이며 status는 이를 기반으로 결정한다.
    mcp_servers는 설정에 등록된 서버 수, model은 설정된 기본 모델명이다.
    MCP 연결 성공, 모델 다운로드 완료 또는 실제 추론 성공까지 보장하지 않는다.
    """

    status: HealthStatus
    ollama: bool
    mcp_servers: int
    model: str
