"""서버 이름으로 도구 제공자를 선택하는 조합 어댑터."""

from collections.abc import Mapping
from typing import Any

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.mcp.interface import MCPToolClient


class CompositeToolClient:
    """명시적으로 등록한 서버는 해당 제공자에, 나머지는 기본 제공자에 위임한다.

    제공자의 수명주기는 앱 조립부가 관리한다. 공유 라우팅 캐시는 사용하지 않는다.
    """

    def __init__(self, providers: Mapping[str, MCPToolClient], fallback: MCPToolClient) -> None:
        self._providers = dict(providers)
        self._fallback = fallback

    async def list_tools(self) -> list[MCPTool]:
        tools = []
        for server, provider in self._providers.items():
            definitions = await provider.list_tools()
            if any(tool.server != server for tool in definitions):
                raise ValueError("tool provider returned an unexpected server")
            tools.extend(definitions)
        external = await self._fallback.list_tools()
        if any(tool.server in self._providers for tool in external):
            raise ValueError("tool server namespace collision")
        tools.extend(external)
        names = [tool.qualified_name for tool in tools]
        if len(set(names)) != len(names):
            raise ValueError("duplicate tool name")
        return tools

    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        provider = self._providers.get(server, self._fallback)
        return await provider.call_tool(server, name, arguments)
