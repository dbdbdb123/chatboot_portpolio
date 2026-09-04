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
    """설정에 등록된 MCP 서버를 stdio 또는 Streamable HTTP로 호출하는 어댑터.

    서버별 제한 시간 안에서 요청마다 세션을 연결·초기화하고 종료한다.
    list_tools는 허용 목록을 통과한 도구만 반환하고 원본 입력 스키마를 캐시한다.
    call_tool은 허용 목록과 캐시된 스키마를 검증한 뒤 SDK 결과를
    MCPToolResult로 변환한다. 모델용으로 변환된 스키마는 이 캐시를 덮어쓰지 않는다.
    영구 세션은 보유하지 않으므로 close에서 추가로 닫을 연결은 없다.
    서버별 장애 격리와 도구 목록 페이지네이션은 현재 처리하지 않는다.
    """

    def __init__(self, servers: tuple[MCPServerConfig, ...]) -> None:
        """서버 설정을 이름으로 색인하고 빈 도구 스키마 캐시를 만든다.

        servers는 설정 객체들의 tuple이며 실제 연결이나 도구 조회는 수행하지 않는다.
        동일한 서버 이름이 반복되면 뒤의 설정이 색인의 이전 값을 덮어쓴다.
        이름 중복 검증은 현재 별도로 제공하지 않으므로 설정 작성 시 유일성을 유지한다.
        """
        self._servers = {server.name: server for server in servers}
        self._tool_cache: dict[str, MCPTool] = {}

    async def _with_session[T](
        self,
        config: MCPServerConfig,
        operation: Callable[[ClientSession], Awaitable[T]],
    ) -> T:
        """선택한 전송 방식의 임시 세션에서 비동기 작업을 실행한다.

        config에 맞는 stdio 또는 HTTP 연결을 열고 세션 초기화 후 operation을 호출한다.
        operation의 결과 타입을 그대로 반환하며 연결·작업·정리 범위에 제한 시간을 적용한다.
        컨텍스트 관리자로 클라이언트와 세션을 정리하고 SDK·작업 오류를 그대로 전달한다.
        호출마다 새 세션을 사용하며 연결을 캐시하거나 재시도하지 않는다.
        """
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
        """등록된 서버를 순서대로 조회해 허용된 도구 목록을 반환한다.

        SDK 도구를 내부 MCPTool로 변환하고 qualified_name 기준으로 스키마를 캐시한다.
        반환 목록에는 현재 조회 결과 중 allowed_tools에 포함된 항목만 들어간다.
        기존 캐시 전체를 초기화하지 않으며 페이지네이션이나 일부 장애 격리는 수행하지 않는다.
        어느 서버에서든 오류가 발생하면 해당 예외를 호출부로 전달한다.
        """

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
        """허용된 도구와 원본 스키마로 입력을 확인한 뒤 새 세션에서 실행한다.

        server·name이 허용 목록에 없으면 ToolValidationError를 발생시킨다.
        스키마가 캐시에 없으면 도구 목록을 다시 조회하며 그래도 없으면 호출을 거부한다.
        인자 검증 후 SDK 결과의 콘텐츠·구조화 결과·오류 상태를 MCPToolResult로 반환한다.
        실행·검증·전송 예외는 그대로 전달하며 모델용 스키마로 원본 검증을 대체하지 않는다.
        """
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
        """요청마다 세션을 닫는 현재 구현의 수명주기 종료 진입점.

        영구 연결이 없어 추가 I/O나 자원 해제를 수행하지 않고 None을 반환한다.
        서버 설정과 도구 캐시를 초기화하는 메서드는 아니다.
        앱은 구현체 종류와 무관하게 MCPGateway 계약에 따라 이 메서드를 호출할 수 있다.
        """


# 기존 stdio 전용 이름을 사용하는 호출부와의 호환성을 유지한다.
StdioMCPGateway = ConfiguredMCPGateway
