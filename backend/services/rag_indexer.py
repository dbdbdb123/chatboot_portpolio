"""RAG document validation, chunking, embedding, and revision indexing."""

import asyncio
import hashlib
import re
import uuid

from backend.services.pdf_text import extract_pdf

INDEX_VERSION = "structure-v2"


def split_document(text, max_chars=700, overlap_chars=80):
    sections: list[str] = []
    blocks: list[dict] = []
    pending: list[tuple[int, str]] = []
    pending_section = ""

    def flush():
        nonlocal pending
        if pending and any(line.strip() for _, line in pending):
            blocks.append({"lines": pending, "section": pending_section})
        pending = []

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            flush()
            level, title = len(heading.group(1)), heading.group(2)
            sections[level - 1:] = [title]
            pending_section = " > ".join(sections)
            pending = [(number, line)]
            continue
        if not line:
            flush()
            continue
        section = " > ".join(sections)
        if pending and section != pending_section:
            flush()
        pending_section = section
        pending.append((number, line))
    flush()

    chunks: list[dict] = []
    for block in blocks:
        lines = block["lines"]
        text_block = "\n".join(line for _, line in lines)
        if len(text_block) <= max_chars:
            chunks.append({"text": text_block, "start": lines[0][0],
                           "end": lines[-1][0], "section": block["section"]})
            continue
        cursor, step = 0, max_chars - overlap_chars
        while cursor < len(text_block):
            piece = text_block[cursor:cursor + max_chars].strip()
            if piece:
                chunks.append({"text": piece, "start": lines[0][0],
                               "end": lines[-1][0], "section": block["section"]})
            cursor += step
    return chunks


class RagIndexer:
    def __init__(self, service) -> None:
        self.service = service

    async def register_pdf(self, name, data):
        if not re.fullmatch(r"[^/\\\x00-\x1f]{1,150}\.pdf", name, re.IGNORECASE):
            raise ValueError("경로 없는 .pdf 파일명만 허용됩니다.")
        pages = await asyncio.to_thread(extract_pdf, data)
        content = "\n\n".join(f"[페이지 {i}]\n{text}" for i, text in enumerate(pages, 1))
        result = await self.register(name, content, pages=pages)
        result["pages"] = len(pages)
        result["empty_pages"] = [i for i, text in enumerate(pages, 1) if not text]
        return result

    async def register(self, name, content, *, pages=None):
        extension = "pdf" if pages is not None else "(?:md|txt)"
        if not re.fullmatch(r"[^/\\\x00-\x1f]{1,150}\." + extension, name, re.IGNORECASE):
            raise ValueError("경로 없는 .md 또는 .txt 파일명만 허용됩니다.")
        if not content.strip() or (pages is None and len(content.encode("utf-8")) > 200_000):
            raise ValueError("비어 있지 않은 UTF-8 문서만 등록할 수 있습니다. 최대 200 KB입니다.")
        service = self.service
        digest = hashlib.sha256((INDEX_VERSION + "\0" + content).encode()).hexdigest()
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, "mori:" + name))
        async with service.index_lock:
            existing, count = await asyncio.to_thread(service.store.metadata, identifier)
            if existing == (digest, service.embedding_model, INDEX_VERSION):
                return {"id": identifier, "name": name, "unchanged": True}
            if existing is None and count >= 100:
                raise ValueError("최대 100개 문서까지 등록할 수 있습니다.")
            chunks = split_document(content) if pages is None else [
                {**chunk, "page": number}
                for number, text in enumerate(pages, 1) for chunk in split_document(text)
            ]
            for offset in range(0, len(chunks), 16):
                batch = chunks[offset:offset + 16]
                vectors = await service.embed([
                    f"title: {name} | section: {chunk.get('section') or '-'} | text: {chunk['text']}"
                    for chunk in batch
                ])
                for chunk, vector in zip(batch, vectors):
                    chunk["vector"] = vector
            await asyncio.to_thread(
                service.store.save, identifier, name, content, digest,
                service.embedding_model, chunks, INDEX_VERSION,
            )
        return {"id": identifier, "name": name, "chunks": len(chunks), "unchanged": False}

    async def reindex_existing(self):
        results = []
        for document in await asyncio.to_thread(self.service.store.documents):
            if document.get("index_version") == INDEX_VERSION:
                continue
            stored = await asyncio.to_thread(self.service.store.read, document["id"])
            content, pages = stored["content"], None
            if document["name"].lower().endswith(".pdf"):
                markers = list(re.finditer(r"^\[페이지 (\d+)\]\n", content, re.MULTILINE))
                if markers:
                    pages = [
                        content[marker.end():(markers[index + 1].start()
                                if index + 1 < len(markers) else len(content))].strip()
                        for index, marker in enumerate(markers)
                    ]
            results.append(await self.register(document["name"], content, pages=pages))
        return results
