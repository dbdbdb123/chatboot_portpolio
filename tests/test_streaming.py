import asyncio
import json
from contextlib import aclosing

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_chat_service import FakeMCP, FakeOllama

from backend.api import streaming
from backend.api.deps import get_chat_service
from backend.api.routes import router
from backend.models import ChatMessage, ChatRequest
from backend.ollama import OllamaClient
from backend.services.chat import ChatService
from backend.services.tool_policy import OCRToolPolicy
from backend.services.tools import ToolExecutor


@pytest.mark.asyncio
async def test_sse_keep_alive_and_consumer_close(monkeypatch):
    """추론 대기 중 연결 유지 신호를 보내고 소비자가 닫으면 대기 작업도 정리한다."""
    released = asyncio.Event()

    class WaitingService:
        async def stream(self, *args):
            """첫 이벤트 이후 대기해 전송 계층의 종료 처리를 관찰한다."""
            try:
                yield {"event": "round", "data": {"index": 0}}
                await asyncio.Event().wait()
            finally:
                released.set()

    monkeypatch.setattr(streaming, "SSE_KEEP_ALIVE_SECONDS", 0.001)
    payload = ChatRequest(messages=[ChatMessage(role="user", content="안녕")])
    async with aclosing(streaming.chat_events(payload, WaitingService())) as events:
        assert (await anext(events)).startswith("event: round\n")
        assert await asyncio.wait_for(anext(events), timeout=1) == ": keep-alive\n\n"
    assert released.is_set()


@pytest.mark.asyncio
async def test_delta_arrives_before_generation_finishes_and_close_cancels():
    """추론 완료 전 응답을 전달하고 소비자 종료 시 모델 스트림을 정리하는지 확인한다."""
    released = asyncio.Event()

    class SlowOllama:
        async def stream_chat(self, *args):
            try:
                yield {"content": "서울"}
                await asyncio.Event().wait()
            finally:
                released.set()

    mcp = FakeMCP()
    service = ChatService(
        SlowOllama(),
        mcp,
        "test",
        1,
        tool_executor=ToolExecutor(mcp, OCRToolPolicy()),
        tool_policy=OCRToolPolicy(),
    )
    async with aclosing(
        service.stream([ChatMessage(role="user", content="수도?")], False, None)
    ) as stream:
        assert (await anext(stream))["event"] == "model"
        assert (await anext(stream))["event"] == "round"
        event = await asyncio.wait_for(anext(stream), timeout=1)
        assert event == {"event": "delta", "data": {"text": "서울"}}
    assert released.is_set()


@pytest.mark.asyncio
async def test_tool_stream_returns_activity_then_final_answer():
    """도구 실행 요약 뒤에 답변과 완료 이벤트를 전달하는지 확인한다."""
    mcp = FakeMCP()
    service = ChatService(
        FakeOllama(),
        mcp,
        "test",
        2,
        tool_executor=ToolExecutor(mcp, OCRToolPolicy()),
        tool_policy=OCRToolPolicy(),
    )
    events = [event async for event in service.stream([], True, None)]
    kinds = [event["event"] for event in events]
    assert kinds.index("tool") < kinds.index("delta") < kinds.index("done")
    assert events[-1]["data"]["message"]["content"] == "README에서 찾았습니다."
    assert events[-1]["data"]["tools"][0]["name"] == "search"


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ['{"done":true}', '{"error":"failed"}', ""])
async def test_ollama_ndjson_completion_and_failure(ending):
    """Ollama 스트림의 정상 완료와 오류·미완료 종료를 구분하는지 확인한다."""

    def handle(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, text='{"message":{"content":"안녕"}}\n' + ending + "\n")

    client = OllamaClient("http://test", 1)
    await client.close()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://test"
    )
    try:
        async with aclosing(client.stream_chat("test", [])) as stream:
            assert (await anext(stream))["content"] == "안녕"
            if ending == '{"done":true}':
                with pytest.raises(StopAsyncIteration):
                    await anext(stream)
            else:
                with pytest.raises(RuntimeError):
                    await anext(stream)
    finally:
        await client.close()


@pytest.mark.parametrize("fail", [False, True])
def test_sse_protocol_and_errors(fail):
    """SSE 프레임과 헤더를 유지하고 내부 오류 내용을 사용자에게 숨기는지 확인한다."""

    class Service:
        async def stream(self, *args):
            yield {"event": "delta", "data": {"text": "안녕\n하세요"}}
            if fail:
                raise RuntimeError("private internal detail")
            yield {"event": "done", "data": {"model": "test"}}

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_service] = lambda: Service()
    with TestClient(app) as client:
        response = client.post(
            "/api/chat/stream", json={"messages": [{"role": "user", "content": "안녕"}]}
        )
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    frames = response.text.strip().split("\n\n")
    assert json.loads(frames[0].split("data: ", 1)[1])["text"] == "안녕\n하세요"
    assert ("event: error" if fail else "event: done") in frames[-1]
    assert "private internal detail" not in response.text
