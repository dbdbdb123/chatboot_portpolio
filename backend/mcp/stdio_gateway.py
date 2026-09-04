"""공식 MCP Python SDK를 이용한 stdio/HTTP 게이트웨이."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, ListToolsResult

from backend.constants.app import TOOL_NAME_SEPARATOR
from backend.constants.enums import MCPTransport
from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.dataclass.settings import MCPServerConfig
from backend.mcp.interface import MCPGateway
from backend.mcp.validation import ToolValidationError, validate_arguments


class ConfiguredMCPGateway(MCPGateway):
    """허용 목록을 적용하며 stdio와 Streamable HTTP 연결을 제공한다."""

    def __init__(self, servers: tuple[MCPServerConfig, ...]) -> None:
        """서버 설정을 이름으로 색인하고 도구 스키마 캐시를 준비한다."""
        self._servers = {server.name: server for server in servers}
        self._tool_cache: dict[str, MCPTool] = {}

    async def _with_session[T](
        self,
        config: MCPServerConfig,
        operation: Callable[[ClientSession], Awaitable[T]],
    ) -> T:
        """제한 시간 안에서 연결·초기화·정리를 수행한다."""
        async with asyncio.timeout(config.timeout_seconds):
            async with AsyncExitStack() as stack:
                if config.transport == MCPTransport.STREAMABLE_HTTP:
                    client = await stack.enter_async_context(
                        httpx2.AsyncClient(
                            headers=config.headers,
                            timeout=config.timeout_seconds,
                        )
                    )
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

        async def fetch(session: ClientSession) -> ListToolsResult:
            """초기화된 세션에서 SDK 형식의 도구 목록을 읽는다."""
            return await session.list_tools()

        discovered: list[MCPTool] = []
        for config in self._servers.values():
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
        qualified_name = f"{server}{TOOL_NAME_SEPARATOR}{name}"
        cached = self._tool_cache.get(qualified_name)
        if cached is None:
            await self.list_tools()
            cached = self._tool_cache.get(qualified_name)
        if cached is None:
            raise ToolValidationError("tool was not advertised by the MCP server")
        # 모델이 생성한 인자는 신뢰할 수 없으므로 서버로 보내기 전에 검증한다.
        validate_arguments(arguments, cached.input_schema)

        async def invoke(session: ClientSession) -> CallToolResult:
            """허용 목록과 스키마 검증을 통과한 인자로 SDK 도구를 호출한다."""
            return await session.call_tool(name, arguments=arguments)

        result = await self._with_session(config, invoke)
        content = [block.model_dump(mode="json", by_alias=True) for block in result.content]
        return MCPToolResult(
            content=content,
            structured_content=result.structured_content,
            is_error=bool(result.is_error),
        )

    async def close(self) -> None:
        """세션을 요청마다 닫으므로 별도로 정리할 영구 연결은 없다."""


# 기존 stdio 전용 이름을 사용하는 호출부와의 호환성을 유지한다.
StdioMCPGateway = ConfiguredMCPGateway
