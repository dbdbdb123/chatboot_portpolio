"""Shared LangChain-compatible test doubles."""

from typing import Any

from langchain_core.messages import AIMessageChunk

from backend.dataclass.mcp import MCPTool, MCPToolResult


class FakeMCP:
    async def list_tools(self) -> list[MCPTool]:
        return [MCPTool(
            "docs", "search", "Search docs",
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )]

    async def call_tool(
        self, server: str, name: str, arguments: dict[str, Any],
    ) -> MCPToolResult:
        return MCPToolResult(structured_content={"matches": ["README.md"]})

    async def close(self) -> None:
        return None


class FakeOllama:
    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(self, model, messages, tools=None, think=False):
        self.calls += 1
        if self.calls == 1:
            yield AIMessageChunk(content="", tool_calls=[{
                "name": "docs__search", "args": {"query": "auth"}, "id": "call-search",
            }])
        else:
            yield AIMessageChunk(content="README에서 찾았습니다.")
