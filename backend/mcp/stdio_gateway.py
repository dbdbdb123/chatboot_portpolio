"""공식 MCP Python SDK를 이용한 stdio/HTTP 게이트웨이."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from contextlib import AsyncExitStack

import httpx2

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.dataclass.settings import MCPServerConfig
from backend.mcp.interface import MCPGateway
from backend.mcp.validation import ToolValidationError, validate_arguments


class ConfiguredMCPGateway(MCPGateway):
    """Allow-listed MCP client supporting stdio and Streamable HTTP."""

    def __init__(self, servers: tuple[MCPServerConfig, ...]) -> None:
        self._servers = {server.name: server for server in servers}
        self._tool_cache: dict[str, MCPTool] = {}

    async def _with_session(
        self,
        config: MCPServerConfig,
        operation: Callable[[ClientSession], Awaitable[Any]],
    ) -> Any:
        """제한 시간 안에서 연결·초기화·정리를 수행한다."""
        async with asyncio.timeout(config.timeout_seconds):
            async with AsyncExitStack() as stack:
                if config.transport == "streamable_http":
                    client = await stack.enter_async_context(httpx2.AsyncClient(
                        headers=config.headers, timeout=config.timeout_seconds,
                    ))
                    read, write, *_ = await stack.enter_async_context(
                        streamable_http_client(config.url, http_client=client)
                    )
                else:
                    params = StdioServerParameters(
                        command=config.command, args=list(config.args), env=config.env or None
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await operation(session)

    async def list_tools(self) -> list[MCPTool]:
        """각 서버의 도구를 조회하고 명시적으로 허용된 항목만 캐시한다."""
        discovered: list[MCPTool] = []
        for config in self._servers.values():
            async def fetch(session: ClientSession) -> Any:
                return await session.list_tools()

            response = await self._with_session(config, fetch)
            for tool in response.tools:
                # 서버가 광고했다는 사실만으로 신뢰하지 않고 설정의 allow-list를 적용한다.
                if tool.name not in config.allowed_tools:
                    continue
                item = MCPTool(
                    server=config.name,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(tool.input_schema),
                )
                discovered.append(item)
                self._tool_cache[item.qualified_name] = item
        return discovered

    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        """도구명과 입력값을 검증한 후 새 MCP 세션에서 실행한다."""
        config = self._servers.get(server)
        if config is None or name not in config.allowed_tools:
            raise ToolValidationError("tool is not allow-listed")
        cached = self._tool_cache.get(f"{server}__{name}")
        if cached is None:
            await self.list_tools()
            cached = self._tool_cache.get(f"{server}__{name}")
        if cached is None:
            raise ToolValidationError("tool was not advertised by the MCP server")
        # 모델이 생성한 인자는 신뢰할 수 없으므로 서버로 보내기 전에 검증한다.
        validate_arguments(arguments, cached.input_schema)

        async def invoke(session: ClientSession) -> Any:
            return await session.call_tool(name, arguments=arguments)

        result = await self._with_session(config, invoke)
        content = [block.model_dump(mode="json", by_alias=True) for block in result.content]
        return MCPToolResult(
            content=content,
            structured_content=result.structured_content,
            is_error=bool(result.is_error),
        )

    async def close(self) -> None:
        return None


# Existing imports remain compatible.
StdioMCPGateway = ConfiguredMCPGateway
