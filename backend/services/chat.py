"""Ollama 추론과 MCP 도구 실행을 조율하는 대화 서비스."""

from __future__ import annotations

import json
from typing import Any

from backend.mcp.interface import MCPGateway
from backend.models import ChatMessage, ChatResponse, ToolActivity
from backend.ollama import OllamaClient


class ChatService:
    """HTTP와 무관한 모델-도구 호출 루프를 담당한다."""
    def __init__(
        self,
        ollama: OllamaClient,
        mcp: MCPGateway,
        default_model: str,
        max_tool_rounds: int,
    ) -> None:
        self._ollama = ollama
        self._mcp = mcp
        self._default_model = default_model
        self._max_tool_rounds = max_tool_rounds

    async def run(
        self, messages: list[ChatMessage], use_tools: bool, model: str | None
    ) -> ChatResponse:
        """최종 텍스트가 생성되거나 최대 도구 반복 횟수에 도달할 때까지 실행한다."""
        selected_model = model or self._default_model
        history: list[dict[str, Any]] = [item.model_dump() for item in messages]
        tools = await self._mcp.list_tools() if use_tools else []
        tool_index = {tool.qualified_name: tool for tool in tools}
        activities: list[ToolActivity] = []

        # 마지막 1회는 도구 결과를 읽은 모델이 최종 답변을 만들 기회다.
        for _ in range(self._max_tool_rounds + 1):
            assistant = await self._ollama.chat(
                selected_model,
                history,
                [tool.as_ollama_tool() for tool in tools] or None,
            )
            calls = assistant.get("tool_calls") or []
            if not calls:
                return ChatResponse(
                    message=ChatMessage(role="assistant", content=str(assistant.get("content", ""))),
                    model=selected_model,
                    tools=activities,
                )
            history.append(assistant)
            for call in calls:
                function = call.get("function", {})
                qualified_name = str(function.get("name", ""))
                # 모델이 임의의 함수명을 만들어도 등록된 도구 외에는 실행하지 않는다.
                tool = tool_index.get(qualified_name)
                if tool is None:
                    raise ValueError(f"model requested unknown tool: {qualified_name}")
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be an object")
                result = await self._mcp.call_tool(tool.server, tool.name, arguments)
                activities.append(ToolActivity(
                    server=tool.server, name=tool.name,
                    arguments=arguments, is_error=result.is_error,
                ))
                # 구조화 결과가 없으면 MCP의 일반 콘텐츠 블록을 모델에 전달한다.
                payload = result.structured_content or {"content": result.content}
                history.append({
                    "role": "tool",
                    "tool_name": qualified_name,
                    "content": json.dumps(payload, ensure_ascii=False),
                })
        raise RuntimeError("maximum tool rounds exceeded")
