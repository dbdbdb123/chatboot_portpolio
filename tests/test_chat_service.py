from typing import Any

import pytest

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.models import ChatMessage
from backend.services.chat import ChatService


class FakeMCP:
    async def list_tools(self) -> list[MCPTool]:
        return [MCPTool("docs", "search", "Search docs", {
            "type": "object", "properties": {"query": {"type": "string"}},
            "required": ["query"],
        })]

    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        return MCPToolResult(structured_content={"matches": ["README.md"]})

    async def close(self) -> None:
        return None


class FakeOllama:
    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(self, model, messages, tools=None):
        yield await self.chat(model, messages, tools)

    async def chat(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "docs__search", "arguments": {"query": "auth"}}
            }]}
        return {"role": "assistant", "content": "README에서 찾았습니다."}


@pytest.mark.asyncio
async def test_executes_tool_and_returns_final_answer() -> None:
    service = ChatService(FakeOllama(), FakeMCP(), "qwen3.5:2b-q4_K_M", 3)  # type: ignore[arg-type]
    result = await service.run([ChatMessage(role="user", content="인증 문서 찾아줘")], True, None)
    assert result.message.content == "README에서 찾았습니다."
    assert result.tools[0].name == "search"
