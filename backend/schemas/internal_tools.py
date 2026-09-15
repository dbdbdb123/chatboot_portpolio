"""내부 도구의 입력 검증과 모델에 공개할 JSON 스키마."""

from pydantic import BaseModel, ConfigDict, Field


class DateTimeArguments(BaseModel):
    """IANA 시간대 이름을 받는다."""

    model_config = ConfigDict(extra="forbid", strict=True)
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=100)


class CalculateArguments(BaseModel):
    """제한된 길이의 사칙연산 수식을 받는다."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expression: str = Field(min_length=1, max_length=256)


class SearchArguments(BaseModel):
    """검색어와 반환 개수를 제한한다."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)


class ReadKnowledgeArguments(BaseModel):
    """검색 결과의 문서 ID와 1부터 시작하는 줄 범위를 받는다."""

    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: str = Field(min_length=1, max_length=300)
    start_line: int = Field(default=1, ge=1)
    line_count: int = Field(default=40, ge=1, le=100)
