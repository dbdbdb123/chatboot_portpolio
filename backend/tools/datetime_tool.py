"""현재·지정 날짜 조회, 시간대 변환과 달력 날짜 이동을 제공한다."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.schemas.internal_tools import DateTimeArguments
from backend.tools.registry import INTERNAL_SERVER


def utc_now() -> datetime:
    return datetime.now(UTC)


def localize(value: datetime, zone: ZoneInfo) -> datetime:
    """존재하지 않거나 중복되는 현지 시각은 임의로 해석하지 않는다."""
    candidates = []
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold)
        restored = candidate.astimezone(UTC).astimezone(zone)
        if restored.replace(tzinfo=None) == value:
            candidates.append(candidate)
    if not candidates:
        raise ValueError("nonexistent local time in timezone")
    if len({candidate.utcoffset() for candidate in candidates}) > 1:
        raise ValueError("ambiguous local time; provide an explicit UTC offset")
    return candidates[0]


class DateTimeTool:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

    @property
    def definition(self) -> MCPTool:
        return MCPTool(
            INTERNAL_SERVER, "get_datetime",
            "Get date, time and weekday for now or an ISO value. Convert to an IANA timezone "
            "(default Asia/Seoul), then optionally shift by offset_days calendar days. "
            "A date-only value means midnight; a value without UTC offset uses timezone.",
            DateTimeArguments.model_json_schema(),
        )

    async def execute(self, arguments: dict[str, Any]) -> MCPToolResult:
        args = DateTimeArguments.model_validate(arguments)
        try:
            zone = ZoneInfo(args.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown IANA timezone") from exc
        if args.value is None:
            instant = self._clock()
        else:
            try:
                instant = datetime.fromisoformat(args.value)
            except ValueError as exc:
                raise ValueError("value must be an ISO date or datetime") from exc
            if instant.utcoffset() is None:
                instant = localize(instant, zone)
        if instant.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        local = instant.astimezone(zone)
        if args.offset_days:
            try:
                shifted = local.replace(tzinfo=None) + timedelta(days=args.offset_days)
            except OverflowError as exc:
                raise ValueError("date shift exceeds supported range") from exc
            local = localize(shifted, zone)
        return MCPToolResult(structured_content={
            "timezone": args.timezone,
            "datetime": local.isoformat(),
            "date": local.date().isoformat(),
            "time": local.timetz().isoformat(),
            "weekday": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[local.weekday()],
            "weekday_ko": ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")[local.weekday()],
            "iso_weekday": local.isoweekday(),
        })


# 기존 조립 코드 및 외부 import와의 하위 호환성.
CurrentDateTimeTool = DateTimeTool
