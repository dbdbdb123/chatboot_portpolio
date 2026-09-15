"""도구 실행 요약의 Pydantic 스키마."""

from typing import Any

from pydantic import BaseModel


class ToolActivity(BaseModel):
    """도구 실행 후 사용자 화면에 공개할 요약 데이터.

    server와 name은 실행 대상을 식별하고 arguments는 정책이 정한 공개용 인자다.
    OCR의 경우 실제 Base64 대신 파일명과 MIME만 기록한다.
    is_error는 도구 결과의 실패 상태이며 전체 대화의 완료 여부를 의미하지 않는다.
    모델 자체가 인자를 마스킹하지 않으므로 생성자가 안전한 공개값을 제공해야 한다.
    """

    server: str
    name: str
    arguments: dict[str, Any]
    is_error: bool = False

