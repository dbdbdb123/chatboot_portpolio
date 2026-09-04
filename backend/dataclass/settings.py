"""파일 및 환경변수에서 읽는 타입 안전한 실행 설정."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from backend.constants.app import DEFAULT_MODEL, PRODUCT_NAME
from backend.constants.environment import (
    DEFAULT_MAX_TOOL_ROUNDS,
    DEFAULT_MCP_TIMEOUT_SECONDS,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ENV_MAX_TOOL_ROUNDS,
    ENV_MCP_SERVERS_JSON,
    ENV_OLLAMA_BASE_URL,
    ENV_OLLAMA_MODEL,
    ENV_REQUEST_TIMEOUT_SECONDS,
)
from backend.constants.paths import SETTINGS_FILE


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    """하나의 MCP 서버 연결 정보와 보안 제한."""
    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    allowed_tools: frozenset[str] = frozenset()
    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS
    transport: str = "stdio"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.transport not in {"stdio", "streamable_http"}:
            raise ValueError("unsupported MCP transport")
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP requires command")
        if self.transport == "streamable_http":
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("HTTP MCP requires an http(s) URL")
        if self.timeout_seconds <= 0:
            raise ValueError("MCP timeout must be positive")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPServerConfig":
        """JSON 객체를 불변 설정으로 정규화한다."""
        return cls(
            name=str(data["name"]),
            command=str(data.get("command", "")),
            transport=str(data.get("transport", "stdio")),
            url=str(data.get("url", "")),
            headers={str(key): str(value) for key, value in data.get("headers", {}).items()},
            args=tuple(str(value) for value in data.get("args", [])),
            env={str(key): str(value) for key, value in data.get("env", {}).items()},
            allowed_tools=frozenset(str(value) for value in data.get("allowed_tools", [])),
            timeout_seconds=float(data.get("timeout_seconds", DEFAULT_MCP_TIMEOUT_SECONDS)),
        )


@dataclass(frozen=True, slots=True)
class Settings:
    """애플리케이션 전체에서 공유하는 불변 설정."""
    app_name: str = PRODUCT_NAME
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_MODEL
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    mcp_servers: tuple[MCPServerConfig, ...] = ()

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "Settings":
        """JSON 설정을 읽고 환경변수로 선택적으로 덮어쓴다.

        우선순위는 환경변수 > 설정 파일 > 코드 기본값 순서다.
        """
        file_data: dict[str, Any] = {}
        try:
            if path.exists():
                decoded_file = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(decoded_file, dict):
                    raise ValueError("settings file must contain a JSON object")
                file_data = decoded_file

            # MCP 서버 목록도 배포 환경에서는 단일 JSON 환경변수로 교체할 수 있다.
            raw_servers = os.getenv(
                ENV_MCP_SERVERS_JSON,
                json.dumps(file_data.get("mcp_servers", []), ensure_ascii=False),
            )
            decoded = json.loads(raw_servers)
            if not isinstance(decoded, list):
                raise ValueError("MCP_SERVERS_JSON must contain a JSON array")
            servers = tuple(MCPServerConfig.from_dict(item) for item in decoded)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid application settings: {exc}") from exc

        return cls(
            app_name=str(file_data.get("app_name", PRODUCT_NAME)),
            ollama_base_url=os.getenv(
                ENV_OLLAMA_BASE_URL,
                str(file_data.get("ollama_base_url", DEFAULT_OLLAMA_BASE_URL)),
            ),
            ollama_model=os.getenv(
                ENV_OLLAMA_MODEL,
                str(file_data.get("ollama_model", DEFAULT_MODEL)),
            ),
            request_timeout_seconds=float(
                os.getenv(
                    ENV_REQUEST_TIMEOUT_SECONDS,
                    str(file_data.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS)),
                )
            ),
            max_tool_rounds=int(
                os.getenv(
                    ENV_MAX_TOOL_ROUNDS,
                    str(file_data.get("max_tool_rounds", DEFAULT_MAX_TOOL_ROUNDS)),
                )
            ),
            mcp_servers=servers,
        )

    @classmethod
    def from_env(cls) -> "Settings":
        """Backward-compatible alias for callers that only used environment settings."""
        return cls.load()
