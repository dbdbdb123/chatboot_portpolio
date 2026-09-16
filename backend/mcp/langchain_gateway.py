"""LangChain 공식 MCP 어댑터와 애플리케이션 도구 계약을 연결한다."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from backend.constants.app import TOOL_NAME_SEPARATOR
from backend.constants.enums import MCPTransport
from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.dataclass.settings import MCPServerConfig
from backend.mcp.interface import MCPGateway
from backend.mcp.validation import ToolValidationError, validate_arguments


def _connection(config: MCPServerConfig) -> dict[str, Any]:
    """검증된 앱 설정을 ``langchain-mcp-adapters`` 연결 설정으로 변환한다.

    인증 헤더와 환경 변수는 어댑터에만 전달하고 로그나 공개 도구 정의에는 넣지 않는다.
    HTTP 제한 시간은 일반 요청과 장시간 응답 읽기에 동일하게 적용해 앱 설정의 의미를
    유지한다. 반환 타입은 어댑터가 지원하는 두 전송 형식 중 하나다.
    """
    if config.transport == MCPTransport.STREAMABLE_HTTP:
        return {
            "transport": "streamable_http",
            "url": config.url,
            "headers": dict(config.headers),
            "timeout": config.timeout_seconds,
            "sse_read_timeout": config.timeout_seconds,
        }
    return {
        "transport": "stdio",
        "command": config.command,
        "args": list(config.args),
        "env": dict(config.env) or None,
    }


class LangChainMCPGateway(MCPGateway):
    """공식 ``MultiServerMCPClient``를 기존 안전 경계 안에서 사용한다.

    LangChain 어댑터가 MCP 세션 생성, 도구 페이지네이션, 콘텐츠 블록 변환을 담당한다.
    이 클래스는 프로젝트 고유의 서버별 허용 목록과 ``server__tool`` 이름을 유지하고,
    모델 인자를 실행 전에 한 번 더 검증한다. 도구는 목록 조회 때 캐시되지만 실제 MCP
    연결은 공식 어댑터의 기본 동작대로 각 실행 시 열고 닫힌다.
    """

    def __init__(self, servers: tuple[MCPServerConfig, ...]) -> None:
        """서버 설정을 색인하고 공식 다중 서버 클라이언트를 구성한다."""
        self._servers = {server.name: server for server in servers}
        self._client = MultiServerMCPClient(
            {server.name: _connection(server) for server in servers},
            # 프로젝트는 외부 API 호환성을 위해 밑줄 하나가 아닌 ``__``를 사용한다.
            tool_name_prefix=False,
            # MCP가 보고한 도구 오류는 모델이 수정할 수 있는 ToolMessage로 받는다.
            handle_tool_errors=True,
        )
        self._tool_cache: dict[str, tuple[MCPTool, BaseTool]] = {}

    async def list_tools(self) -> list[MCPTool]:
        """각 서버의 LangChain 도구 중 허용된 항목만 공개하고 실행 도구를 캐시한다.

        서버별로 조회하므로 같은 이름의 도구가 여러 서버에 있어도 ``server__tool``로
        구분된다. 한 서버 조회 실패는 호출자에게 전달하며 이전 캐시는 실행 근거로
        남겨 두지 않고, 이번 조회에서 실제 광고된 도구만 새 캐시에 기록한다.
        """
        discovered: list[MCPTool] = []
        refreshed: dict[str, tuple[MCPTool, BaseTool]] = {}
        for config in self._servers.values():
            for tool in await self._client.get_tools(server_name=config.name):
                if tool.name not in config.allowed_tools:
                    continue
                definition = MCPTool(
                    server=config.name,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.get_input_jsonschema(),
                )
                discovered.append(definition)
                refreshed[definition.qualified_name] = (definition, tool)
        self._tool_cache = refreshed
        return discovered

    async def call_tool(
        self, server: str, name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        """허용 목록·원본 스키마를 검사하고 LangChain ``BaseTool``로 MCP를 실행한다."""
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

        definition, tool = cached
        validate_arguments(arguments, definition.input_schema)
        # ToolCall 형태로 실행해야 LangChain이 콘텐츠와 artifact를 ToolMessage에 함께 보존한다.
        output = await tool.ainvoke({
            "type": "tool_call",
            "name": tool.name,
            "args": arguments,
            "id": f"mcp-{uuid4().hex}",
        })
        if isinstance(output, ToolMessage):
            artifact = output.artifact if isinstance(output.artifact, dict) else {}
            structured = artifact.get("structured_content")
            content = output.content if isinstance(output.content, list) else [
                {"type": "text", "text": str(output.content)}
            ]
            return MCPToolResult(
                content=[item if isinstance(item, dict) else {"type": "text", "text": str(item)}
                         for item in content],
                structured_content=structured if isinstance(structured, dict) else None,
                is_error=output.status == "error",
            )
        # 사용자 정의 어댑터/테스트 대역이 ToolMessage를 만들지 않는 경우도 안전하게 정규화한다.
        return MCPToolResult(content=[{"type": "text", "text": str(output)}])

    async def close(self) -> None:
        """클라이언트가 호출별 세션을 사용하므로 영구 연결 정리는 필요하지 않다."""


# 이전 이름을 가져오는 외부 코드가 새 구현으로 자연스럽게 이동하도록 호환 별칭을 둔다.
ConfiguredMCPGateway = LangChainMCPGateway
StdioMCPGateway = LangChainMCPGateway
