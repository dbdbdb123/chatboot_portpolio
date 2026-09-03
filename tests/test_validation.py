import pytest

from backend.mcp.validation import ToolValidationError, validate_arguments


SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
    "required": ["query"],
    "additionalProperties": False,
}


def test_accepts_valid_arguments() -> None:
    validate_arguments({"query": "auth", "limit": 3}, SCHEMA)


@pytest.mark.parametrize("arguments", [{}, {"query": 42}, {"query": "auth", "write": True}])
def test_rejects_invalid_arguments(arguments: dict[str, object]) -> None:
    with pytest.raises(ToolValidationError):
        validate_arguments(arguments, SCHEMA)
