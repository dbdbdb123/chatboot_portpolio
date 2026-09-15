"""현재 요청의 대화 스냅샷만 검색한다. 전역 대화 저장소를 사용하지 않는다."""

from collections.abc import Sequence
from typing import Any

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.schemas import ChatMessage
from backend.schemas.internal_tools import SearchArguments
from backend.tools.registry import INTERNAL_SERVER
from backend.tools.search import match_position, snippet


class SearchConversationTool:
    def __init__(self, messages: Sequence[ChatMessage]) -> None:
        self._messages = tuple(
            (index, message.role.value, message.content)
            for index, message in enumerate(messages, start=1)
            if message.role in ("user", "assistant")
        )

    @property
    def definition(self) -> MCPTool:
        return MCPTool(INTERNAL_SERVER, "search_conversation",
            "Search earlier user/assistant messages in this request using keywords. "
            "Newest matches first. No access to other sessions or omitted history.",
            SearchArguments.model_json_schema())

    async def execute(self, arguments: dict[str, Any]) -> MCPToolResult:
        args = SearchArguments.model_validate(arguments)
        results = []
        for index, role, content in reversed(self._messages):
            position = match_position(content, args.query)
            if position is not None:
                results.append({"message_index": index, "role": role,
                                "snippet": snippet(content, position)})
        return MCPToolResult(structured_content={
            "scope": "current_request", "matches": results[:args.limit],
            "total_matches": len(results),
        })
