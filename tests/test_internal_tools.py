from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.schemas import ChatMessage
from backend.services.chat import ChatService
from backend.services.tool_policy import OCRToolPolicy
from backend.services.tools import ToolExecutor
from backend.tools.calculator import CalculatorTool, calculate
from backend.tools.composite import CompositeToolClient
from backend.tools.datetime_tool import CurrentDateTimeTool
from backend.tools.registry import InternalToolRegistry


@pytest.mark.parametrize(("expression", "expected"), [
    ("0.1 + 0.2", "0.3"), ("1250000*(1-15/100)", "1062500"),
    ("-(3+2)/2", "-2.5"), ("1/3", "0.3333333333333333333333333333"),
])
def test_decimal_arithmetic(expression, expected):
    assert Decimal(calculate(expression)) == Decimal(expected)


@pytest.mark.parametrize("expression", [
    "__import__('os')", "(1).__class__", "2**999", "1//2", "1/0", "True",
    "[1]", "1e300", "9" * 200, "+".join(["1"] * 100), "", "1+", "1%2",
])
def test_unsafe_or_excessive_calculations_are_rejected(expression):
    with pytest.raises(ValueError):
        calculate(expression)


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{}, {"expression": 123},
    {"expression": "1+2", "extra": True}, {"expression": "1" * 257}])
async def test_calculator_validates_inputs(arguments):
    with pytest.raises(ValueError):
        await CalculatorTool().execute(arguments)


@pytest.mark.asyncio
async def test_timezones_and_date_rollover():
    tool = CurrentDateTimeTool(lambda: datetime(2026, 9, 15, 18, 30, tzinfo=UTC))
    result = (await tool.execute({})).structured_content
    assert result["datetime"] == "2026-09-16T03:30:00+09:00"
    assert result["weekday"] == "Wednesday"
    utc = (await tool.execute({"timezone": "UTC"})).structured_content
    assert utc["date"] == "2026-09-15"
    ny = (await tool.execute({"timezone": "America/New_York"})).structured_content
    assert ny["datetime"] == "2026-09-15T14:30:00-04:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{"timezone": "Mars/City"},
    {"timezone": "../UTC"}, {"timezone": 9}, {"extra": "x"}])
async def test_invalid_timezone_inputs(arguments):
    with pytest.raises(ValueError):
        await CurrentDateTimeTool().execute(arguments)


class RemoteTools:
    async def list_tools(self):
        return [MCPTool("docs", "search", "Search", {"type": "object"})]

    async def call_tool(self, server, name, arguments):
        assert (server, name) == ("docs", "search")
        return MCPToolResult(structured_content={"found": True})


def clients():
    return CompositeToolClient(
        {"internal": InternalToolRegistry([CalculatorTool(), CurrentDateTimeTool()])},
        RemoteTools(),
    )


@pytest.mark.asyncio
async def test_registry_routing_and_unknown_calls():
    client = clients()
    assert len(await client.list_tools()) == 3
    assert (await client.call_tool("docs", "search", {})).structured_content == {"found": True}
    assert (await client.call_tool("internal", "calculate", {"expression": "2+3"})).structured_content["result"] == "5"
    with pytest.raises(ValueError, match="unknown internal"):
        await client.call_tool("internal", "missing", {})
    with pytest.raises(ValueError, match="duplicate"):
        InternalToolRegistry([CalculatorTool(), CalculatorTool()])


@pytest.mark.asyncio
async def test_namespace_collision_is_rejected():
    class Collision(RemoteTools):
        async def list_tools(self):
            return [CalculatorTool().definition]
    client = CompositeToolClient({"internal": InternalToolRegistry([])}, Collision())
    with pytest.raises(ValueError, match="collision"):
        await client.list_tools()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_chat_executes_internal_tool_and_respects_disabled_toggle(enabled):
    class Model:
        calls = 0

        async def stream_chat(self, model, history, tools=None, think=False):
            self.calls += 1
            if not enabled:
                assert tools is None
                yield {"content": "도구 꺼짐"}
            elif self.calls == 1:
                assert any(t["function"]["name"] == "internal__calculate" for t in tools)
                yield {"tool_calls": [{"function": {
                    "name": "internal__calculate", "arguments": {"expression": "0.1+0.2"},
                }}]}
            else:
                assert '"result": "0.3"' in history[-1]["content"]
                yield {"content": "0.3입니다"}

    client = clients()
    policy = OCRToolPolicy()
    service = ChatService(Model(), client, "test", 2,
        tool_executor=ToolExecutor(client, policy), tool_policy=policy)
    result = await service.run([ChatMessage(role="user", content="0.1+0.2")], enabled, None)
    assert result.message.content == ("0.3입니다" if enabled else "도구 꺼짐")
    assert len(result.tools) == int(enabled)
    if enabled:
        assert result.tools[0].server == "internal"
