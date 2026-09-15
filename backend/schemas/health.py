"""상태 조회 응답의 Pydantic 스키마."""

from pydantic import BaseModel

from backend.constants.enums import HealthStatus


class HealthResponse(BaseModel):
    """웹 앱에서 확인한 추론 서버 응답 여부와 구성 상태를 표현한다.

    ollama는 모델 목록 API의 접근 가능 여부이며 status는 이를 기반으로 결정한다.
    mcp_servers는 설정에 등록된 서버 수, model은 설정된 기본 모델명이다.
    MCP 연결 성공, 모델 다운로드 완료 또는 실제 추론 성공까지 보장하지 않는다.
    """

    status: HealthStatus
    ollama: bool
    mcp_servers: int
    model: str

