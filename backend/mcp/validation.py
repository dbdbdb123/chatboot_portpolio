"""모델이 생성한 MCP 도구 인자를 위한 경량 검증기."""

from __future__ import annotations

from typing import Any


class ToolValidationError(ValueError):
    """도구 허용 목록 또는 입력 스키마 검증 실패."""

    pass


def validate_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate the safe JSON-Schema subset used by initial read-only tools."""
    if schema.get("type", "object") != "object":
        raise ToolValidationError("tool input schema must describe an object")
    properties = schema.get("properties", {})
    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        raise ToolValidationError(f"missing required arguments: {', '.join(missing)}")
    if schema.get("additionalProperties", True) is False:
        extras = set(arguments) - set(properties)
        if extras:
            raise ToolValidationError(f"unexpected arguments: {', '.join(sorted(extras))}")
    # 초기 읽기 전용 도구에 필요한 JSON Schema 기본 타입만 지원한다.
    type_map: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None),
    }
    for name, value in arguments.items():
        expected_name = properties.get(name, {}).get("type")
        expected = type_map.get(expected_name)
        if expected is not None and not isinstance(value, expected):
            raise ToolValidationError(f"argument '{name}' must be {expected_name}")
