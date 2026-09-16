"""공식 LangChain MCP 어댑터를 감싼 게이트웨이의 안전 경계를 검증한다."""

from langchain_core.messages import ToolMessage
import pytest

from backend.dataclass.settings import MCPServerConfig
from backend.mcp import langchain_gateway as module
from backend.mcp.validation import ToolValidationError


class FakeTool:
    """어댑터가 반환하는 BaseTool의 테스트에 필요한 표면만 구현한다."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} 설명"
        self.calls = []

    def get_input_jsonschema(self):
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        }

    async def ainvoke(self, call):
        self.calls.append(call)
        return ToolMessage(
            content=[{"type": "text", "text": "찾음"}],
            artifact={"structured_content": {"count": 1}},
            tool_call_id=call["id"],
            name=self.name,
        )


async def test_official_adapter_connections_allowlist_and_execution(monkeypatch):
    """연결 설정을 공식 클라이언트에 전달하고 허용 도구만 실행하는지 확인한다."""
    clients = []

    class FakeClient:
        def __init__(self, connections, **options):
            self.connections = connections
            self.options = options
            self.tools = {"docs": [FakeTool("search"), FakeTool("delete")]}
            clients.append(self)

        async def get_tools(self, *, server_name=None):
            return self.tools[server_name]

    monkeypatch.setattr(module, "MultiServerMCPClient", FakeClient)
    config = MCPServerConfig.from_dict({
        "name": "docs",
        "transport": "streamable_http",
        "url": "https://mcp.example/mcp",
        "headers": {"Authorization": "Bearer secret"},
        "timeout_seconds": 7,
        "allowed_tools": ["search"],
    })
    gateway = module.LangChainMCPGateway((config,))

    assert clients[0].connections["docs"] == {
        "transport": "streamable_http",
        "url": "https://mcp.example/mcp",
        "headers": {"Authorization": "Bearer secret"},
        "timeout": 7.0,
        "sse_read_timeout": 7.0,
    }
    assert clients[0].options == {"tool_name_prefix": False, "handle_tool_errors": True}
    assert [tool.qualified_name for tool in await gateway.list_tools()] == ["docs__search"]

    with pytest.raises(ToolValidationError):
        await gateway.call_tool("docs", "delete", {"query": "x"})
    with pytest.raises(ToolValidationError):
        await gateway.call_tool("docs", "search", {})

    result = await gateway.call_tool("docs", "search", {"query": "readme"})
    assert result.structured_content == {"count": 1}
    assert result.content == [{"type": "text", "text": "찾음"}]
    assert clients[0].tools["docs"][0].calls[0]["type"] == "tool_call"


def test_stdio_connection_is_converted_without_empty_environment():
    """stdio 설정이 어댑터의 명령·인자·환경 형식으로 변환되는지 확인한다."""
    config = MCPServerConfig.from_dict({
        "name": "local", "command": "python", "args": ["server.py"],
    })
    assert module._connection(config) == {
        "transport": "stdio", "command": "python", "args": ["server.py"], "env": None,
    }
