"""LangChain 프롬프트에 시스템 지침과 현재 대화 이력을 결합한다."""

from typing import Any

from langchain_core.messages import ChatMessage as LangChainMessage

from backend.dataclass.mcp import MCPTool
from backend.schemas.images import ImageAttachment
from backend.schemas import ChatMessage
from backend.prompts.chat import CHAT_PROMPT, build_request_guidance




def build_history(
    messages: list[ChatMessage],
    tools: list[MCPTool],
    image: ImageAttachment | None,
) -> list[dict[str, Any]]:
    """요청별 이력을 역할·순서 그대로 주입하고 Ollama 입력으로 변환한다.

    대화 본문을 템플릿 문자열로 해석하지 않으며 공유 메모리에 저장하지 않는다.
    클라이언트는 매 요청에 이전 대화와 현재 사용자 메시지를 함께 보내야 한다.
    """
    prompt = CHAT_PROMPT.invoke(
        {
            "request_guidance": build_request_guidance(tools, image is not None),
            "history": [
                LangChainMessage(role=message.role.value, content=message.content)
                for message in messages
            ],
        }
    )
    history = [
        {
            "role": message.role if isinstance(message, LangChainMessage) else message.type,
            "content": message.content,
        }
        for message in prompt.to_messages()
    ]
    if image:
        history[-1]["images"] = [image.data_base64]
    return history
