"""Ollama 추론과 MCP 도구 실행을 조율하는 대화 서비스."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
import json
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage, ToolMessage

from backend.constants.enums import MessageRole, StreamEvent
from backend.prompts.chat import CALCULATION_REVIEW_PROMPT
from backend.schemas.images import ImageAttachment
from backend.mcp.interface import MCPToolCatalog
from backend.schemas import ChatMessage, ChatResponse, ToolActivity
from backend.services.context import build_history
from backend.services.date_validation import is_date_conversation, resolve_date_followup, validate_date_answer
from backend.services.interfaces import ChatModel
from backend.services.tool_policy import ToolPolicy
from backend.services.tools import ToolRunner, build_langchain_tools


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
        tool_runner_factory: Callable[[list[ChatMessage]], ToolRunner] | None = None,
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
        self._tool_runner_factory = tool_runner_factory

    async def _review_calculation(
        self, selected_model: str, history, assistant: AIMessage, think: bool,
    ) -> AIMessage:
        """검산 전용 모델 호출을 실행하고 공개 가능한 최종 답변을 반환한다."""
        review_history = [
            *history, assistant, SystemMessage(content=CALCULATION_REVIEW_PROMPT),
        ]
        reviewed = ""
        async with aclosing(self._ollama.stream_chat(
            selected_model, review_history, None, think,
        )) as chunks:
            async for chunk in chunks:
                chunk_calls = chunk.tool_calls
                if chunk_calls:
                    raise RuntimeError("calculation review requested unavailable tools")
                reviewed += chunk.text
        if not reviewed.strip():
            raise RuntimeError("calculation review returned an empty answer")
        return AIMessage(content=reviewed)

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
        내부 계산 도구 실행 이후의 초안은 보류하고, 최종 답변을 도구 없는 추가 호출로
        한 번 검토한 뒤 전달한다. 이 검토는 도구 실행 라운드 제한과 별개다.
        날짜 문맥의 답변은 버퍼링하고 명시적인 날짜·요일 단정을 달력으로 검산한다.
        마지막 허용 추론에서도 도구를 요청하면 RuntimeError를 발생시킨다.
        소비자 종료 시 모델 생성기를 닫고 정책·모델·실행 오류는 전송 계층에 전달한다.
        """
        selected_model = model or self._default_model
        runner = self._tool_runner_factory(messages) if self._tool_runner_factory else self._tool_executor
        yield {"event": StreamEvent.MODEL, "data": {"model": selected_model}}
        tools = await self._mcp.list_tools() if use_tools else []
        tools = self._tool_policy.prepare_tools(tools, image)
        history = build_history(messages, tools, image)
        activities: list[ToolActivity] = []
        tool_index = {tool.qualified_name: tool for tool in tools}
        bound_tools = build_langchain_tools(tools, runner, image)
        followup = resolve_date_followup(messages) if image is None else None
        if followup is not None:
            answer = followup.clarification
            if followup.value or followup.offset_days is not None:
                if "internal__get_datetime" not in tool_index:
                    answer = "날짜와 요일을 조회하려면 도구 사용을 켜 주세요."
                else:
                    execution = await runner.execute({
                        "name": "internal__get_datetime",
                        "args": ({"value": followup.value} if followup.value else
                                 {"offset_days": followup.offset_days}),
                        "id": "date-followup",
                    }, tool_index, image)
                    activities.append(execution.activity)
                    yield {"event": StreamEvent.TOOL, "data": execution.activity.model_dump()}
                    if execution.activity.is_error:
                        answer = "날짜 조회에 실패했습니다. 잠시 후 다시 시도해 주세요."
                    else:
                        payload = json.loads(str(execution.message.content))
                        if followup.value and payload.get("date") != followup.value:
                            raise RuntimeError("date lookup returned a different date")
                        year, month, day = map(int, payload["date"].split("-"))
                        answer = validate_date_answer(
                            f"{year}년 {month}월 {day}일은 {payload['weekday_ko']}입니다."
                        )
            yield {"event": StreamEvent.DELTA, "data": {"text": answer}}
            result = ChatResponse(
                message=ChatMessage(role=MessageRole.ASSISTANT, content=answer),
                model=selected_model, tools=activities,
            )
            yield {"event": StreamEvent.DONE, "data": result.model_dump()}
            return
        calculation_used = False
        check_dates = is_date_conversation(messages)
        if hasattr(self._ollama, "stream_agent"):
            async for event in self._stream_agent(
                selected_model, history, bound_tools, runner, tool_index,
                image, think, check_dates,
            ):
                yield event
            return
        # 마지막 1회는 도구 결과를 읽은 모델이 최종 답변을 만들 기회다.
        for round_index in range(self._max_tool_rounds + 1):
            yield {"event": StreamEvent.ROUND, "data": {"index": round_index}}
            assistant_chunk: AIMessageChunk | None = None
            async with aclosing(
                self._ollama.stream_chat(
                    selected_model,
                    history,
                    bound_tools or None,
                    think,
                )
            ) as chunks:
                async for chunk in chunks:
                    assistant_chunk = chunk if assistant_chunk is None else assistant_chunk + chunk
                    content = chunk.text
                    if content and not calculation_used and not check_dates:
                        yield {"event": StreamEvent.DELTA, "data": {"text": content}}
            assistant_chunk = assistant_chunk or AIMessageChunk(content="")
            assistant = AIMessage(
                content=assistant_chunk.content,
                tool_calls=assistant_chunk.tool_calls,
                additional_kwargs=assistant_chunk.additional_kwargs,
            )
            calls = assistant.tool_calls
            if not calls:
                if calculation_used:
                    assistant = await self._review_calculation(
                        selected_model, history, assistant, think,
                    )
                if check_dates:
                    assistant = AIMessage(content=validate_date_answer(assistant.text))
                if calculation_used or check_dates:
                    yield {"event": StreamEvent.DELTA, "data": {"text": assistant.text}}
                result = ChatResponse(
                    message=ChatMessage(
                        role=MessageRole.ASSISTANT, content=assistant.text
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
                execution = await runner.execute(call, tool_index, image)
                activities.append(execution.activity)
                yield {"event": StreamEvent.TOOL, "data": execution.activity.model_dump()}
                history.append(execution.message)
                if call.get("name") == "internal__calculate":
                    calculation_used = True
        raise RuntimeError("maximum tool rounds exceeded")

    async def _stream_agent(
        self,
        selected_model: str,
        history: list[BaseMessage],
        bound_tools,
        runner: ToolRunner,
        tool_index,
        image: ImageAttachment | None,
        think: bool,
        check_dates: bool,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Adapt a LangChain ``create_agent`` graph to Mori's existing SSE contract."""
        activities: list[ToolActivity] = []
        pending = []

        def record(execution):
            activities.append(execution.activity)
            pending.append(execution.activity)

        agent_tools = build_langchain_tools(
            list(tool_index.values()), runner, image, on_execution=record,
        )
        final_message: AIMessage | None = None
        completed_history = list(history)
        seen_steps: set[int] = set()
        calculation_used = False

        async for mode, chunk in self._ollama.stream_agent(
            selected_model,
            history,
            agent_tools if bound_tools else [],
            think,
            self._max_tool_rounds + 1,
        ):
            while pending:
                activity = pending.pop(0)
                if activity.server == "internal" and activity.name == "calculate":
                    calculation_used = True
                yield {"event": StreamEvent.TOOL, "data": activity.model_dump()}

            if mode == "messages":
                message, metadata = chunk
                step = metadata.get("langgraph_step")
                if metadata.get("langgraph_node") == "model" and isinstance(step, int):
                    if step not in seen_steps:
                        seen_steps.add(step)
                        yield {"event": StreamEvent.ROUND, "data": {"index": len(seen_steps) - 1}}
                if isinstance(message, AIMessageChunk):
                    text = message.text
                    if text and not calculation_used and not check_dates:
                        yield {"event": StreamEvent.DELTA, "data": {"text": text}}
                continue

            if mode != "updates":
                continue
            for update in chunk.values():
                if not isinstance(update, dict):
                    continue
                for message in update.get("messages", []):
                    if isinstance(message, (AIMessage, ToolMessage)):
                        completed_history.append(message)
                    if isinstance(message, AIMessage) and not message.tool_calls:
                        final_message = message

        while pending:
            activity = pending.pop(0)
            if activity.server == "internal" and activity.name == "calculate":
                calculation_used = True
            yield {"event": StreamEvent.TOOL, "data": activity.model_dump()}

        if final_message is None:
            raise RuntimeError("agent ended without a final response")
        if calculation_used:
            context = (
                completed_history[:-1]
                if completed_history[-1] is final_message
                else completed_history
            )
            final_message = await self._review_calculation(
                selected_model, context, final_message, think,
            )
        if check_dates:
            final_message = AIMessage(content=validate_date_answer(final_message.text))
        if calculation_used or check_dates:
            yield {"event": StreamEvent.DELTA, "data": {"text": final_message.text}}
        result = ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content=final_message.text),
            model=selected_model,
            tools=activities,
        )
        yield {"event": StreamEvent.DONE, "data": result.model_dump()}
