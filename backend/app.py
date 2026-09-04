"""FastAPI 애플리케이션 조립 및 리소스 생명주기 관리."""

from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.constants.app import APP_NAME, APP_VERSION
from backend.constants.paths import UI_DIRECTORY
from backend.dataclass.settings import Settings
from backend.mcp.stdio_gateway import ConfiguredMCPGateway
from backend.ollama import OllamaClient
from backend.services.chat import ChatService

@asynccontextmanager
async def lifespan(app: FastAPI):
    """프로세스당 한 번 공유 클라이언트를 생성하고 종료 시 정리한다."""
    settings = Settings.load()
    ollama = OllamaClient(settings.ollama_base_url, settings.request_timeout_seconds)
    mcp = ConfiguredMCPGateway(settings.mcp_servers)
    app.state.settings = settings
    app.state.ollama = ollama
    app.state.mcp = mcp
    app.state.chat_service = ChatService(
        ollama, mcp, settings.ollama_model, settings.max_tool_rounds
    )
    try:
        yield
    finally:
        # 네트워크/서브프로세스 리소스가 예외 상황에서도 닫히도록 보장한다.
        await mcp.close()
        await ollama.close()


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Pydantic's default input field can echo an entire Base64 image.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]})


app.include_router(router)
# API 라우터를 먼저 등록해야 루트 정적 파일 마운트에 가려지지 않는다.
app.mount("/", StaticFiles(directory=UI_DIRECTORY, html=True), name="ui")
