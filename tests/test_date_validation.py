import pytest
from langchain_core.messages import AIMessageChunk

from backend.schemas import ChatMessage
from backend.services.chat import ChatService
from backend.services.date_validation import validate_date_answer
from backend.services.tool_policy import OCRToolPolicy
from backend.services.tools import ToolExecutor
from fakes import FakeMCP


@pytest.mark.parametrize(("answer", "expected"), [
    ("2026 년 9 월 25 일 (토요일) 입니다.", "2026 년 9 월 25 일 (금요일) 입니다."),
    ("2026년 9월 25일은 토요일입니다.", "2026년 9월 25일은 금요일입니다."),
    ("2024년 2월 29일은 월요일입니다.", "2024년 2월 29일은 목요일입니다."),
    ("2026년 9월 16일은 수요일입니다.", "2026년 9월 16일은 수요일입니다."),
])
def test_corrects_explicit_weekday_assertions(answer, expected):
    assert validate_date_answer(answer) == expected


@pytest.mark.parametrize("answer", [
    "25일은 토요일입니다.",
    "2026년 9월 25일은 토요일이 아닙니다.",
    '"2026년 9월 25일은 토요일입니다."라고 썼습니다.',
    "`2026년 9월 25일은 토요일입니다.`",
    "음력 2026년 9월 25일은 토요일입니다.",
    "2026년 2월 30일은 토요일입니다.",
])
def test_does_not_guess_or_rewrite_non_assertions(answer):
    assert validate_date_answer(answer) == answer


@pytest.mark.asyncio
@pytest.mark.parametrize("use_tools", [True, False])
async def test_wrong_weekday_never_reaches_stream_even_without_tool_call(use_tools):
    class WrongWeekdayModel:
        async def stream_chat(self, *args):
            yield AIMessageChunk(content="2026 년 9 월 25 일 (토")
            yield AIMessageChunk(content="요일) 입니다.")

    mcp = FakeMCP()
    policy = OCRToolPolicy()
    service = ChatService(
        WrongWeekdayModel(), mcp, "test", 1,
        tool_executor=ToolExecutor(mcp, policy), tool_policy=policy,
    )
    messages = [
        ChatMessage(role="user", content="내일은?"),
        ChatMessage(role="assistant", content="2026년 9월 16일은 수요일입니다."),
        ChatMessage(role="user", content="2026년 9월 25일은 무슨 요일이야?"),
    ]
    events = [event async for event in service.stream(messages, use_tools, None)]
    visible = "".join(e["data"]["text"] for e in events if e["event"] == "delta")
    assert visible == "2026 년 9 월 25 일 (금요일) 입니다."
    assert events[-1]["data"]["message"]["content"] == visible


@pytest.mark.asyncio
async def test_followup_uses_requested_day_and_never_asks_model_to_rewrite():
    from datetime import UTC, datetime
    from backend.tools.datetime_tool import DateTimeTool
    from backend.tools.registry import InternalToolRegistry

    class DateClient:
        registry = InternalToolRegistry([
            DateTimeTool(lambda: datetime(2026, 9, 15, 6, tzinfo=UTC)),
        ])

        async def list_tools(self):
            return [DateTimeTool().definition]

        async def call_tool(self, server, name, arguments):
            assert server == "internal"
            return await self.registry.call_tool(server, name, arguments)

    class UnusedModel:
        async def stream_chat(self, *args):
            pytest.fail("simple date followups must not be rewritten by a model")
            yield AIMessageChunk(content="")

    client = DateClient()
    policy = OCRToolPolicy()
    service = ChatService(UnusedModel(), client, "test", 1,
        tool_executor=ToolExecutor(client, policy), tool_policy=policy)
    messages = [ChatMessage(role="assistant", content="오늘은 2025년 12월 19일입니다.")]
    for question, day, weekday, offset in [
        ("오늘은 몇일?", 15, "화요일", 0),
        ("내일은 몇요일?", 16, "수요일", 1),
        ("어제는?", 14, "월요일", -1),
    ]:
        messages.append(ChatMessage(role="user", content=question))
        result = await service.run(messages, True, None)
        assert result.message.content == f"2026년 9월 {day}일은 {weekday}입니다."
        assert result.tools[0].arguments == {"offset_days": offset}
        messages.append(result.message)
    for day, weekday in [(25, "금요일"), (17, "목요일")]:
        messages.append(ChatMessage(role="user", content=f"{day}일은?"))
        result = await service.run(messages, True, None)
        assert result.message.content == f"2026년 9월 {day}일은 {weekday}입니다."
        assert result.tools[0].arguments == {"value": f"2026-09-{day}"}
        messages.append(result.message)


@pytest.mark.parametrize(("context", "question", "value"), [
    ("2026년 9월 15일입니다.", "25일은?", "2026-09-25"),
    ("2026년 9월 17일은 목요일입니다.", "17일은?", "2026-09-17"),
    ("2024-02-10", "29일은?", "2024-02-29"),
    ("2026년 2월 10일", "30일은?", None),
    ("2026년 9월과 2026년 10월", "25일은?", None),
    ("안녕하세요", "25일은?", None),
    ("음력 2026년 9월 15일", "25일은?", None),
])
def test_followup_context_and_invalid_dates(context, question, value):
    from backend.services.date_validation import resolve_date_followup
    result = resolve_date_followup([
        ChatMessage(role="assistant", content=context),
        ChatMessage(role="user", content=question),
    ])
    assert result.value == value
    assert bool(result.clarification) == (value is None)


@pytest.mark.parametrize("question", [
    "내일 서울 날씨는?", "오늘 할 일을 정리해줘", "내일은 영어로 뭐야?",
    "뉴욕 기준 오늘은 며칠?", "2025년 12월 19일을 오늘로 가정하면 내일은?",
])
def test_relative_date_route_does_not_capture_other_requests(question):
    from backend.services.date_validation import resolve_date_followup
    assert resolve_date_followup([ChatMessage(role="user", content=question)]) is None
