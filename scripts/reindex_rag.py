"""배포 후 기존 Qdrant 문서를 최신 청킹 규칙으로 한 번 재색인한다."""

import asyncio
import os

from backend.dataclass.settings import Settings
from backend.ollama import OllamaClient
from backend.services.rag import RagService, RagStore


async def main() -> None:
    settings = Settings.load()
    model = OllamaClient(settings.ollama_base_url, settings.request_timeout_seconds,
                         options=settings.generation.model_copy(update={"num_ctx": 8192, "num_predict": 768}))
    service = RagService(
        RagStore(os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"),
                 os.environ.get("QDRANT_API_KEY"), os.environ.get("RAG_COLLECTION", "mori")),
        model, settings.ollama_model, settings.ollama_base_url,
        os.environ.get("RAG_EMBEDDING_MODEL", "embeddinggemma"),
    )
    try:
        results = await service.reindex_existing()
        print({"reindexed": len(results), "documents": [item["name"] for item in results]})
    finally:
        await service.close()
        await model.close()


if __name__ == "__main__":
    asyncio.run(main())
