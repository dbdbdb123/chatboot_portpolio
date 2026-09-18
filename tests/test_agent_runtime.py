"""LangChain create_agent integration tests."""

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import Field

from backend.ollama import OllamaClient


class ToolCapableFakeModel(FakeMessagesListChatModel):
    """Small deterministic model that accepts LangChain tool binding."""

    bound_tools: list = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        self.bound_tools = tools
        return self


@pytest.mark.asyncio
async def test_ollama_client_runs_create_agent_tool_loop(monkeypatch):
    calls = []

    async def lookup(query: str) -> str:
        calls.append(query)
        return "README.md"

    tool = StructuredTool.from_function(
        coroutine=lookup,
        name="docs__search",
        description="Search documentation",
    )
    model = ToolCapableFakeModel(responses=[
        AIMessage(content="", tool_calls=[{
            "name": "docs__search",
            "args": {"query": "auth"},
            "id": "call-search",
        }]),
        AIMessage(content="README에서 찾았습니다."),
    ])
    client = OllamaClient("http://unused", 1)
    monkeypatch.setattr(client, "_model", lambda *args: model)
    try:
        events = [event async for event in client.stream_agent(
            "test", [HumanMessage(content="인증 문서 찾아줘")], [tool], False, 3,
        )]
    finally:
        await client.close()

    assert calls == ["auth"]
    assert any(mode == "updates" for mode, _ in events)
    assert model.bound_tools[0].name == "docs__search"
