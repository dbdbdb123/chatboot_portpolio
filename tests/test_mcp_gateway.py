import pytest

from backend.dataclass.settings import MCPServerConfig


@pytest.mark.parametrize(
    "data",
    [
        {"name": "x"},
        {"name": "x", "transport": "bad"},
        {"name": "x", "transport": "streamable_http", "url": "file:///tmp/x"},
        {"name": "x", "command": "python", "timeout_seconds": 0},
    ],
)
def test_invalid_configuration(data):
    """잘못된 MCP 전송 설정과 제한 시간을 거부하는지 확인한다."""
    with pytest.raises(ValueError):
        MCPServerConfig.from_dict(data)
