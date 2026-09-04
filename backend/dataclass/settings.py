"""파일 및 환경변수에서 읽는 타입 안전한 실행 설정."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

from backend.constants.app import DEFAULT_MODEL, PRODUCT_NAME
from backend.constants.enums import MCPTransport
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
    """단일 MCP 서버의 연결 정보와 도구 접근 범위를 담는 설정 객체.

    name은 서버 색인과 도구의 qualified_name 생성에 사용한다.
    stdio는 command·args·env, HTTP는 url·headers를 사용하며,
    allowed_tools가 비어 있으면 모델에 노출하거나 호출할 도구가 없다.
    생성 시 전송 방식을 MCPTransport로 정규화하고 필수 연결값과 시간을 검증한다.
    frozen과 slots로 필드 재할당을 막지만 내부 env·headers 사전까지 불변은 아니다.
    인증 정보가 포함될 수 있는 설정 원문은 응답이나 로그에 출력하지 않는다.
    """

    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    allowed_tools: frozenset[str] = frozenset()
    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS
    transport: MCPTransport = MCPTransport.STDIO
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """설정 생성 직후 전송 방식과 연결 필수값을 검증한다.

        문자열 transport를 MCPTransport로 정규화해 frozen 객체에 반영한다.
        stdio는 command, HTTP는 http(s) 스킴과 호스트가 있는 URL을 요구하며
        timeout_seconds는 양수여야 한다. 잘못된 값은 ValueError로 전달한다.
        실제 서버 연결, 인증 또는 명령 실행 가능 여부는 검사하지 않는다.
        """
        try:
            object.__setattr__(self, "transport", MCPTransport(self.transport))
        except ValueError as exc:
            raise ValueError("unsupported MCP transport") from exc
        if self.transport == MCPTransport.STDIO and not self.command:
            raise ValueError("stdio MCP requires command")
        if self.transport == MCPTransport.STREAMABLE_HTTP:
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("HTTP MCP requires an http(s) URL")
        if self.timeout_seconds <= 0:
            raise ValueError("MCP timeout must be positive")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """JSON 사전을 MCP 서버 설정 객체로 정규화해 반환한다.

        name은 필수이며 생략 가능한 연결값에는 기본값을 적용한다.
        문자열 필드·사전 키와 값·제한 시간을 변환하고 args는 tuple,
        allowed_tools는 frozenset으로 구성한다. 생성 후 연결 필수값 검증도 수행한다.
        누락된 필수 키나 형식 변환·설정 검증 오류는 호출부로 전달한다.
        """
        return cls(
            name=str(data["name"]),
            command=str(data.get("command", "")),
            transport=str(data.get("transport", MCPTransport.STDIO)),
            url=str(data.get("url", "")),
            headers={str(key): str(value) for key, value in data.get("headers", {}).items()},
            args=tuple(str(value) for value in data.get("args", [])),
            env={str(key): str(value) for key, value in data.get("env", {}).items()},
            allowed_tools=frozenset(str(value) for value in data.get("allowed_tools", [])),
            timeout_seconds=float(data.get("timeout_seconds", DEFAULT_MCP_TIMEOUT_SECONDS)),
        )


@dataclass(frozen=True, slots=True)
class Settings:
    """프로세스 시작 시 읽어 앱 구성 요소에 전달하는 공통 실행 설정.

    load는 환경변수, JSON 파일, 코드 기본값 순으로 우선순위를 적용한다.
    모델 주소·이름·요청 제한·도구 실행 라운드와 MCP 서버 설정을 보관하며,
    MCP 서버 목록은 tuple로 정규화한다. from_env는 load의 호환용 진입점이다.
    실행 중 파일 변경을 감시하거나 자동 재적용하지 않으므로 설정 변경 후에는
    앱을 다시 시작해야 한다. frozen은 내부 객체까지 깊은 불변성을 보장하지 않는다.
    """

    app_name: str = PRODUCT_NAME
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_MODEL
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    mcp_servers: tuple[MCPServerConfig, ...] = ()

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> Self:
        """설정 파일과 환경변수에서 앱 실행 설정을 생성해 반환한다.

        path가 존재하면 UTF-8 JSON 객체를 읽고 환경변수로 선택적으로 덮어쓴다.
        우선순위는 환경변수 > 파일 > 코드 기본값이며 MCP 서버 목록은 전체를 교체한다.
        파일 읽기·JSON 구조·서버 설정 구성 오류는 RuntimeError로 감싼다.
        이후 최종 앱 수치 필드 변환에서 발생한 오류는 해당 변환 예외로 전달된다.
        파일이 없으면 기본값과 환경변수를 사용하며 파일 쓰기나 자동 감시는 하지 않는다.
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
    def from_env(cls) -> Self:
        """기존 환경변수 기반 호출부를 위해 공통 설정 로더에 위임한다.

        기본 경로로 load를 실행해 Settings를 반환하며 파일 설정도 함께 적용된다.
        환경변수만 읽는 별도 경로가 아니므로 우선순위와 예외 처리는 load와 같다.
        호출 시마다 설정을 다시 구성하며 결과를 전역 캐시하지 않는다.
        """
        return cls.load()
