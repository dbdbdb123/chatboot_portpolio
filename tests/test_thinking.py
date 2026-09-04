import json

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
@pytest.mark.parametrize('think', [False, True])
async def test_thinking_reaches_ollama_in_both_modes(think):
    seen = []
    def handle(request):
        payload = json.loads(request.content)
        assert payload['think'] is think
        seen.append(payload['stream'])
        if payload['stream']:
            return httpx.Response(200, text='{"message":{"content":"OK"},"done":true}\n')
        return httpx.Response(200, json={'message': {'content': 'OK'}})
    client = OllamaClient('http://test', 1)
    await client.close()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://test')
    try:
        await client.chat('test', [], think=think)
        assert [chunk async for chunk in client.stream_chat('test', [], think=think)]
        assert seen == [False, True]
    finally:
        await client.close()


@pytest.mark.parametrize('think', [False, True])
@pytest.mark.parametrize('endpoint', ['/api/chat', '/api/chat/stream'])
def test_thinking_survives_api_and_tool_rounds(think, endpoint):
    choices = []
    class RecordingOllama(FakeOllama):
        async def stream_chat(self, model, messages, tools=None, think=False):
            choices.append(think)
            yield await self.chat(model, messages, tools)
    service = ChatService(RecordingOllama(), FakeMCP(), 'test', 2)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_service] = lambda: service
    with TestClient(app) as client:
        result = client.post(endpoint, json={
            'messages': [{'role': 'user', 'content': 'search'}], 'think': think,
        })
    assert result.status_code == 200
    assert choices == [think, think]
    assert 'README' in result.text
