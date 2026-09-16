"""FastAPI 애플리케이션 조립 및 리소스 생명주기 관리."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.constants.app import APP_NAME, APP_VERSION
from backend.constants.environment import ENV_REDIS_URL
from backend.constants.paths import PROJECT_ROOT, UI_DIRECTORY
from backend.dataclass.settings import Settings
from backend.mcp.langchain_gateway import LangChainMCPGateway
from backend.ollama import OllamaClient
from backend.services.chat import ChatService
from backend.services.rag import RagService, RagStore
from backend.services.tool_policy import OCRToolPolicy
from backend.services.history import create_redis_history_store
from backend.services.tools import ToolExecutor
from backend.tools.calculator import CalculatorTool
from backend.tools.composite import CompositeToolClient
from backend.tools.datetime_tool import DateTimeTool
from backend.tools.registry import INTERNAL_SERVER, InternalToolRegistry
from backend.tools.conversation import SearchConversationTool
from backend.tools.knowledge import DocumentStore, ReadKnowledgeTool, SearchKnowledgeTool
from backend.schemas import ChatMessage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """프로세스당 한 번 공유 클라이언트를 생성하고 종료 시 정리한다."""
    settings = Settings.load()
    if any(server.name == INTERNAL_SERVER for server in settings.mcp_servers):
        raise ValueError("MCP server name 'internal' is reserved for built-in tools")
    knowledge = DocumentStore.from_files(PROJECT_ROOT, ["README.md", "docs/DEVELOPMENT.md"])
    ollama = OllamaClient(settings.ollama_base_url, settings.request_timeout_seconds,
                          options=settings.generation)
    mcp = LangChainMCPGateway(settings.mcp_servers)
    app.state.settings = settings
    app.state.ollama = ollama
    app.state.mcp = mcp
    app.state.history_store = None

    # Redis는 선택 기능이다. REDIS_URL이 없으면 기존 무상태 채팅을 그대로 유지한다.
    # URL이 설정됐지만 연결할 수 없는 경우에도 모델 채팅은 실행하고 기록 기능만 비활성화한다.
    redis_url = os.environ.get(ENV_REDIS_URL)
    if redis_url:
        history_store = create_redis_history_store(redis_url)
        try:
            await history_store.ping()
            app.state.history_store = history_store
        except Exception:
            logger.exception("Redis chat history is unavailable")
            await history_store.close()
    tool_policy = OCRToolPolicy()
    shared_tools = [DateTimeTool(), CalculatorTool(),
                    SearchKnowledgeTool(knowledge), ReadKnowledgeTool(knowledge)]
    tools = CompositeToolClient(
        {INTERNAL_SERVER: InternalToolRegistry([*shared_tools, SearchConversationTool([])])},
        fallback=mcp,
    )

    def request_runner(messages: list[ChatMessage]) -> ToolExecutor:
        # 마지막 사용자 질문은 검색 대상에서 제외하고 앞선 대화만 복사한다.
        previous = messages[:-1] if messages and messages[-1].role == "user" else messages
        client = CompositeToolClient(
            {INTERNAL_SERVER: InternalToolRegistry([
                *shared_tools, SearchConversationTool(previous),
            ])}, fallback=mcp,
        )
        return ToolExecutor(client, tool_policy)

    app.state.chat_service = ChatService(
        ollama,
        tools,
        settings.ollama_model,
        settings.max_tool_rounds,
        tool_executor=ToolExecutor(tools, tool_policy),
        tool_policy=tool_policy,
        tool_runner_factory=request_runner,
    )
    rag_model = OllamaClient(settings.ollama_base_url, settings.request_timeout_seconds,
        options=settings.generation.model_copy(update={"num_ctx": 8192, "num_predict": 768}))
    app.state.rag_service = RagService(
        RagStore(os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"),
                 os.environ.get("QDRANT_API_KEY"), os.environ.get("RAG_COLLECTION", "mori")),
        rag_model, settings.ollama_model, settings.ollama_base_url,
        os.environ.get("RAG_EMBEDDING_MODEL", "embeddinggemma"),
    )
    try:
        yield
    finally:
        if app.state.history_store is not None:
            await app.state.history_store.close()
        await app.state.rag_service.close()
        await rag_model.close()
        # 네트워크/서브프로세스 리소스가 예외 상황에서도 닫히도록 보장한다.
        await mcp.close()
        await ollama.close()


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """첨부 원문이 노출되지 않도록 입력값을 제외한 검증 오류만 반환한다."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                for error in exc.errors()
            ]
        },
    )


app.include_router(router)
# API 라우터를 먼저 등록해야 루트 정적 파일 마운트에 가려지지 않는다.
app.mount("/", StaticFiles(directory=UI_DIRECTORY, html=True), name="ui")
