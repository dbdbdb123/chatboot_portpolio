from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend.dataclass.settings import MCPServerConfig
from backend.mcp import stdio_gateway as module
from backend.mcp.validation import ToolValidationError


@pytest.mark.parametrize("data", [
    {"name": "x"},
    {"name": "x", "transport": "bad"},
    {"name": "x", "transport": "streamable_http", "url": "file:///tmp/x"},
    {"name": "x", "command": "python", "timeout_seconds": 0},
])
def test_invalid_configuration(data):
    with pytest.raises(ValueError):
        MCPServerConfig.from_dict(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable_http"])
async def test_transport_allowlist_and_cleanup(monkeypatch, transport):
    closed = []
    invoked = []

    @asynccontextmanager
    async def connection(*args, **kwargs):
        if transport == "streamable_http":
            assert args[0] == "http://mcp/mcp"
            assert kwargs["http_client"].headers["Host"] == "localhost"
        try:
            yield (None, None, None) if transport == "streamable_http" else (None, None)
        finally:
            closed.append(True)

    class Session:
        def __init__(self, *args): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def initialize(self): pass
        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(
                name=name, description="test", input_schema={"type": "object"}
            ) for name in ("health", "delete")])
        async def call_tool(self, name, arguments):
            invoked.append(name)
            return SimpleNamespace(content=[], structured_content={"ok": True}, is_error=False)

    monkeypatch.setattr(module, "ClientSession", Session)
    monkeypatch.setattr(module, "streamable_http_client", connection)
    monkeypatch.setattr(module, "stdio_client", connection)
    config = MCPServerConfig.from_dict({
        "name": "ocr", "transport": transport, "command": "python",
        "url": "http://mcp/mcp", "headers": {"Host": "localhost"},
        "allowed_tools": ["health"],
    })
    gateway = module.ConfiguredMCPGateway((config,))
    assert [tool.name for tool in await gateway.list_tools()] == ["health"]
    with pytest.raises(ToolValidationError):
        await gateway.call_tool("ocr", "delete", {})
    result = await gateway.call_tool("ocr", "health", {})
    assert result.structured_content == {"ok": True}
    assert invoked == ["health"]
    assert len(closed) == 2
