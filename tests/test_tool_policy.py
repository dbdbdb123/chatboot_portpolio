"""도구별 정책의 검증 경계와 교체 가능성을 확인한다."""

from dataclasses import replace

import pytest
from test_chat_service import FakeMCP, FakeOllama
from test_images import attachment

from backend.constants.chat import OCR_TOOL_NAME
from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.images import ImageAttachment
from backend.models import ChatMessage
from backend.services.chat import ChatService
from backend.services.tool_policy import OCRToolPolicy, ToolArguments
from backend.services.tools import ToolExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("has_image", "arguments"),
    [(False, {}), (False, {"data_base64": "invented"}), (True, {"data_base64": "invented"})],
)
async def test_ocr_policy_blocks_invalid_calls_before_mcp(has_image, arguments):
    """첨부 누락과 모델이 임의로 만든 OCR 인자는 서버 호출 전에 거부한다."""

    class GuardedCaller:
        async def call_tool(self, *args):
            """잘못된 OCR 요청이 서버 호출까지 도달하면 실패시킨다."""
            pytest.fail("invalid OCR call reached MCP")

    tool = MCPTool("ocr", OCR_TOOL_NAME, "OCR", {"type": "object"})
    image = ImageAttachment(**attachment()) if has_image else None
    with pytest.raises(ValueError, match="빈 인자"):
        await ToolExecutor(GuardedCaller(), OCRToolPolicy()).execute(
            {"function": {"name": tool.qualified_name, "arguments": arguments}},
            {tool.qualified_name: tool},
            image,
        )


@pytest.mark.asyncio
async def test_shared_policy_controls_exposure_and_execution():
    """서비스·실행기 수정 없이 주입한 정책이 노출과 실제 인자에 함께 적용된다."""
    prepared = []

    class SearchPolicy:
        def prepare_tools(self, tools, image):
            """정책 전용 설명을 붙여 모델에 전달할 도구를 준비한다."""
            prepared.append("exposure")
            return [replace(tool, description="Policy search") for tool in tools]

        def prepare_arguments(self, tool, arguments, image):
            """노출에 사용한 정책이 실행 인자도 변환하는지 확인한다."""
            assert tool.description == "Policy search"
            prepared.append("arguments")
            return ToolArguments(execution={"query": "policy query"}, display={"query": "safe"})

    class SearchMCP(FakeMCP):
        async def call_tool(self, server, name, arguments):
            """모델의 원래 인자 대신 정책이 구성한 인자로 실행되는지 확인한다."""
            assert arguments == {"query": "policy query"}
            return MCPToolResult(structured_content={"matches": ["README.md"]})

    policy = SearchPolicy()
    mcp = SearchMCP()
    service = ChatService(
        FakeOllama(),
        mcp,
        "test",
        2,
        tool_executor=ToolExecutor(mcp, policy),
        tool_policy=policy,
    )
    result = await service.run([ChatMessage(role="user", content="search")], True, None)
    assert prepared == ["exposure", "arguments"]
    assert result.tools[0].arguments == {"query": "safe"}
