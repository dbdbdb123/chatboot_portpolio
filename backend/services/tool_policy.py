"""도구 노출과 실행 인자 변환을 같은 정책으로 관리한다."""

from dataclasses import dataclass
from typing import Any, Protocol

from backend.constants.chat import OCR_TOOL_NAME
from backend.dataclass.mcp import MCPTool
from backend.images import ImageAttachment


@dataclass(frozen=True, slots=True)
class ToolArguments:
    """서버에 전달할 인자와 UI에 공개할 안전한 인자를 구분한다."""

    execution: dict[str, Any]
    display: dict[str, Any]


class ToolPolicy(Protocol):
    """모델에 노출할 도구와 실행 인자에 적용하는 일관된 정책 계약."""

    def prepare_tools(self, tools: list[MCPTool], image: ImageAttachment | None) -> list[MCPTool]:
        """요청 문맥에 맞게 도구 노출 여부와 모델용 스키마를 결정한다."""
        ...

    def prepare_arguments(
        self,
        tool: MCPTool,
        arguments: dict[str, Any],
        image: ImageAttachment | None,
    ) -> ToolArguments:
        """모델 인자를 검증·변환하고 공개 가능한 실행 요약 인자를 반환한다."""
        ...


class OCRToolPolicy:
    """OCR의 첨부 요구·빈 인자 스키마·실제 이미지 주입 규칙을 관리한다."""

    def prepare_tools(self, tools: list[MCPTool], image: ImageAttachment | None) -> list[MCPTool]:
        """첨부 여부에 맞춰 모델에 노출할 도구를 준비한다.

        이미지가 없으면 OCR 도구를 제외하고, 있으면 빈 인자 스키마로 제공한다.
        실제 이미지 데이터는 도구 실행 시 백엔드에서 채운다.
        """
        model_tools = []
        for tool in tools:
            if tool.name != OCR_TOOL_NAME:
                model_tools.append(tool)
            elif image is not None:
                model_tools.append(
                    MCPTool(
                        server=tool.server,
                        name=tool.name,
                        description=(
                            "Run OCR on the attached image only when the user asks for OCR or text extraction. "
                            "For general image questions, answer directly using vision. No arguments required."
                        ),
                        input_schema={
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    )
                )
        return model_tools

    def prepare_arguments(
        self,
        tool: MCPTool,
        arguments: dict[str, Any],
        image: ImageAttachment | None,
    ) -> ToolArguments:
        """일반 도구 인자는 유지하고 OCR에는 첨부 데이터와 안전한 요약을 구성한다."""
        display_arguments = arguments
        if tool.name == OCR_TOOL_NAME:
            if image is None or arguments:
                raise ValueError("OCR 도구는 첨부 이미지에 대해 빈 인자로 호출해야 합니다.")
            arguments = {"data_base64": image.data_base64, "mime_type": image.mime_type}
            display_arguments = {"image": image.name, "mime_type": image.mime_type}
        return ToolArguments(execution=arguments, display=display_arguments)
