"""채팅 서비스와 실제 MCP 전송 구현 사이의 추상 경계."""

from __future__ import annotations

from typing import Any, Protocol

from backend.dataclass.mcp import MCPTool, MCPToolResult


class MCPGateway(Protocol):
    """stdio 외의 전송 방식도 동일하게 구현할 수 있는 최소 계약."""
    async def list_tools(self) -> list[MCPTool]: ...
    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> MCPToolResult: ...
    async def close(self) -> None: ...
