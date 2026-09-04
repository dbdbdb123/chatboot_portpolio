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
    """모델 추론과 도구 실행의 순서를 조율하는 대화 애플리케이션 서비스.

    ChatModel, MCPToolCatalog, ToolRunner, ToolPolicy를 외부에서 주입받으며
    HTTP 응답 형식이나 실제 MCP 전송 연결은 직접 관리하지 않는다.
    stream은 모델·라운드·답변 조각·도구·완료 이벤트를 전달하고,
    run은 같은 스트림을 소비해 최종 ChatResponse만 반환한다.
    대화와 실행 기록은 요청 내부에만 두며 영구 저장하지 않는다.
    max_tool_rounds는 실행 라운드 제한이며 마지막 추론 기회를 한 번 더 제공한다.
    """

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
        """앱 조립부가 구성한 모델·도구 조회·실행기·정책을 보관한다.

        ollama는 추론, mcp는 조회, tool_executor는 실행, tool_policy는 노출에 사용한다.
        서비스와 실행기에는 같은 정책을 주입해야 하며 여기서 동일성은 검사하지 않는다.
        default_model과 max_tool_rounds를 저장하고 네트워크 요청은 수행하지 않는다.
        구체 구현 생성과 설정값 검증은 조립부 및 설정 계층에서 담당한다.
        """
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
        """이벤트 스트림을 끝까지 처리해 완료된 ChatResponse만 반환한다.

        대화·도구 선택·모델·Thinking·첨부 인자를 stream에 그대로 전달한다.
        done 이벤트의 데이터를 응답 모델로 검증하고 완료 이벤트가 없으면 RuntimeError를 낸다.
        스트림 처리 중 예외는 그대로 전달하며 종료 시 생성기를 닫는다.
        중간 이벤트를 외부에 반환하거나 대화 이력을 영구 저장하지 않는다.
        """
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
        """정책을 적용한 도구와 대화 문맥으로 추론·실행 루프를 진행한다.

        선택 모델, 추론 라운드, 답변 조각, 도구 요약과 완료 이벤트를 순서에 맞게 생성한다.
        use_tools가 False이면 조회를 생략하고 think는 모든 모델 라운드에 전달한다.
        모델이 호출한 도구 결과를 요청 내부 이력에 추가해 후속 추론에 사용하며,
        thinking은 누적하되 답변 조각 이벤트로 보내지 않는다.
        마지막 허용 추론에서도 도구를 요청하면 RuntimeError를 발생시킨다.
        소비자 종료 시 모델 생성기를 닫고 정책·모델·실행 오류는 전송 계층에 전달한다.
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
