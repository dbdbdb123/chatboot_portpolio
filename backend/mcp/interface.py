"""채팅 서비스와 실제 MCP 전송 구현 사이의 추상 경계."""

from __future__ import annotations

from typing import Any, Protocol

from backend.dataclass.mcp import MCPTool, MCPToolResult


class MCPToolCatalog(Protocol):
    """대화 준비에 필요한 도구 조회 계약만 제공한다."""

    async def list_tools(self) -> list[MCPTool]:
        """사용 가능한 도구와 입력 스키마를 반환한다."""
        ...


class MCPToolCaller(Protocol):
    """도구 실행에 필요한 호출 계약만 제공한다."""

    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        """지정한 서버의 도구를 실행하고 내부 공통 형식으로 결과를 반환한다."""
        ...


class MCPToolClient(MCPToolCatalog, MCPToolCaller, Protocol):
    """조회와 호출을 모두 제공하는 MCP 클라이언트의 통합 계약."""


class MCPGateway(MCPToolClient, Protocol):
    """앱 수명주기에서 관리하는 MCP 클라이언트의 종료 계약을 추가한다."""

    async def close(self) -> None:
        """게이트웨이가 보유한 연결과 자원을 정리한다."""
        ...
