"""채팅 입력과 스트리밍 전송의 공통 제한값."""

MAX_CHAT_MESSAGES = 100
SSE_KEEP_ALIVE_SECONDS = 15
SSE_MEDIA_TYPE = "text/event-stream"
SSE_KEEP_ALIVE_FRAME = ": keep-alive\n\n"
STREAM_ERROR_MESSAGE = "응답 생성 중 오류가 발생했습니다. 다시 시도해 주세요."
OCR_TOOL_NAME = "inspect_document"
