import asyncio
import json
from contextlib import aclosing

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_chat_service
from backend.api.routes import router
from backend.models import ChatMessage
from backend.ollama import OllamaClient
from backend.services.chat import ChatService
from test_chat_service import FakeMCP, FakeOllama


@pytest.mark.asyncio
async def test_delta_arrives_before_generation_finishes_and_close_cancels():
    released = asyncio.Event()

    class SlowOllama:
        async def stream_chat(self, *args):
            try:
                yield {"content": "서울"}
                await asyncio.Event().wait()
            finally:
                released.set()

    service = ChatService(SlowOllama(), FakeMCP(), "test", 1)
    async with aclosing(service.stream([ChatMessage(role="user", content="수도?")], False, None)) as stream:
        assert (await anext(stream))["event"] == "model"
        assert (await anext(stream))["event"] == "round"
        event = await asyncio.wait_for(anext(stream), timeout=1)
        assert event == {"event": "delta", "data": {"text": "서울"}}
    assert released.is_set()


@pytest.mark.asyncio
async def test_tool_stream_returns_activity_then_final_answer():
    service = ChatService(FakeOllama(), FakeMCP(), "test", 2)
    events = [event async for event in service.stream([], True, None)]
    kinds = [event["event"] for event in events]
    assert kinds.index("tool") < kinds.index("delta") < kinds.index("done")
    assert events[-1]["data"]["message"]["content"] == "README에서 찾았습니다."
    assert events[-1]["data"]["tools"][0]["name"] == "search"


@pytest.mark.asyncio
@pytest.mark.parametrize('ending', ['{"done":true}', '{"error":"failed"}', ''])
async def test_ollama_ndjson_completion_and_failure(ending):
    def handle(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, text='{"message":{"content":"안녕"}}\n' + ending + '\n')

    client = OllamaClient("http://test", 1)
    await client.close()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://test")
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


@pytest.mark.parametrize('fail', [False, True])
def test_sse_protocol_and_errors(fail):
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
        response = client.post('/api/chat/stream', json={"messages": [{"role": "user", "content": "안녕"}]})
    assert response.headers['content-type'].startswith('text/event-stream')
    assert response.headers['x-accel-buffering'] == 'no'
    frames = response.text.strip().split('\n\n')
    assert json.loads(frames[0].split('data: ', 1)[1])['text'] == '안녕\n하세요'
    assert ('event: error' if fail else 'event: done') in frames[-1]
    assert 'private internal detail' not in response.text
