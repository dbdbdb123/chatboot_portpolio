"""대화 이력 전달과 요청 사이 격리를 검증한다."""

from backend.schemas import ChatMessage
from backend.services.context import build_history


def test_plain_chat_keeps_system_prompt_and_previous_turns():
    messages = [
        ChatMessage(role="user", content='내 이름은 민수야. 설정은 {"theme": "dark"}'),
        ChatMessage(role="assistant", content="알겠습니다, 민수님."),
        ChatMessage(role="user", content="내 이름이 뭐였지?"),
    ]
    original = [message.model_dump() for message in messages]
    history = build_history(messages, [], None)
    assert history[0]["role"] == "system"
    assert "You are Mori" in history[0]["content"]
    assert "preceding conversation" in history[0]["content"]
    assert history[1:] == original
    assert [message.model_dump() for message in messages] == original


def test_separate_requests_do_not_share_memories():
    build_history([ChatMessage(role="user", content="비밀 이름 민수")], [], None)
    history = build_history([ChatMessage(role="user", content="안녕")], [], None)
    assert len(history) == 2
    assert "민수" not in str(history)


def test_existing_system_and_tool_roles_are_preserved():
    messages = [
        ChatMessage(role="system", content="답변은 한국어로 해줘"),
        ChatMessage(role="tool", content="문서 내용 {history}"),
        ChatMessage(role="user", content="요약해줘"),
    ]
    assert build_history(messages, [], None)[1:] == [m.model_dump() for m in messages]
