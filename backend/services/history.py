"""Redis를 사용하는 세션별 대화 기록 저장소."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ChatMessage as LangChainChatMessage,
    HumanMessage,
)
from redis.asyncio import Redis

from backend.constants.history import CHAT_HISTORY_KEY_PREFIX, CHAT_MESSAGE_RETENTION
from backend.schemas import ChatMessage
from backend.schemas.history import ChatSessionMessages, ChatSessionSummary, StoredChatMessage


class RedisChatHistoryStore:
    """메시지별 생성 시각을 기준으로 3일 보관하는 Redis 저장소.

    메시지는 세션별 Sorted Set에 JSON으로 저장하며 score에는 Unix 시간을 사용한다.
    이 구조는 ``ZREMRANGEBYSCORE``로 기준 시각 이전 메시지만 제거할 수 있으므로,
    세션 키 전체에 TTL을 거는 방식과 달리 최근 메시지가 오래된 메시지와 함께 사라지지 않는다.
    세션 제목과 생성 시각은 별도 Hash, 세션 정렬 순서는 공통 Sorted Set에 저장한다.
    """

    def __init__(self, redis: Redis, *, now=None) -> None:
        self._redis = redis
        # 테스트에서는 고정 시계를 주입할 수 있고 운영에서는 UTC 현재 시각을 사용한다.
        self._now = now or (lambda: datetime.now(UTC))

    def _messages_key(self, session_id: str) -> str:
        return f"{CHAT_HISTORY_KEY_PREFIX}:session:{session_id}:messages"

    def _metadata_key(self, session_id: str) -> str:
        return f"{CHAT_HISTORY_KEY_PREFIX}:session:{session_id}:metadata"

    @property
    def _sessions_key(self) -> str:
        return f"{CHAT_HISTORY_KEY_PREFIX}:sessions"

    def _cutoff_timestamp(self) -> float:
        return (self._now() - CHAT_MESSAGE_RETENTION).timestamp()

    async def close(self) -> None:
        """애플리케이션 종료 시 Redis 연결 풀을 닫는다."""
        await self._redis.aclose()

    async def ping(self) -> None:
        """설정된 Redis 서버에 실제로 연결할 수 있는지 확인한다."""
        await self._redis.ping()

    async def create_session(self, title: str = "새 대화") -> ChatSessionSummary:
        """UUID 세션을 만들고 목록 정렬에 사용할 생성·수정 시각을 기록한다."""
        now = self._now()
        session_id = str(uuid4())
        await self._redis.hset(self._metadata_key(session_id), mapping={
            "title": title.strip()[:80] or "새 대화",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })
        await self._redis.zadd(self._sessions_key, {session_id: now.timestamp()})
        return ChatSessionSummary(
            id=session_id, title=title.strip()[:80] or "새 대화",
            created_at=now, updated_at=now, message_count=0,
        )

    async def _remove_expired_messages(self, session_id: str) -> None:
        """해당 세션에서 현재 시각 기준 3일을 지난 메시지만 제거한다."""
        await self._redis.zremrangebyscore(
            self._messages_key(session_id), "-inf", self._cutoff_timestamp()
        )

    async def append_exchange(
        self, session_id: str, user_message: ChatMessage, assistant_message: ChatMessage,
    ) -> None:
        """한 번의 정상 완료 요청에서 사용자 질문과 모델 답변을 순서대로 저장한다."""
        await self.add_messages(session_id, [
            HumanMessage(content=user_message.content),
            AIMessage(content=assistant_message.content),
        ])

    async def add_messages(self, session_id: str, messages: list[BaseMessage]) -> None:
        """LangChain 메시지를 한 번의 Redis 트랜잭션으로 세션에 추가한다."""
        now = self._now()
        metadata_key = self._metadata_key(session_id)
        if not await self._redis.exists(metadata_key):
            raise KeyError("대화 세션을 찾을 수 없습니다.")

        # 같은 내용이 반복되어도 Sorted Set member가 겹치지 않도록 메시지마다 UUID를 포함한다.
        members: dict[str, float] = {}
        for offset, message in enumerate(messages):
            created_at = now.timestamp() + offset / 1_000_000
            stored = StoredChatMessage(
                id=str(uuid4()), role=_message_role(message), content=message.text,
                created_at=datetime.fromtimestamp(created_at, UTC),
            )
            members[stored.model_dump_json()] = created_at

        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.zremrangebyscore(
                self._messages_key(session_id), "-inf", self._cutoff_timestamp()
            )
            pipeline.zadd(self._messages_key(session_id), members)
            pipeline.hset(metadata_key, mapping={"updated_at": now.isoformat()})
            pipeline.zadd(self._sessions_key, {session_id: now.timestamp()})
            await pipeline.execute()

        # 첫 사용자 질문을 세션 제목으로 사용하되 긴 본문은 사이드바에 맞게 자른다.
        first_human = next((message for message in messages if isinstance(message, HumanMessage)), None)
        metadata = await self._redis.hgetall(metadata_key)
        if first_human is not None and metadata.get("title") == "새 대화":
            await self._redis.hset(
                metadata_key, "title", first_human.text.strip()[:80] or "새 대화"
            )

    async def get_session(self, session_id: str) -> ChatSessionMessages:
        """만료 메시지를 정리한 뒤 세션 메타데이터와 남은 메시지를 시간순으로 반환한다."""
        await self._remove_expired_messages(session_id)
        metadata = await self._redis.hgetall(self._metadata_key(session_id))
        if not metadata:
            raise KeyError("대화 세션을 찾을 수 없습니다.")
        raw_messages = await self._redis.zrange(self._messages_key(session_id), 0, -1)
        messages = [StoredChatMessage.model_validate(json.loads(item)) for item in raw_messages]
        summary = ChatSessionSummary(
            id=session_id,
            title=metadata["title"],
            created_at=datetime.fromisoformat(metadata["created_at"]),
            updated_at=datetime.fromisoformat(metadata["updated_at"]),
            message_count=len(messages),
        )
        return ChatSessionMessages(session=summary, messages=messages)

    async def list_sessions(self) -> list[ChatSessionSummary]:
        """최근 활동 순서로 세션을 조회하며 각 세션의 만료 메시지를 먼저 정리한다."""
        session_ids = await self._redis.zrevrange(self._sessions_key, 0, -1)
        sessions = []
        for session_id in session_ids:
            try:
                sessions.append((await self.get_session(session_id)).session)
            except KeyError:
                # 메타데이터가 수동 삭제된 고아 항목은 세션 색인에서도 제거한다.
                await self._redis.zrem(self._sessions_key, session_id)
        return sessions

    async def delete_session(self, session_id: str) -> bool:
        """사용자가 명시적으로 삭제한 세션의 메타데이터와 모든 메시지를 제거한다."""
        deleted = await self._redis.delete(
            self._metadata_key(session_id), self._messages_key(session_id)
        )
        await self._redis.zrem(self._sessions_key, session_id)
        return bool(deleted)

    def history(self, session_id: str) -> "RedisSessionMessageHistory":
        """현재 저장소를 공유하는 LangChain 세션 히스토리 객체를 반환한다."""
        return RedisSessionMessageHistory(self, session_id)


def _message_role(message: BaseMessage) -> str:
    """LangChain 구체 메시지 타입을 외부 API와 공유하는 역할 문자열로 변환한다."""
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    return message.type if message.type in {"system", "tool"} else "assistant"


def _stored_to_langchain(message: StoredChatMessage) -> BaseMessage:
    """Redis 조회 모델을 LangChain이 모델 입력과 메모리에 사용하는 메시지로 복원한다."""
    if message.role == "user":
        return HumanMessage(content=message.content, id=message.id)
    if message.role == "assistant":
        return AIMessage(content=message.content, id=message.id)
    return LangChainChatMessage(
        role=message.role.value, content=message.content, id=message.id
    )


class RedisSessionMessageHistory(BaseChatMessageHistory):
    """세션 하나를 LangChain ``BaseChatMessageHistory`` 계약으로 노출한다.

    운영 경로는 비동기 Redis이므로 ``aget_messages``·``aadd_messages``·``aclear``를
    사용한다. 동기 메서드는 이벤트 루프를 중첩하지 않도록 명시적으로 거부한다.
    """

    def __init__(self, store: RedisChatHistoryStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id

    @property
    def messages(self) -> list[BaseMessage]:
        raise RuntimeError("Redis session history must be read asynchronously")

    async def aget_messages(self) -> list[BaseMessage]:
        session = await self.store.get_session(self.session_id)
        return [_stored_to_langchain(message) for message in session.messages]

    def add_messages(self, messages: list[BaseMessage]) -> None:
        raise RuntimeError("Redis session history must be written asynchronously")

    async def aadd_messages(self, messages: list[BaseMessage]) -> None:
        await self.store.add_messages(self.session_id, messages)

    def clear(self) -> None:
        raise RuntimeError("Redis session history must be cleared asynchronously")

    async def aclear(self) -> None:
        await self.store.delete_session(self.session_id)


def create_redis_history_store(url: str) -> RedisChatHistoryStore:
    """문자열 응답으로 디코딩하는 비동기 Redis 클라이언트와 저장소를 생성한다."""
    return RedisChatHistoryStore(Redis.from_url(url, decode_responses=True))
