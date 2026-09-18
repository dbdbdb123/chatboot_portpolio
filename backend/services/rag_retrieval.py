"""Hybrid lexical/vector retrieval and multi-query result fusion."""

import asyncio
import math
import re


def terms(text):
    words = re.findall(r"[a-z0-9_]+|[가-힣]+", text.lower())
    return {token for word in words for token in (
        [word] + ([word[i:i+2] for i in range(len(word)-1)] if re.search("[가-힣]", word) else [])
    ) if len(token) > 1}


def cosine(left, right):
    if len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    return sum(x*y for x, y in zip(left, right)) / denominator if denominator else 0.0


class HybridRetriever:
    def __init__(self, service) -> None:
        self.service = service

    async def search(self, query):
        service = self.service
        if not await asyncio.to_thread(service.store.documents):
            return []
        vector = (await service.embed(["task: search result | query: " + query]))[0]
        query_terms = terms(query)
        rows = await asyncio.to_thread(
            service.store.candidates, service.embedding_model, vector, sorted(query_terms),
        )
        candidates = []
        for chunk in rows:
            lexical = len(query_terms & terms(chunk["text"])) / max(1, len(query_terms))
            semantic = chunk["semantic"]
            if lexical < 0.12 and semantic < 0.55:
                continue
            candidates.append({**chunk, "score": 0.65 * semantic + 0.35 * lexical})
        candidates.sort(key=lambda item: item["score"], reverse=True)
        selected = []
        for chunk in candidates:
            if any(chunk["id"] == old["id"] and chunk.get("page") == old.get("page")
                   and chunk["start"] <= old["end"] and old["start"] <= chunk["end"]
                   for old in selected):
                continue
            selected.append(chunk)
            if len(selected) == 3:
                break
        return selected

    async def search_queries(self, queries):
        rankings = await asyncio.gather(*(self.search(query) for query in dict.fromkeys(queries)))
        fused: dict[tuple, dict] = {}
        for ranking in rankings:
            for rank, chunk in enumerate(ranking, 1):
                key = (chunk["id"], chunk.get("page"), chunk.get("ordinal"),
                       chunk["start"], chunk["end"])
                current = fused.setdefault(key, {**chunk, "rrf": 0.0})
                current["rrf"] += 1 / (60 + rank)
                current["score"] = max(current.get("score", 0.0), chunk.get("score", 0.0))
        return sorted(fused.values(), key=lambda item: (item["rrf"], item["score"]), reverse=True)[:3]

    async def context(self, query, search_queries=None):
        broad = re.search(
            r"요약|정리|전체|핵심\s*(?:내용|경력|강점)|경력\s*(?:전체|사항|기술서)\s*(?:요약|정리)?"
            r"|자기소개\s*(?:작성|요약|정리)|지원자\s*(?:요약|정리|강점)"
            r"|\b(summary|summarize|overview)\b", query, re.IGNORECASE,
        )
        queries = search_queries or [query]
        if not broad:
            return await self.search_queries(queries)
        matches = await self.search_queries(queries)
        document_ids = list(dict.fromkeys(chunk["id"] for chunk in matches))
        if not document_ids:
            documents = await asyncio.to_thread(self.service.store.documents)
            if len(documents) != 1:
                return []
            document_ids = [documents[0]["id"]]
        chunks = await asyncio.to_thread(
            self.service.store.document_chunks, self.service.embedding_model, document_ids,
        )
        selected, size = [], 0
        for chunk in chunks:
            if size + len(chunk["text"]) > 9000:
                break
            selected.append(chunk)
            size += len(chunk["text"])
        return selected
