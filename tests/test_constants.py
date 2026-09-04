"""Enum 도입 후 기존 문자열 기반 요청·응답 계약을 검증한다."""

import json

import pytest
from pydantic import ValidationError

from backend.constants.enums import HealthStatus, MCPTransport, MessageRole, StreamEvent
from backend.dataclass.settings import MCPServerConfig
from backend.models import ChatMessage, HealthResponse


@pytest.mark.parametrize("role", ["system", "user", "assistant", "tool"])
def test_message_role_keeps_wire_value(role: str) -> None:
    """기존 문자열 역할을 받아 Enum으로 저장하고 같은 문자열로 직렬화한다."""
    message = ChatMessage(role=role, content="hello")
    assert isinstance(message.role, MessageRole)
    assert json.loads(message.model_dump_json())["role"] == role


def test_unknown_message_role_is_rejected() -> None:
    """정의되지 않은 역할은 기존 요청 검증처럼 거부한다."""
    with pytest.raises(ValidationError):
        ChatMessage(role="unknown", content="hello")


@pytest.mark.parametrize("transport", ["stdio", "streamable_http"])
def test_transport_normalizes_string_configuration(transport: str) -> None:
    """문자열 설정과 직접 생성 모두 전송 방식 Enum으로 정규화한다."""
    config = MCPServerConfig.from_dict(
        {"name": "test", "transport": transport, "command": "python", "url": "http://test/mcp"}
    )
    direct = MCPServerConfig(
        name="test", transport=transport, command="python", url="http://test/mcp"
    )
    assert config.transport is MCPTransport(transport)
    assert direct.transport is config.transport


def test_status_and_events_serialize_as_strings() -> None:
    """상태 응답과 SSE 데이터에서 Enum 이름 대신 기존 문자열 값을 유지한다."""
    response = HealthResponse(status="ok", ollama=True, mcp_servers=0, model="test")
    assert response.status is HealthStatus.OK
    assert json.loads(response.model_dump_json())["status"] == "ok"
    assert str(StreamEvent.DONE) == "done"
    assert json.loads(json.dumps({"event": StreamEvent.DELTA}))["event"] == "delta"
