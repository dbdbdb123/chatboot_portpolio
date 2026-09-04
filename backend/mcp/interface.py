"""채팅 서비스와 실제 MCP 전송 구현 사이의 추상 경계."""

from __future__ import annotations

from typing import Any, Protocol

from backend.dataclass.mcp import MCPTool, MCPToolResult


class MCPToolCatalog(Protocol):
    """도구 조회만 필요한 대화 서비스에 제공하는 최소 인터페이스.

    list_tools는 서버·이름·설명·입력 스키마가 포함된 MCPTool 목록을 반환한다.
    호출이나 연결 종료 메서드를 요구하지 않아 조회 전용 구현을 사용할 수 있다.
    현재 게이트웨이 구현은 허용 목록을 적용한 결과를 반환한다.
    """

    async def list_tools(self) -> list[MCPTool]:
        """대화 준비에 사용할 도구 설명과 스키마 목록을 반환하는 계약.

        구현체는 사용 가능한 MCPTool 목록을 제공하고 외부 조회 실패를 전달해야 한다.
        호출자는 이후 노출 정책을 적용하므로 서버 원본 스키마를 직접 수정하지 않는다.
        이 계약은 실제 도구 실행이나 연결 종료를 요구하지 않는다.
        """
        ...


class MCPToolCaller(Protocol):
    """정해진 도구 실행만 필요한 실행기에 제공하는 최소 인터페이스.

    서버 이름·도구 이름·인자 객체를 받아 MCPToolResult를 반환한다.
    조회나 연결 수명주기 기능을 요구하지 않으며 실제 전송 방식을 노출하지 않는다.
    호출 구현은 자신의 접근 제한과 입력 검증을 적용해야 한다.
    """

    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        """지정한 서버·도구·인자 객체로 실행을 요청하는 계약.

        구현체는 접근 제한과 입력 검증을 적용하고 결과를 MCPToolResult로 반환한다.
        전송·검증 실패는 예외로, 도구가 보고한 실패는 결과의 is_error로 표현할 수 있다.
        도구 조회나 HTTP 응답 생성은 이 메서드의 책임에 포함되지 않는다.
        """
        ...


class MCPToolClient(MCPToolCatalog, MCPToolCaller, Protocol):
    """조회와 호출을 모두 제공하는 MCP 클라이언트의 통합 인터페이스.

    MCPToolCatalog와 MCPToolCaller 계약을 결합하며 별도 동작은 추가하지 않는다.
    두 기능을 모두 제공하는 구현을 표현할 때 사용한다.
    조회 또는 호출만 필요한 소비자는 각각의 더 작은 계약을 사용한다.
    """


class MCPGateway(MCPToolClient, Protocol):
    """앱 수명주기에서 관리하는 MCP 클라이언트의 전체 인터페이스.

    도구 조회·호출에 더해 close를 통한 자원 정리 계약을 제공한다.
    종료 호출은 앱 조립부가 담당하며 대화 서비스나 도구 실행기는
    이 종료 메서드에 의존하지 않는다. 구체 구현에 따라 영구 연결이 없을 수도 있다.
    """

    async def close(self) -> None:
        """게이트웨이가 보유한 자원을 비동기로 정리하는 계약.

        앱 종료 시 조립부에서 호출하며 반환값은 없다.
        영구 연결을 보유하지 않는 구현은 추가 작업 없이 종료할 수 있다.
        구체 구현의 종료 실패는 수명주기 관리자가 처리할 수 있도록 전달한다.
        """
        ...
