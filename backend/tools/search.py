"""문서와 대화 검색에서 공유하는 단순 키워드 매칭."""


def match_position(text: str, query: str) -> int | None:
    """공백으로 구분한 모든 검색어가 있는 본문에서 첫 위치를 반환한다."""
    folded = text.casefold()
    positions = [folded.find(term) for term in query.casefold().split()]
    return min(positions) if positions and all(pos >= 0 for pos in positions) else None


def snippet(text: str, position: int, length: int = 500) -> str:
    start = max(0, position - 80)
    return text[start:start + length]
