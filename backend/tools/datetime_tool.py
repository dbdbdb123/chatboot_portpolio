"""주입 가능한 시계로 현재 시각을 조회한다."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.schemas.internal_tools import DateTimeArguments
from backend.tools.registry import INTERNAL_SERVER


def utc_now() -> datetime:
    return datetime.now(UTC)


class CurrentDateTimeTool:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

    @property
    def definition(self) -> MCPTool:
        return MCPTool(
            INTERNAL_SERVER, "get_current_datetime",
            "Get current date, time and weekday. timezone is an IANA name; default Asia/Seoul.",
            DateTimeArguments.model_json_schema(),
        )

    async def execute(self, arguments: dict[str, Any]) -> MCPToolResult:
        args = DateTimeArguments.model_validate(arguments)
        try:
            zone = ZoneInfo(args.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown IANA timezone") from exc
        instant = self._clock()
        if instant.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        local = instant.astimezone(zone)
        return MCPToolResult(structured_content={
            "timezone": args.timezone,
            "datetime": local.isoformat(),
            "date": local.date().isoformat(),
            "time": local.timetz().isoformat(),
            "weekday": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[local.weekday()],
            "weekday_ko": ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")[local.weekday()],
            "iso_weekday": local.isoweekday(),
        })
