import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fakes import FakeMCP, FakeOllama

from backend.api.deps import get_chat_service
from backend.api.routes import router
from backend.ollama import OllamaClient
from backend.services.chat import ChatService
from backend.services.tool_policy import OCRToolPolicy
from backend.services.tools import ToolExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize("think", [False, True])
async def test_thinking_reaches_ollama_in_both_modes(think):
    """일반 응답과 스트리밍 모두 reasoning 선택으로 LangChain 모델을 구성한다."""
    seen = []

    class Model:
        async def ainvoke(self, messages):
            seen.append("invoke")
            return AIMessage(content="OK")

        async def astream(self, messages):
            seen.append("stream")
            yield AIMessageChunk(content="OK")

    client = OllamaClient("http://test", 1)
    client._model = lambda model, actual_think: (
        Model() if actual_think is think else pytest.fail("reasoning selection changed")
    )
    try:
        await client.chat("test", [], think=think)
        assert [chunk async for chunk in client.stream_chat("test", [], think=think)]
        assert seen == ["invoke", "stream"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ollama_client_sends_generation_options_to_api():
    """OllamaClient가 GenerationOptions를 ChatOllama 구성값으로 전달한다."""
    from backend.schemas.generation import GenerationOptions

    options = GenerationOptions(temperature=0.3, presence_penalty=0.0, top_k=40)
    client = OllamaClient("http://test", 1, options=options)
    try:
        model = client._model("test", False)
        assert model.temperature == 0.3
        assert model.top_k == 40
        assert client.options.temperature == 0.3
    finally:
        await client.close()


@pytest.mark.parametrize("think", [False, True])
@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_thinking_survives_api_and_tool_rounds(think, endpoint):
    """두 채팅 API에서 도구 호출 후에도 Thinking 선택을 유지하는지 확인한다."""
    choices = []

    class RecordingOllama(FakeOllama):
        async def stream_chat(self, model, messages, tools=None, think=False):
            choices.append(think)
            async for chunk in super().stream_chat(model, messages, tools, think):
                yield chunk

    mcp = FakeMCP()
    service = ChatService(
        RecordingOllama(),
        mcp,
        "test",
        2,
        tool_executor=ToolExecutor(mcp, OCRToolPolicy()),
        tool_policy=OCRToolPolicy(),
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_chat_service] = lambda: service
    with TestClient(app) as client:
        result = client.post(
            endpoint,
            json={
                "messages": [{"role": "user", "content": "search"}],
                "think": think,
            },
        )
    assert result.status_code == 200
    assert choices == [think, think]
    assert "README" in result.text
