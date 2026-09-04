import base64
import json
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from backend.api.deps import get_chat_service
from backend.api.routes import router
from backend.app import validation_error
from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.images import ImageAttachment
from backend.models import ChatMessage, ChatRequest
from backend.services.chat import ChatService
from backend.services.tool_policy import OCRToolPolicy
from backend.services.tools import ToolExecutor


def attachment(image_format: str = "PNG") -> dict[str, str]:
    """테스트용 이미지를 생성해 API 첨부 요청 형식으로 반환한다."""
    out = BytesIO()
    Image.new("RGB", (8, 8), "white").save(out, format=image_format)
    return {
        "name": "sample",
        "mime_type": Image.MIME[image_format],
        "data_base64": base64.b64encode(out.getvalue()).decode(),
    }


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_supported_images(image_format: str) -> None:
    """지원하는 이미지 형식이 실제 내용 검증을 통과하는지 확인한다."""
    assert ImageAttachment(**attachment(image_format)).mime_type.startswith("image/")


@pytest.mark.parametrize(
    "change",
    [
        {"mime_type": "application/pdf"},
        {"mime_type": "image/jpeg"},
        {"data_base64": "invalid!"},
        {"data_base64": base64.b64encode(b"%PDF-1.4 fake").decode()},
    ],
)
def test_reject_invalid_image(change):
    """지원하지 않는 형식과 잘못된 Base64·이미지 내용을 거부하는지 확인한다."""
    with pytest.raises(ValidationError):
        ImageAttachment(**(attachment() | change))


def test_dimensions_and_image_without_tools():
    """해상도 제한과 도구를 끈 이미지 요청의 허용 여부를 확인한다."""
    out = BytesIO()
    Image.new("RGB", (8001, 1)).save(out, format="PNG")
    with pytest.raises(ValidationError):
        ImageAttachment(
            **(attachment() | {"data_base64": base64.b64encode(out.getvalue()).decode()})
        )
    assert ChatRequest(
        messages=[ChatMessage(role="user", content="describe")], use_tools=False, image=attachment()
    ).image


def test_validation_does_not_echo_file():
    """검증 오류 응답에 첨부 파일의 Base64 원문이 포함되지 않는지 확인한다."""
    payload = attachment() | {"mime_type": "application/pdf"}
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.dependency_overrides[get_chat_service] = lambda: None
    response = TestClient(app).post(
        "/api/chat/stream",
        json={
            "messages": [{"role": "user", "content": "read"}],
            "image": payload,
        },
    )
    assert response.status_code == 422
    assert payload["data_base64"] not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("think", [True, False])
@pytest.mark.parametrize("ocr", [True, False])
async def test_qwen_selects_ocr_only_when_needed(think, ocr):
    """모델이 선택한 경우에만 OCR을 실행하고 원문이 실행 요약에 노출되지 않는지 확인한다."""
    img = ImageAttachment(**attachment())
    calls = []

    class MCP:
        async def list_tools(self):
            return [MCPTool("ocr", "inspect_document", "OCR", {"type": "object"})]

        async def call_tool(self, server, name, arguments):
            calls.append(name)
            assert arguments == {"data_base64": img.data_base64, "mime_type": "image/png"}
            return MCPToolResult(structured_content={"text": "invoice 123"})

    class Ollama:
        rounds = 0

        async def stream_chat(self, model, history, tools, actual_think):
            self.rounds += 1
            assert actual_think is think
            assert history[1]["images"] == [img.data_base64]
            assert img.data_base64 not in json.dumps(tools)
            assert "data_base64" not in json.dumps(tools)
            if ocr and self.rounds == 1:
                yield {
                    "tool_calls": [{"function": {"name": "ocr__inspect_document", "arguments": {}}}]
                }
            else:
                if ocr:
                    assert "invoice 123" in history[-1]["content"]
                yield {"content": "Invoice 123" if ocr else "A white image"}

    mcp = MCP()
    service = ChatService(
        Ollama(),
        mcp,
        "test",
        3,
        tool_executor=ToolExecutor(mcp, OCRToolPolicy()),
        tool_policy=OCRToolPolicy(),
    )
    events = [
        e
        async for e in service.stream(
            [ChatMessage(role="user", content="OCR please" if ocr else "describe")],
            True,
            None,
            think,
            img,
        )
    ]
    assert events[-1]["event"] == "done"
    assert img.data_base64 not in json.dumps(events)
    assert calls == (["inspect_document"] if ocr else [])


@pytest.mark.asyncio
async def test_vision_works_with_tools_off():
    """도구를 끈 경우 MCP 조회 없이 이미지를 모델에 전달하는지 확인한다."""
    img = ImageAttachment(**attachment())

    class MCP:
        async def list_tools(self):
            """도구를 끈 요청에서 조회가 발생하면 테스트를 실패시킨다."""
            raise AssertionError("Tools disabled")

    class DisabledRunner:
        async def execute(self, call, tool_index, image):
            """도구를 끈 요청에서 실행이 발생하면 테스트를 실패시킨다."""
            raise AssertionError("Tools disabled")

    class Ollama:
        async def stream_chat(self, model, history, tools, think):
            assert tools is None
            assert history[-1]["images"] == [img.data_base64]
            yield {"content": "white image"}

    mcp = MCP()
    result = await ChatService(
        Ollama(), mcp, "test", 3, tool_executor=DisabledRunner(), tool_policy=OCRToolPolicy()
    ).run([ChatMessage(role="user", content="describe")], False, None, False, img)
    assert result.message.content == "white image"
    assert result.tools == []
