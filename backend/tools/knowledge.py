"""명시적으로 등록한 UTF-8 문서 스냅샷의 검색과 구간 읽기."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from backend.dataclass.mcp import MCPTool, MCPToolResult
from backend.schemas.internal_tools import ReadKnowledgeArguments, SearchArguments
from backend.tools.registry import INTERNAL_SERVER
from backend.tools.search import match_position, snippet


class KnowledgeStore(Protocol):
    def document_ids(self) -> Sequence[str]: ...
    def read(self, document_id: str) -> str: ...


class DocumentStore:
    """요청 시 파일에 접근하지 않는 읽기 전용 스냅샷. ID는 파일 경로로 실행하지 않는다."""

    def __init__(self, documents: Mapping[str, str]) -> None:
        self._documents = dict(documents)

    def document_ids(self) -> Sequence[str]:
        return tuple(sorted(self._documents))

    def read(self, document_id: str) -> str:
        try:
            return self._documents[document_id]
        except KeyError as exc:
            raise ValueError("unknown document_id; use search_knowledge first") from exc

    @classmethod
    def from_files(cls, root: Path, paths: Sequence[str]) -> "DocumentStore":
        root = root.resolve()
        documents = {}
        for name in paths:
            path = (root / name).resolve()
            if not path.is_relative_to(root) or path.suffix.lower() not in {".md", ".txt"}:
                raise ValueError("document must be a registered text file inside the project")
            if not path.exists():
                continue
            with path.open("rb") as stream:
                raw = stream.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("registered document exceeds 1 MB")
            documents[name] = raw.decode("utf-8-sig")
        return cls(documents)


class SearchKnowledgeTool:
    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    @property
    def definition(self) -> MCPTool:
        return MCPTool(INTERNAL_SERVER, "search_knowledge",
            "Search registered project documentation/FAQ by keywords (all terms must match a line). "
            "Returns document_id and line number for read_knowledge. No web search.",
            SearchArguments.model_json_schema())

    async def execute(self, arguments: dict[str, Any]) -> MCPToolResult:
        args = SearchArguments.model_validate(arguments)
        matches = []
        for document_id in self._store.document_ids():
            for number, line in enumerate(self._store.read(document_id).splitlines(), start=1):
                position = match_position(line, args.query)
                if position is not None:
                    matches.append({"document_id": document_id, "line": number,
                                    "snippet": snippet(line, position)})
        return MCPToolResult(structured_content={
            "matches": matches[:args.limit], "total_matches": len(matches),
        })


class ReadKnowledgeTool:
    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    @property
    def definition(self) -> MCPTool:
        return MCPTool(INTERNAL_SERVER, "read_knowledge",
            "Read a registered document_id from search_knowledge. Lines start at 1. "
            "Returns at most 100 lines and 12000 characters; use next_line for more.",
            ReadKnowledgeArguments.model_json_schema())

    async def execute(self, arguments: dict[str, Any]) -> MCPToolResult:
        args = ReadKnowledgeArguments.model_validate(arguments)
        lines = self._store.read(args.document_id).splitlines()
        if args.start_line > max(1, len(lines)):
            raise ValueError("start_line exceeds document length")
        selected = []
        size = 0
        for number in range(args.start_line, min(len(lines) + 1, args.start_line + args.line_count)):
            line = lines[number - 1]
            if size + len(line) > 12000:
                if not selected:
                    selected.append({"line": number, "text": line[:12000], "truncated": True})
                break
            selected.append({"line": number, "text": line})
            size += len(line)
        end = selected[-1]["line"] if selected else args.start_line - 1
        return MCPToolResult(structured_content={
            "document_id": args.document_id, "lines": selected, "total_lines": len(lines),
            "next_line": end + 1 if end < len(lines) else None,
        })
