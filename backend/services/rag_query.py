"""Conversation-aware RAG query normalization and rewriting."""

import re

from langchain_core.messages import HumanMessage, SystemMessage

COLLOQUIAL_QUERY = re.compile(
    r"(?:그거|이거|저거|거기|그곳|그 사람|이 사람|뭐|무엇|누구|어디|어떻게|왜|"
    r"했어|썼어|쓰는지|인가요|거야|알려\s*줘|보여\s*줘|찾아\s*줘|\?)"
)
TECH_TERMS = {
    "레디스": "Redis", "큐드란트": "Qdrant", "랭체인": "LangChain",
    "올라마": "Ollama", "임베딩 젬마": "embeddinggemma", "벡터 디비": "벡터 DB",
}


def normalize_search_query(query: str) -> str:
    normalized = " ".join(query.split())
    for source, target in TECH_TERMS.items():
        normalized = re.sub(re.escape(source), target, normalized, flags=re.IGNORECASE)
    return normalized


class RagQueryRewriter:
    def __init__(self, model) -> None:
        self.model = model

    async def rewrite(self, messages, selected_model):
        original = normalize_search_query(messages[-1].content)
        history = messages[:-1]
        if not history and not COLLOQUIAL_QUERY.search(original):
            return original
        recent = []
        for message in history[-4:]:
            content = message.content.split("\n\n검색한 문서:\n", 1)[0][:600]
            recent.append(f"{message.role}: {content}")
        prompt = (
            "Rewrite the current Korean conversational question into one concise standalone search query. "
            "Resolve omitted subjects only from the conversation. Normalize technical names. "
            "Do not answer, explain, cite, or add facts not present in the conversation. "
            "If rewriting is unnecessary, return the original query. Output one plain-text line only.\n\n"
            + ("CONVERSATION:\n" + "\n".join(recent) + "\n\n" if recent else "")
            + "CURRENT QUESTION:\n" + original
        )
        try:
            response = await self.model.chat(selected_model, [
                SystemMessage(content="You produce safe retrieval queries, not answers."),
                HumanMessage(content=prompt),
            ], None, False)
            rewritten = normalize_search_query(response.text).strip('"\'` ')
            if not rewritten or len(rewritten) > 300 or "검색한 문서:" in rewritten:
                return original
            return rewritten
        except Exception:
            return original
