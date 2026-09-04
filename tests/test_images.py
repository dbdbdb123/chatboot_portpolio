import base64
import json
from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError
from fastapi.testclient import TestClient

from backend.app import validation_error
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from backend.api.routes import router
from backend.api.deps import get_chat_service
from backend.images import ImageAttachment
from backend.models import ChatRequest, ChatMessage
from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.services.chat import ChatService


def attachment(format="PNG"):
    out = BytesIO()
    Image.new("RGB", (8, 8), "white").save(out, format=format)
    return {"name": "sample", "mime_type": Image.MIME[format],
            "data_base64": base64.b64encode(out.getvalue()).decode()}


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_supported_images(format):
    assert ImageAttachment(**attachment(format)).mime_type.startswith("image/")


@pytest.mark.parametrize("change", [
    {"mime_type": "application/pdf"},
    {"mime_type": "image/jpeg"},
    {"data_base64": "invalid!"},
    {"data_base64": base64.b64encode(b"%PDF-1.4 fake").decode()},
])
def test_reject_invalid_image(change):
    with pytest.raises(ValidationError):
        ImageAttachment(**(attachment() | change))


def test_dimensions_and_image_without_tools():
    out = BytesIO()
    Image.new("RGB", (8001, 1)).save(out, format="PNG")
    with pytest.raises(ValidationError):
        ImageAttachment(**(attachment() | {"data_base64": base64.b64encode(out.getvalue()).decode()}))
    assert ChatRequest(messages=[ChatMessage(role="user", content="describe")],
                       use_tools=False, image=attachment()).image


def test_validation_does_not_echo_file():
    payload = attachment() | {"mime_type": "application/pdf"}
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.dependency_overrides[get_chat_service] = lambda: None
    response = TestClient(app).post("/api/chat/stream", json={
        "messages": [{"role": "user", "content": "read"}], "image": payload,
    })
    assert response.status_code == 422
    assert payload["data_base64"] not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("think", [True, False])
@pytest.mark.parametrize("ocr", [True, False])
async def test_qwen_selects_ocr_only_when_needed(think, ocr):
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
                yield {"tool_calls": [{"function": {"name": "ocr__inspect_document", "arguments": {}}}]}
            else:
                if ocr:
                    assert "invoice 123" in history[-1]["content"]
                yield {"content": "Invoice 123" if ocr else "A white image"}
    service = ChatService(Ollama(), MCP(), "test", 3)
    events = [e async for e in service.stream(
        [ChatMessage(role="user", content="OCR please" if ocr else "describe")], True, None, think, img)]
    assert events[-1]["event"] == "done"
    assert img.data_base64 not in json.dumps(events)
    assert calls == (["inspect_document"] if ocr else [])


@pytest.mark.asyncio
async def test_vision_works_with_tools_off():
    img = ImageAttachment(**attachment())
    class MCP:
        async def list_tools(self):
            raise AssertionError("Tools disabled")
    class Ollama:
        async def stream_chat(self, model, history, tools, think):
            assert tools is None
            assert history[-1]["images"] == [img.data_base64]
            yield {"content": "white image"}
    result = await ChatService(Ollama(), MCP(), "test", 3).run(
        [ChatMessage(role="user", content="describe")], False, None, False, img)
    assert result.message.content == "white image"
    assert result.tools == []
