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
    """UI에 보낼 안전한 실행 요약과 모델에 전달할 결과 메시지."""

    activity: ToolActivity
    message: dict[str, Any]


class ToolRunner(Protocol):
    """대화 서비스가 도구 실행 전략에 요구하는 최소 계약."""

    async def execute(
        self,
        call: dict[str, Any],
        tool_index: dict[str, MCPTool],
        image: ImageAttachment | None,
    ) -> ToolExecution:
        """모델 호출을 실행해 UI 요약과 모델 결과 메시지를 반환한다."""
        ...


class ToolExecutor:
    """공통 호출 검증 후 주입된 정책의 인자로 MCP를 실행한다."""

    def __init__(self, mcp: MCPToolCaller, policy: ToolPolicy) -> None:
        """구체적인 전송 구현 대신 도구 실행 계약을 주입받는다."""
        self._mcp = mcp
        self._policy = policy

    async def execute(
        self,
        call: dict[str, Any],
        tool_index: dict[str, MCPTool],
        image: ImageAttachment | None,
    ) -> ToolExecution:
        """등록된 도구만 실행하고 첨부 원문을 숨긴 요약과 모델 결과를 반환한다."""
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
