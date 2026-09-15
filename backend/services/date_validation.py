"""날짜 대화의 명시적인 한국어 날짜·요일 단정을 달력으로 검산한다."""

import re
from dataclasses import dataclass
from datetime import date

from backend.schemas import ChatMessage


_DATE_TOPIC = re.compile(
    r"날짜|요일|오늘|내일|어제|모레|그제|\d\s*[년월일]|\d{4}-\d{2}-\d{2}"
    r"|\b(date|weekday|today|tomorrow|yesterday)\b", re.IGNORECASE,
)
_ASSERTION = re.compile(
    r"(?P<date>(?P<year>\d{4})\s*년\s*(?P<month>\d{1,2})\s*월\s*"
    r"(?P<day>\d{1,2})\s*일)"
    r"(?P<link>\s*(?:은|는)?\s*\(?\s*)"
    r"(?P<weekday>[월화수목금토일]요일)"
    r"(?=\s*\)?\s*입니다[.!]?\s*$)"
)
_WEEKDAYS = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")


@dataclass(frozen=True)
class DateFollowup:
    value: str | None = None
    clarification: str = ""
    offset_days: int | None = None


def resolve_date_followup(messages: list[ChatMessage]) -> DateFollowup | None:
    """단순한 '25일은?' 질문의 일자를 보존하고 직전 문맥의 연월만 보충한다."""
    if not messages or messages[-1].role != "user":
        return None
    relative = re.fullmatch(
        r"\s*(오늘|내일|어제|모레|그제|그저께)\s*(?:은|는|이)?\s*"
        r"(?:(?:몇\s*일|며칠|몇\s*요일|무슨\s*요일|날짜)\s*"
        r"(?:이야|인가요|이니|이지|야|이요|이에요|예요|알려줘)?)?\s*[?？.!]*\s*",
        messages[-1].content,
    )
    if relative:
        return DateFollowup(offset_days={
            "오늘": 0, "내일": 1, "어제": -1, "모레": 2, "그제": -2, "그저께": -2,
        }[relative[1]])
    question = re.fullmatch(r"\s*(\d{1,2})\s*일\s*(?:은|는)?\s*[?？]?\s*", messages[-1].content)
    if not question:
        return None
    clarification = DateFollowup(clarification="몇 년 몇 월의 날짜를 말씀하시나요?")
    for message in reversed(messages[:-1]):
        if message.role not in ("user", "assistant"):
            continue
        if "음력" in message.content:
            return DateFollowup(clarification="양력 날짜인가요, 음력 날짜인가요? 연도와 월도 알려주세요.")
        matches = re.findall(r"(?<!\d)(\d{4})\s*(?:년\s*|[-/])(\d{1,2})\s*(?:월|[-/])", message.content)
        if not matches:
            # 다른 주제를 넘어 오래된 날짜를 임의로 가져오지 않는다.
            return clarification
        months = {(int(year), int(month)) for year, month in matches}
        if len(months) != 1:
            return clarification
        year, month = months.pop()
        try:
            requested = date(year, month, int(question[1]))
        except ValueError:
            return DateFollowup(clarification=f"{year}년 {month}월에는 {int(question[1])}일이 없습니다. 날짜를 확인해 주세요.")
        return DateFollowup(value=requested.isoformat())
    return clarification


def is_date_conversation(messages: list[ChatMessage]) -> bool:
    """짧은 후속 질문도 처리하도록 제공된 대화에서 날짜 문맥을 확인한다."""
    return any(_DATE_TOPIC.search(message.content) for message in messages)


def validate_date_answer(answer: str) -> str:
    """명시적인 양력 날짜의 요일 단정만 수정한다. 인용·코드는 변경하지 않는다.

    연월일이 생략된 답, 부정문, 음력 문맥 등은 이 검사의 범위 밖이다.
    사용자 날짜 의도 해석이나 도구 조회 성공 여부를 보장하는 검사는 아니다.
    """
    if any(marker in answer for marker in ('`', '"', "'", '“', '”', '「', '」', '>', '음력')):
        return answer

    def correct(match: re.Match[str]) -> str:
        try:
            value = date(int(match['year']), int(match['month']), int(match['day']))
        except ValueError:
            return match.group(0)
        return match['date'] + match['link'] + _WEEKDAYS[value.weekday()]

    return _ASSERTION.sub(correct, answer)
