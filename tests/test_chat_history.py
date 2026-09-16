"""Redis 대화 기록의 세션 격리와 메시지별 3일 보관 정책을 검증한다."""

from datetime import UTC, datetime, timedelta

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage

from backend.schemas import ChatMessage
from backend.schemas import ChatRequest
from backend.api.routes import _hydrate_session_messages
from backend.services.history import RedisChatHistoryStore


class FakePipeline:
    """테스트에 필요한 Redis pipeline 명령만 순서대로 실행하는 작은 대역이다."""

    def __init__(self, redis) -> None:
        self.redis = redis
        self.commands = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def zremrangebyscore(self, *args):
        self.commands.append((self.redis.zremrangebyscore, args))

    def zadd(self, *args):
        self.commands.append((self.redis.zadd, args))

    def hset(self, *args, **kwargs):
        self.commands.append((self.redis.hset, args, kwargs))

    async def execute(self):
        for command in self.commands:
            function, args, *kwargs = command
            await function(*args, **(kwargs[0] if kwargs else {}))


class FakeRedis:
    """외부 Redis 서버 없이 저장소의 키·정렬 집합 동작을 검증하는 메모리 대역이다."""

    def __init__(self) -> None:
        self.hashes = {}
        self.sorted_sets = {}

    async def hset(self, key, field=None, value=None, *, mapping=None):
        target = self.hashes.setdefault(key, {})
        if mapping is not None:
            target.update(mapping)
        else:
            target[field] = value

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def exists(self, key):
        return int(key in self.hashes or key in self.sorted_sets)

    async def zadd(self, key, mapping):
        self.sorted_sets.setdefault(key, {}).update(mapping)

    async def zremrangebyscore(self, key, minimum, maximum):
        lower = float("-inf") if minimum == "-inf" else float(minimum)
        target = self.sorted_sets.setdefault(key, {})
        for member, score in list(target.items()):
            if lower <= score <= float(maximum):
                del target[member]

    async def zrange(self, key, start, end):
        values = sorted(self.sorted_sets.get(key, {}).items(), key=lambda item: item[1])
        return [member for member, _score in values]

    async def zrevrange(self, key, start, end):
        values = sorted(
            self.sorted_sets.get(key, {}).items(), key=lambda item: item[1], reverse=True
        )
        return [member for member, _score in values]

    async def zrem(self, key, member):
        self.sorted_sets.get(key, {}).pop(member, None)

    async def delete(self, *keys):
        deleted = 0
        for key in keys:
            deleted += int(self.hashes.pop(key, None) is not None)
            deleted += int(self.sorted_sets.pop(key, None) is not None)
        return deleted

    def pipeline(self, transaction=True):
        return FakePipeline(self)


async def test_only_messages_older_than_three_days_are_removed():
    current = [datetime(2026, 1, 1, tzinfo=UTC)]
    store = RedisChatHistoryStore(FakeRedis(), now=lambda: current[0])
    session = await store.create_session()

    await store.append_exchange(
        session.id,
        ChatMessage(role="user", content="첫 질문"),
        ChatMessage(role="assistant", content="첫 답변"),
    )
    current[0] += timedelta(days=2)
    await store.append_exchange(
        session.id,
        ChatMessage(role="user", content="최근 질문"),
        ChatMessage(role="assistant", content="최근 답변"),
    )

    # 첫 교환은 4일이 지나 제거되지만 두 번째 교환은 2일밖에 지나지 않아 남아야 한다.
    current[0] += timedelta(days=2)
    history = await store.get_session(session.id)
    assert [message.content for message in history.messages] == ["최근 질문", "최근 답변"]
    assert history.session.message_count == 2


async def test_sessions_keep_their_messages_separate():
    store = RedisChatHistoryStore(FakeRedis())
    first = await store.create_session()
    second = await store.create_session()
    await store.append_exchange(
        first.id, ChatMessage(role="user", content="A"),
        ChatMessage(role="assistant", content="A 답변"),
    )

    assert (await store.get_session(first.id)).session.message_count == 2
    assert (await store.get_session(second.id)).session.message_count == 0


async def test_session_history_implements_langchain_async_contract():
    """세션 어댑터가 LangChain 메시지를 저장하고 같은 표준 타입으로 복원한다."""
    store = RedisChatHistoryStore(FakeRedis())
    session = await store.create_session()
    history = store.history(session.id)
    assert isinstance(history, BaseChatMessageHistory)

    await history.aadd_messages([
        HumanMessage(content="질문"), AIMessage(content="답변"),
    ])
    restored = await history.aget_messages()
    assert [(message.type, message.text) for message in restored] == [
        ("human", "질문"), ("ai", "답변"),
    ]


async def test_second_session_request_restores_saved_messages_before_current_question():
    """첫 답변 저장 후 두 번째 요청에서 Redis 문맥과 현재 질문을 안전하게 합친다."""
    store = RedisChatHistoryStore(FakeRedis())
    session = await store.create_session()
    await store.history(session.id).aadd_messages([
        HumanMessage(content="오늘은 몇일이야?"),
        AIMessage(content="2026년 9월 16일은 수요일입니다."),
    ])
    payload = ChatRequest(
        session_id=session.id,
        messages=[ChatMessage(role="user", content="오늘은 몇일이라고?")],
    )

    restored = await _hydrate_session_messages(store, payload)

    assert [(message.role, message.content) for message in restored.messages] == [
        ("user", "오늘은 몇일이야?"),
        ("assistant", "2026년 9월 16일은 수요일입니다."),
        ("user", "오늘은 몇일이라고?"),
    ]
