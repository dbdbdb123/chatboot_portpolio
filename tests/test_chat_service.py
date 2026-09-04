from typing import Any

import pytest

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.models import ChatMessage, ToolActivity
from backend.services.chat import ChatService
from backend.services.tool_policy import OCRToolPolicy
from backend.services.tools import ToolExecution, ToolExecutor


class FakeMCP:
    async def list_tools(self) -> list[MCPTool]:
        return [
            MCPTool(
                "docs",
                "search",
                "Search docs",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ]

    async def call_tool(self, server: str, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        return MCPToolResult(structured_content={"matches": ["README.md"]})

    async def close(self) -> None:
        return None


class FakeOllama:
    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(self, model, messages, tools=None, think=False):
        yield await self.chat(model, messages, tools)

    async def chat(
        self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "docs__search", "arguments": {"query": "auth"}}}
                ],
            }
        return {"role": "assistant", "content": "README에서 찾았습니다."}


@pytest.mark.asyncio
async def test_executes_tool_and_returns_final_answer() -> None:
    """모델이 요청한 도구 실행 결과를 후속 추론에 전달해 최종 답변을 얻는지 확인한다."""
    mcp = FakeMCP()
    service = ChatService(
        FakeOllama(),
        mcp,
        "qwen3.5:2b-q4_K_M",
        3,
        tool_executor=ToolExecutor(mcp, OCRToolPolicy()),
        tool_policy=OCRToolPolicy(),
    )
    result = await service.run([ChatMessage(role="user", content="인증 문서 찾아줘")], True, None)
    assert result.message.content == "README에서 찾았습니다."
    assert result.tools[0].name == "search"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments", "expected_error"),
    [
        ("docs__unknown", {}, "unknown tool"),
        ("ocr__inspect_document", {}, "unknown tool"),
        ("docs__search", [], "arguments must be an object"),
        ("docs__search", "[]", "arguments must be an object"),
    ],
)
async def test_invalid_model_calls_never_reach_mcp(name, arguments, expected_error):
    """미등록 도구·첨부 없는 OCR·객체가 아닌 인자를 MCP 실행 전에 차단한다."""

    class InvalidCallModel:
        async def stream_chat(self, *args):
            """검증 경계를 시험할 잘못된 도구 호출을 생성한다."""
            yield {"tool_calls": [{"function": {"name": name, "arguments": arguments}}]}

    class GuardedMCP(FakeMCP):
        async def call_tool(self, *args):
            """잘못된 모델 호출이 MCP까지 도달하면 테스트를 실패시킨다."""
            pytest.fail("invalid tool call reached MCP")

    mcp = GuardedMCP()
    service = ChatService(
        InvalidCallModel(),
        mcp,
        "test",
        1,
        tool_executor=ToolExecutor(mcp, OCRToolPolicy()),
        tool_policy=OCRToolPolicy(),
    )
    with pytest.raises(ValueError, match=expected_error):
        await service.run([ChatMessage(role="user", content="search")], True, None)


@pytest.mark.asyncio
async def test_injected_tool_runner_is_used():
    """조회만 제공하는 객체와 교체 실행기로 대화 서비스를 구성할 수 있는지 확인한다."""

    class CatalogOnly:
        async def list_tools(self) -> list[MCPTool]:
            """도구 실행·종료 메서드 없이 사용 가능한 도구만 제공한다."""
            return [MCPTool("docs", "search", "Search docs", {"type": "object"})]

    class ReplacementRunner:
        async def execute(self, call, tool_index, image):
            """실행 요약과 모델 결과를 대화 서비스의 공통 계약으로 제공한다."""
            assert call["function"]["name"] in tool_index
            return ToolExecution(
                activity=ToolActivity(server="docs", name="replacement", arguments={}),
                message={"role": "tool", "tool_name": "docs__search", "content": "README.md"},
            )

    service = ChatService(
        FakeOllama(),
        CatalogOnly(),
        "test",
        2,
        tool_executor=ReplacementRunner(),
        tool_policy=OCRToolPolicy(),
    )
    result = await service.run([ChatMessage(role="user", content="search")], True, None)
    assert result.tools[0].name == "replacement"
    assert result.message.content == "README에서 찾았습니다."


@pytest.mark.asyncio
async def test_executor_accepts_call_only_client():
    """조회·종료 메서드가 없는 클라이언트만으로 도구 실행을 처리하는지 확인한다."""

    class CallerOnly:
        async def call_tool(self, server, name, arguments) -> MCPToolResult:
            """전달받은 실행 인자를 확인하고 도구 결과만 반환한다."""
            assert (server, name, arguments) == ("docs", "search", {"query": "auth"})
            return MCPToolResult(structured_content={"matches": ["README.md"]})

    tool = MCPTool("docs", "search", "Search docs", {"type": "object"})
    result = await ToolExecutor(CallerOnly(), OCRToolPolicy()).execute(
        {"function": {"name": tool.qualified_name, "arguments": {"query": "auth"}}},
        {tool.qualified_name: tool},
        None,
    )
    assert result.activity.name == "search"
    assert "README.md" in result.message["content"]
