"""도구 노출과 실행 인자 변환을 같은 정책으로 관리한다."""

from dataclasses import dataclass
from typing import Any, Protocol

from backend.constants.chat import OCR_TOOL_NAME
from backend.dataclass.mcp import MCPTool
from backend.images import ImageAttachment


@dataclass(frozen=True, slots=True)
class ToolArguments:
    """정책이 구성한 서버 실행용 인자와 사용자 공개용 인자의 묶음.

    execution은 MCP 호출에 전달하며 첨부 원문 등 비공개 데이터가 포함될 수 있다.
    display는 ToolActivity에 사용하므로 UI에 공개해도 되는 값만 담아야 한다.
    일반 도구에서는 두 필드가 같은 사전을 참조할 수 있다.
    frozen은 필드 교체만 막으므로 소비자는 내부 사전을 직접 수정하지 않는다.
    """

    execution: dict[str, Any]
    display: dict[str, Any]


class ToolPolicy(Protocol):
    """도구 노출과 인자 변환에 동일한 규칙을 적용하기 위한 정책 인터페이스.

    prepare_tools는 모델에 제공할 도구 목록과 스키마를 결정하고,
    prepare_arguments는 실행 직전에 입력을 확인해 ToolArguments를 반환한다.
    앱 조립부는 같은 정책 인스턴스를 서비스와 실행기에 주입해야 한다.
    정책은 도구를 직접 호출하지 않으며 MCP의 허용 목록·스키마 검증을 대체하지 않는다.
    """

    def prepare_tools(self, tools: list[MCPTool], image: ImageAttachment | None) -> list[MCPTool]:
        """요청 문맥에 맞게 모델에 노출할 목록과 스키마를 준비하는 계약.

        tools는 조회된 도구 목록, image는 현재 요청의 선택적 첨부다.
        노출할 수 없는 도구는 제외하고 필요한 도구만 모델용 설명·스키마로 변환한다.
        호출·실제 파일 전송을 수행하지 않으며 원본 서버 스키마를 보존해야 한다.
        반환된 도구는 실행 단계의 인자 정책과 일치해야 한다.
        """
        ...

    def prepare_arguments(
        self,
        tool: MCPTool,
        arguments: dict[str, Any],
        image: ImageAttachment | None,
    ) -> ToolArguments:
        """선택된 도구의 모델 입력을 실행용·공개용 인자로 구성하는 계약.

        tool은 노출된 도구, arguments는 공통 검증을 통과한 객체, image는 선택적 첨부다.
        도구별 제약 위반은 예외로 알리고 성공하면 ToolArguments를 반환한다.
        display에는 사용자에게 노출할 수 있는 값만 포함해야 한다.
        MCP 실행이나 원본 서버 스키마 검증 자체는 이 메서드가 수행하지 않는다.
        """
        ...


class OCRToolPolicy:
    """OCR 도구의 첨부 요구와 원문 전달·공개 범위를 관리하는 정책 구현.

    이미지가 없으면 OCR 도구를 숨기고, 있으면 모델용 빈 인자 스키마로 노출한다.
    실행 시 첨부 존재와 빈 모델 인자를 확인한 뒤 실제 Base64·MIME을 주입한다.
    공개용 인자에는 파일명·MIME만 포함하고 일반 도구는 원래 인자를 유지한다.
    OCR 실행 여부는 모델이 선택하며 이 정책이 자동 실행하지 않는다.
    다른 도구의 특수 규칙은 이 클래스에 누적하기보다 별도 정책으로 분리한다.
    """

    def prepare_tools(self, tools: list[MCPTool], image: ImageAttachment | None) -> list[MCPTool]:
        """첨부 여부에 따라 OCR 노출을 결정하고 일반 도구는 유지한다.

        이미지가 없으면 OCR 도구를 제외하고, 있으면 새 MCPTool에 빈 인자 스키마와
        OCR 용도 설명을 넣어 반환한다. 실제 Base64는 모델용 스키마에 넣지 않는다.
        입력 목록 순서를 유지하며 일반 도구 객체는 그대로 사용한다.
        서버 원본 스키마를 수정하거나 OCR을 자동으로 실행하지 않는다.
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
        """OCR 호출에 실제 첨부를 주입하고 사용자 공개 정보와 분리한다.

        OCR이면 image가 존재하고 arguments가 비어 있어야 하며 위반 시 ValueError를 낸다.
        execution에는 data_base64·mime_type, display에는 파일명·MIME을 새로 구성한다.
        일반 도구는 입력 사전을 두 필드에 그대로 사용하므로 반환값을 수정하지 않는다.
        첨부 파일의 실제 내용 검증은 ImageAttachment 생성 단계에서 수행한다.
        """
        display_arguments = arguments
        if tool.name == OCR_TOOL_NAME:
            if image is None or arguments:
                raise ValueError("OCR 도구는 첨부 이미지에 대해 빈 인자로 호출해야 합니다.")
            arguments = {"data_base64": image.data_base64, "mime_type": image.mime_type}
            display_arguments = {"image": image.name, "mime_type": image.mime_type}
        return ToolArguments(execution=arguments, display=display_arguments)
