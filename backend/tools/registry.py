"""구체 도구를 알지 못하는 내부 도구 등록·조회·실행 어댑터."""

from collections.abc import Iterable
from typing import Any, Protocol

from backend.dataclass.mcp import MCPTool, MCPToolResult

INTERNAL_SERVER = "internal"


class InternalTool(Protocol):
    """각 도구는 설명과 실행만 제공한다. 입력 검증은 실행 계약에 포함된다."""

    @property
    def definition(self) -> MCPTool: ...

    async def execute(self, arguments: dict[str, Any]) -> MCPToolResult: ...


class InternalToolRegistry:
    """기존 도구 조회·호출 Protocol을 구현하며 중복 등록을 거부한다."""

    def __init__(self, tools: Iterable[InternalTool]) -> None:
        self._tools: dict[str, InternalTool] = {}
        for tool in tools:
            definition = tool.definition
            if definition.server != INTERNAL_SERVER or definition.name in self._tools:
                raise ValueError("invalid or duplicate internal tool registration")
            self._tools[definition.name] = tool

    async def list_tools(self) -> list[MCPTool]:
        return [tool.definition for tool in self._tools.values()]

    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        if server != INTERNAL_SERVER or name not in self._tools:
            raise ValueError("unknown internal tool")
        return await self._tools[name].execute(arguments)
