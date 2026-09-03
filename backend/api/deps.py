"""FastAPI 의존성 주입 함수."""

from fastapi import Request

from backend.services.chat import ChatService


def get_chat_service(request: Request) -> ChatService:
    """앱 시작 시 생성한 ChatService 인스턴스를 요청 핸들러에 제공한다."""
    return request.app.state.chat_service
