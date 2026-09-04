"""모델 호출의 공통 검증과 MCP 실행, 결과 변환을 담당한다."""

import json
from dataclasses import dataclass
from typing import Any, Protocol

from backend.constants.enums import MessageRole
from backend.dataclass.mcp import MCPTool
from backend.images import ImageAttachment
from backend.mcp.interface import MCPToolCaller
from backend.models import ToolActivity
from backend.services.tool_policy import ToolPolicy


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """도구 실행에서 얻은 UI 요약과 후속 추론 메시지를 함께 전달한다.

    activity는 공개용 ToolActivity이며 message는 role=tool 형식의 모델 입력이다.
    ChatService는 두 값을 각각 이벤트와 대화 이력에 추가한다.
    실행 데이터 전달만 담당하며 파일 저장·전송·민감 정보 정제를 수행하지 않는다.
    """

    activity: ToolActivity
    message: dict[str, Any]


class ToolRunner(Protocol):
    """ChatService가 구체적인 실행 구현 없이 도구를 실행하기 위한 계약.

    execute는 모델 호출, 현재 노출된 도구 색인과 첨부를 받아 ToolExecution을 반환한다.
    구현체는 등록된 도구와 올바른 입력만 실행하고 안전한 공개용 요약을 제공해야 한다.
    실패 예외는 상위 처리 계층으로 전달하며 HTTP 상태나 SSE 프레임을 생성하지 않는다.
    반환 타입뿐 아니라 오류·취소 동작도 구현 교체 시 함께 확인해야 한다.
    """

    async def execute(
        self,
        call: dict[str, Any],
        tool_index: dict[str, MCPTool],
        image: ImageAttachment | None,
    ) -> ToolExecution:
        """모델의 단일 도구 호출을 처리해 공개 요약과 모델 메시지를 반환하는 계약.

        call은 모델 호출 사전, tool_index는 현재 노출된 도구 색인, image는 선택적 첨부다.
        구현체는 실행 대상을 검증하고 ToolExecution의 activity와 message를 구성한다.
        부적절한 입력·실행 실패는 호출부에 알리며 사용자 공개 데이터의 범위를 지켜야 한다.
        대화 이력 저장과 이벤트 송신은 이 계약을 사용하는 서비스에 맡긴다.
        """
        ...


class ToolExecutor:
    """공통 호출 검증과 정책 적용 후 MCP 실행·결과 변환을 수행한다.

    MCPToolCaller와 ToolPolicy를 주입받으며 구체적인 전송 연결을 생성하지 않는다.
    모델이 요청한 이름을 노출 도구 색인에서 찾고 문자열 JSON 인자를 객체로 검증한다.
    도구별 인자 규칙은 정책에 위임하고 execution으로 호출해 display로 요약을 만든다.
    도구 결과는 ToolExecution으로 반환하며 대화 이력과 UI 갱신은 서비스에 맡긴다.
    전체 JSON Schema와 허용 목록 검증은 MCP 게이트웨이가 추가로 담당한다.
    """

    def __init__(self, mcp: MCPToolCaller, policy: ToolPolicy) -> None:
        """실제 호출 클라이언트와 인자 구성 정책을 주입받아 보관한다.

        mcp에는 call_tool만 요구하며 조회·종료 메서드에 의존하지 않는다.
        policy는 모델 노출에 사용한 정책과 일치하도록 조립부에서 제공해야 한다.
        생성 시 연결을 열거나 도구를 조회하지 않는다.
        """
        self._mcp = mcp
        self._policy = policy

    async def execute(
        self,
        call: dict[str, Any],
        tool_index: dict[str, MCPTool],
        image: ImageAttachment | None,
    ) -> ToolExecution:
        """모델 호출을 검증하고 정책이 구성한 인자로 MCP를 실행한다.

        노출 색인에 없는 이름과 JSON 객체가 아닌 인자를 ValueError로 거부한다.
        문자열 인자는 JSON으로 해석하며 파싱 오류와 정책 오류는 그대로 전달한다.
        정책의 execution으로 호출하고 display로 ToolActivity를 구성한다.
        구조화 결과가 비어 있지 않으면 이를, 아니면 일반 콘텐츠를 직렬화해
        후속 추론용 메시지를 만든다. MCP 실패 상태는 요약에 기록하고 예외는 전파한다.
        입력 이력이나 도구 색인을 직접 변경하지 않으며 재시도하지 않는다.
        """
        function = call.get("function", {})
        qualified_name = str(function.get("name", ""))
        # 모델이 임의의 함수명을 만들어도 등록된 도구 외에는 실행하지 않는다.
        tool = tool_index.get(qualified_name)
        if tool is None:
            raise ValueError(f"model requested unknown tool: {qualified_name}")
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        prepared = self._policy.prepare_arguments(tool, arguments, image)
        result = await self._mcp.call_tool(tool.server, tool.name, prepared.execution)
        activity = ToolActivity(
            server=tool.server,
            name=tool.name,
            arguments=prepared.display,
            is_error=result.is_error,
        )
        # 구조화 결과가 없으면 MCP의 일반 콘텐츠 블록을 모델에 전달한다.
        payload = result.structured_content or {"content": result.content}
        message = {
            "role": MessageRole.TOOL,
            "tool_name": qualified_name,
            "content": json.dumps(payload, ensure_ascii=False),
        }
        return ToolExecution(activity=activity, message=message)
