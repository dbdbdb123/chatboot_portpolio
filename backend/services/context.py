"""API 메시지를 LangChain 표준 메시지와 시스템 프롬프트로 결합한다."""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from backend.dataclass.mcp import MCPTool
from backend.prompts.chat import CHAT_PROMPT, build_request_guidance
from backend.schemas import ChatMessage
from backend.schemas.images import ImageAttachment


def build_history(
    messages: list[ChatMessage], tools: list[MCPTool], image: ImageAttachment | None,
) -> list[BaseMessage]:
    """외부 DTO를 역할과 순서를 보존한 LangChain ``BaseMessage`` 목록으로 변환한다.

    이미지는 마지막 사용자 메시지의 표준 멀티모달 콘텐츠 블록으로 연결한다.
    API DTO와 원본 배열은 변경하지 않는다.
    """
    history: list[BaseMessage] = []
    for index, message in enumerate(messages):
        if message.role == "user":
            history.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            history.append(AIMessage(content=message.content))
        elif message.role == "system":
            history.append(SystemMessage(content=message.content))
        else:
            # 외부 API의 과거 tool 메시지에는 호출 ID가 없으므로 안정적인 합성 ID를 부여한다.
            history.append(ToolMessage(
                content=message.content, tool_call_id=f"history-tool-{index}"
            ))
    if image:
        latest = history[-1]
        latest.content = [
            {"type": "text", "text": str(latest.content)},
            {"type": "image_url", "image_url": (
                f"data:{image.mime_type};base64,{image.data_base64}"
            )},
        ]
    prompt = CHAT_PROMPT.invoke({
        "request_guidance": build_request_guidance(tools, image is not None),
        "history": history,
    })
    return prompt.to_messages()
