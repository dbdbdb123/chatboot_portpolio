import asyncio
import json

import pytest
from langchain_core.messages import AIMessageChunk

from backend.schemas import ChatMessage
from backend.tools.conversation import SearchConversationTool
from backend.tools.knowledge import DocumentStore, ReadKnowledgeTool, SearchKnowledgeTool


@pytest.mark.asyncio
async def test_document_search_read_and_pagination():
    store = DocumentStore({"guide.md": "# Guide\n실행 방법 uv run\n설정 방법\n끝"})
    found = (await SearchKnowledgeTool(store).execute({"query": "실행 UV"})).structured_content
    assert found["matches"][0]["line"] == 2
    read = ReadKnowledgeTool(store)
    result = (await read.execute({"document_id": "guide.md", "start_line": 2, "line_count": 2})).structured_content
    assert result["lines"][0]["text"] == "실행 방법 uv run"
    assert result["next_line"] == 4
    assert (await read.execute({"document_id": "guide.md", "start_line": 4})).structured_content["next_line"] is None
    assert (await SearchKnowledgeTool(store).execute({"query": "missing"})).structured_content["matches"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"query": " "}, {"query": "x", "limit": 21},
    {"query": "x", "limit": True}, {"query": "x", "file": ".env"}])
async def test_search_validation(args):
    with pytest.raises(ValueError):
        await SearchKnowledgeTool(DocumentStore({})).execute(args)


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"document_id": "../secret"},
    {"document_id": "C:/secret.txt"}, {"document_id": "x", "start_line": 0},
    {"document_id": "x", "line_count": 101}, {"document_id": "x", "start_line": 5}])
async def test_read_bounds_and_unregistered_paths(args):
    with pytest.raises(ValueError):
        await ReadKnowledgeTool(DocumentStore({"x": "one"})).execute(args)


def test_file_registration_is_bounded(tmp_path):
    (tmp_path / "readme.md").write_text("hello", encoding="utf-8")
    assert DocumentStore.from_files(tmp_path, ["readme.md"]).read("readme.md") == "hello"
    for name in ["../outside.md", ".env"]:
        with pytest.raises(ValueError):
            DocumentStore.from_files(tmp_path, [name])
    (tmp_path / "large.md").write_bytes(b"x" * 1_000_001)
    with pytest.raises(ValueError):
        DocumentStore.from_files(tmp_path, ["large.md"])


@pytest.mark.asyncio
async def test_long_lines_and_empty_document():
    read = ReadKnowledgeTool(DocumentStore({"long": "x" * 20000, "empty": ""}))
    result = (await read.execute({"document_id": "long"})).structured_content
    assert len(result["lines"][0]["text"]) == 12000
    assert result["lines"][0]["truncated"]
    assert (await read.execute({"document_id": "empty"})).structured_content["lines"] == []


@pytest.mark.asyncio
async def test_conversation_snapshot_roles_and_order():
    messages = [ChatMessage(role="system", content="서버 secret"),
                ChatMessage(role="user", content="서버 2GB"),
                ChatMessage(role="assistant", content="서버 확인"),
                ChatMessage(role="user", content="서버 4GB 정정")]
    tool = SearchConversationTool(messages)
    messages[-1].content = "changed"
    result = (await tool.execute({"query": "서버", "limit": 2})).structured_content
    assert result["total_matches"] == 3
    assert [m["message_index"] for m in result["matches"]] == [4, 3]
    assert "4GB" in result["matches"][0]["snippet"]


@pytest.mark.asyncio
async def test_app_wiring_and_concurrent_conversation_isolation(monkeypatch):
    from backend.app import app, lifespan
    from backend.dataclass.settings import Settings

    monkeypatch.setattr(Settings, "load", lambda: Settings())

    class Model:
        async def stream_chat(self, model, history, tools=None, think=False):
            await asyncio.sleep(0)
            if history[-1].type != "tool":
                assert len([tool for tool in tools if tool.name.startswith("internal__")]) == 5
                yield AIMessageChunk(content="", tool_calls=[{
                    "name": "internal__search_conversation", "args": {"query": "이름"},
                    "id": "call-conversation",
                }])
            else:
                result = json.loads(history[-1].text)
                assert result["total_matches"] == 1
                yield AIMessageChunk(content=result["matches"][0]["snippet"])

    async with lifespan(app):
        service = app.state.chat_service
        service._ollama = Model()
        async def ask(name):
            return await service.run([
                ChatMessage(role="user", content=f"내 이름은 {name}"),
                ChatMessage(role="user", content="이름 찾아줘"),
            ], True, None)
        first, second = await asyncio.gather(ask("민수"), ask("영희"))
        assert first.message.content == "내 이름은 민수"
        assert second.message.content == "내 이름은 영희"
