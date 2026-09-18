"""Mori HTTP API router composition and system endpoints."""

from fastapi import APIRouter, HTTPException, Request

from backend.api.chat_routes import router as chat_router
from backend.api.knowledge_routes import router as knowledge_router
from backend.api.session_routes import router as session_router
from backend.constants.app import API_PREFIX
from backend.constants.enums import HealthStatus
from backend.schemas import HealthResponse

router = APIRouter(prefix=API_PREFIX)
router.include_router(chat_router)
router.include_router(session_router)
router.include_router(knowledge_router)


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    ollama_ok = await request.app.state.ollama.is_available()
    return HealthResponse(
        status=HealthStatus.OK if ollama_ok else HealthStatus.DEGRADED,
        ollama=ollama_ok,
        mcp_servers=len(request.app.state.settings.mcp_servers),
        model=request.app.state.settings.ollama_model,
    )


@router.get("/mcp/tools")
async def list_mcp_tools(request: Request) -> dict[str, object]:
    try:
        tools = await request.app.state.mcp.list_tools()
        return {"tools": [{
            "server": tool.server,
            "name": tool.name,
            "qualified_name": tool.qualified_name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        } for tool in tools]}
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail=f"MCP unavailable: {exc}") from exc


__all__ = ["router"]
