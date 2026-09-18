"""Redis-backed chat session HTTP routes."""

from fastapi import APIRouter, HTTPException, Request

from backend.schemas.history import ChatSessionMessages, ChatSessionSummary
from backend.services.history import RedisChatHistoryStore

router = APIRouter()


def history_store(request: Request) -> RedisChatHistoryStore:
    store = getattr(request.app.state, "history_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="대화 기록 저장소가 설정되지 않았습니다.")
    return store


@router.post("/chat/sessions", response_model=ChatSessionSummary)
async def create_chat_session(request: Request) -> ChatSessionSummary:
    return await history_store(request).create_session()


@router.get("/chat/sessions", response_model=list[ChatSessionSummary])
async def list_chat_sessions(request: Request) -> list[ChatSessionSummary]:
    return await history_store(request).list_sessions()


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionMessages)
async def read_chat_session(session_id: str, request: Request) -> ChatSessionMessages:
    try:
        return await history_store(request).get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str, request: Request) -> dict[str, str]:
    if not await history_store(request).delete_session(session_id):
        raise HTTPException(status_code=404, detail="대화 세션을 찾을 수 없습니다.")
    return {"deleted": session_id}
