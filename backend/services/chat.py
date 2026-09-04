"""Ollama 추론과 MCP 도구 실행을 조율하는 대화 서비스."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

from backend.constants.enums import MessageRole, StreamEvent
from backend.images import ImageAttachment
from backend.mcp.interface import MCPToolCatalog
from backend.models import ChatMessage, ChatResponse, ToolActivity
from backend.services.context import build_history
from backend.services.interfaces import ChatModel
from backend.services.tool_policy import ToolPolicy
from backend.services.tools import ToolRunner


class ChatService:
    """HTTP와 무관한 모델-도구 호출 루프를 담당한다."""

    def __init__(
        self,
        ollama: ChatModel,
        mcp: MCPToolCatalog,
        default_model: str,
        max_tool_rounds: int,
        *,
        tool_executor: ToolRunner,
        tool_policy: ToolPolicy,
    ) -> None:
        """외부에서 조립한 추론·도구 조회·실행 구현과 대화 제한 설정을 보관한다."""
        self._ollama = ollama
        self._mcp = mcp
        self._tool_executor = tool_executor
        self._tool_policy = tool_policy
        self._default_model = default_model
        self._max_tool_rounds = max_tool_rounds

    async def run(
        self,
        messages: list[ChatMessage],
        use_tools: bool,
        model: str | None,
        think: bool = False,
        image: ImageAttachment | None = None,
    ) -> ChatResponse:
        """대화 스트림을 소비해 최종 응답을 반환하고 완료 없이 끝나면 오류를 낸다."""
        async with aclosing(self.stream(messages, use_tools, model, think, image)) as events:
            async for event in events:
                if event["event"] == StreamEvent.DONE:
                    return ChatResponse.model_validate(event["data"])
        raise RuntimeError("chat ended before completion")

    async def stream(
        self,
        messages: list[ChatMessage],
        use_tools: bool,
        model: str | None,
        think: bool = False,
        image: ImageAttachment | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """모델 추론과 검증된 MCP 호출을 반복하며 응답·도구·완료 이벤트를 전달한다.

        도구 결과를 대화에 추가해 다음 추론에 사용하며, 호출 횟수 제한을 적용한다.
        첨부 이미지의 실제 데이터는 OCR 실행 인자에만 넣고 실행 요약에서는 숨긴다.
        """
        selected_model = model or self._default_model
        yield {"event": StreamEvent.MODEL, "data": {"model": selected_model}}
        tools = await self._mcp.list_tools() if use_tools else []
        tools = self._tool_policy.prepare_tools(tools, image)
        history = build_history(messages, tools, image)
        activities: list[ToolActivity] = []
        tool_index = {tool.qualified_name: tool for tool in tools}
        # 마지막 1회는 도구 결과를 읽은 모델이 최종 답변을 만들 기회다.
        for round_index in range(self._max_tool_rounds + 1):
            yield {"event": StreamEvent.ROUND, "data": {"index": round_index}}
            assistant: dict[str, Any] = {
                "role": MessageRole.ASSISTANT,
                "content": "",
                "thinking": "",
                "tool_calls": [],
            }
            async with aclosing(
                self._ollama.stream_chat(
                    selected_model,
                    history,
                    [tool.as_ollama_tool() for tool in tools] or None,
                    think,
                )
            ) as chunks:
                async for chunk in chunks:
                    content = chunk.get("content") or ""
                    assistant["content"] += content
                    assistant["thinking"] += chunk.get("thinking") or ""
                    assistant["tool_calls"].extend(chunk.get("tool_calls") or [])
                    if content:
                        yield {"event": StreamEvent.DELTA, "data": {"text": content}}
            calls = assistant.get("tool_calls") or []
            if not calls:
                result = ChatResponse(
                    message=ChatMessage(
                        role=MessageRole.ASSISTANT, content=str(assistant.get("content", ""))
                    ),
                    model=selected_model,
                    tools=activities,
                )
                yield {"event": StreamEvent.DONE, "data": result.model_dump()}
                return
            if round_index == self._max_tool_rounds:
                raise RuntimeError("maximum tool rounds exceeded")
            history.append(assistant)
            for call in calls:
                execution = await self._tool_executor.execute(call, tool_index, image)
                activities.append(execution.activity)
                yield {"event": StreamEvent.TOOL, "data": execution.activity.model_dump()}
                history.append(execution.message)
        raise RuntimeError("maximum tool rounds exceeded")
