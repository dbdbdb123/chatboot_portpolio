import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk

from backend.api.deps import get_chat_service
from backend.api.routes import router
from backend.schemas import ChatMessage
from backend.services.rag import RagService, RagStore, display_document_name, split_document


class Model:
    calls = 0

    async def stream_chat(self, model, messages, tools, think):
        self.calls += 1
        assert tools is None
        prompt = messages[-1].text
        assert 'QUESTION:' in prompt and 'SOURCE [1]' in prompt
        assert 'untrusted' in messages[0].text
        yield AIMessageChunk(content='프로젝트 문의는 담당자에게 전달합니다. [1]')

    async def chat(self, model, messages, tools, think):
        assert tools is None and think is False
        return AIMessage(content='유지호 이력서 주인 이름')


class FakeObservation:
    def __init__(self, record):
        self.record = record

    def update(self, **values):
        self.record.update(values)


class FakeLangfuse:
    def __init__(self):
        self.observations = []

    @contextmanager
    def start_as_current_observation(self, **values):
        record = dict(values)
        self.observations.append(record)
        yield FakeObservation(record)



class FakeQdrant:
    """REST contract fake; production storage remains exclusively Qdrant."""
    def __init__(self):
        self.collections = {}
        self.config = {}
        self.fail_manifest = False

    def matches(self, payload, filters):
        def condition(item):
            value = payload.get(item['key'])
            match = item['match']
            if 'any' in match:
                return any(v in match['any'] for v in value) if isinstance(value, list) else value in match['any']
            return value == match['value']
        return (all(condition(item) for item in filters.get('must', []))
                and not any(condition(item) for item in filters.get('must_not', [])))

    def __call__(self, request):
        from backend.services.rag import cosine
        parts = request.url.path.strip('/').split('/')
        assert parts[0] == 'collections'
        name = parts[1]
        body = json.loads(request.content) if request.content else {}
        result = True
        if len(parts) == 2:
            if request.method == 'PUT':
                self.collections[name] = {}
                self.config[name] = body
            elif name not in self.collections:
                return httpx.Response(404, json={'status': 'not found'})
            else:
                result = {'config': {'params': self.config[name]}}
        elif parts[2] == 'index':
            assert body['field_schema'] == 'keyword'
        elif parts[2] == 'points':
            points = self.collections[name]
            action = parts[3] if len(parts) > 3 else ''
            if request.method == 'PUT':
                if name.endswith('_documents') and self.fail_manifest:
                    return httpx.Response(503, json={'status': 'failed'})
                for point in body['points']:
                    assert len(point['vector']) == self.config[name]['vectors']['size']
                    points[point['id']] = point
            elif action in ('scroll', 'query'):
                selected = [p for p in points.values() if self.matches(p['payload'], body.get('filter', {}))]
                if action == 'query':
                    selected.sort(key=lambda p: cosine(body['query'], p['vector']), reverse=True)
                result = {'points': selected[:body['limit']], 'next_page_offset': None}
            elif action == 'delete':
                for identifier in list(points):
                    if identifier in body.get('points', []) or ('filter' in body and self.matches(points[identifier]['payload'], body['filter'])):
                        del points[identifier]
            else:
                if action not in points:
                    return httpx.Response(404, json={'status': 'not found'})
                result = points[action]
        return httpx.Response(200, json={'result': result})


@pytest.fixture
async def rag(tmp_path):
    service = RagService(RagStore('http://qdrant', dimensions=2, transport=httpx.MockTransport(FakeQdrant())), Model(), 'test', 'http://test')
    await service.http.aclose()

    def handle(request):
        payload = json.loads(request.content)
        assert request.url.path == '/api/embed'
        assert payload['truncate'] is False
        vectors = [[1.0, 0.0] if any(word in text for word in ['문의', '담당자', 'contact']) else [0.0, 1.0]
                   for text in payload['input']]
        return httpx.Response(200, json={'embeddings': vectors})

    service.http = httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(handle))
    yield service
    await service.close()


@pytest.mark.asyncio
async def test_register_update_deduplicate_persist_delete(rag):
    initial = await rag.register('guide.md', '# 문의\n담당자에게 연락하세요.')
    same = await rag.register('guide.md', '# 문의\n담당자에게 연락하세요.')
    assert same['unchanged']
    assert same['id'] == initial['id']
    updated = await rag.register('guide.md', '# 문의\n새 담당자에게 문의하세요.')
    assert not updated['unchanged']
    reopened = RagStore('http://qdrant', dimensions=2, transport=rag.store.http._transport)
    assert reopened.read(initial['id'])['content'].endswith('새 담당자에게 문의하세요.')
    assert len(reopened.documents()) == 1
    assert reopened.delete(initial['id'])
    reopened.close()
    assert await rag.search('담당자 문의') == []


@pytest.mark.asyncio
async def test_reindex_existing_document_from_previous_chunk_version(rag):
    registered = await rag.register('legacy.md', '# 제목\n기존 내용')
    fake = rag.store.http._transport.handler
    fake.collections['mori_documents'][registered['id']]['payload'].pop('index_version')
    results = await rag.reindex_existing()
    assert [item['name'] for item in results] == ['legacy.md']
    assert rag.store.documents()[0]['index_version'] == 'structure-v2'


@pytest.mark.asyncio
async def test_embedding_failure_preserves_previous_document(rag):
    old = await rag.register('guide.txt', '문의 담당자')
    async def fail(texts):
        raise ValueError('embedding failed')
    rag.embed = fail
    with pytest.raises(ValueError):
        await rag.register('guide.txt', 'new content')
    assert rag.store.read(old['id'])['content'] == '문의 담당자'


@pytest.mark.asyncio
async def test_incomplete_qdrant_revision_is_not_searchable(rag):
    old = await rag.register('guide.txt', '문의 담당자 기존 내용')
    fake = rag.store.http._transport.handler
    fake.fail_manifest = True
    with pytest.raises(httpx.HTTPError):
        await rag.register('guide.txt', '문의 담당자 미완성 변경')
    assert rag.store.read(old['id'])['content'] == '문의 담당자 기존 내용'
    hits = await rag.search('문의')
    assert hits and all('미완성' not in hit['text'] for hit in hits)
    fake.fail_manifest = False
    await rag.register('guide.txt', '문의 담당자 최종 변경')
    hits = await rag.search('문의')
    assert hits and all('최종 변경' in hit['text'] for hit in hits)
    assert len(fake.collections['mori_chunks']) == 1


@pytest.mark.asyncio
async def test_wrong_embedding_dimension_is_rejected(rag):
    await rag.http.aclose()
    rag.http = httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'embeddings': [[1, 2, 3]]})))
    with pytest.raises(ValueError, match='차원'):
        await rag.register('guide.txt', '문의 담당자')
    assert rag.store.documents() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(('name', 'content'), [
    ('../guide.md', 'text'), ('folder\\guide.md', 'text'), ('guide.pdf', 'text'),
    ('guide.txt', ' '), ('guide.txt', '가' * 70000),
], ids=['parent-path', 'nested-path', 'unsupported', 'empty', 'oversized'])
async def test_registration_rejects_invalid_documents(rag, name, content):
    with pytest.raises(ValueError):
        await rag.register(name, content)
    assert rag.store.documents() == []


@pytest.mark.asyncio
async def test_semantic_retrieval_and_source_answer(rag):
    await rag.register('guide.md', '# 프로젝트 안내\n문의는 담당자에게 전달합니다.')
    # No shared words: semantic vector should still retrieve the passage.
    hits = await rag.search('contact')
    assert hits[0]['name'] == 'guide.md'
    result = await rag.run([ChatMessage(role='user', content='문의 방법')])
    assert 'guide.md (L1–L2)' in result.message.content
    assert '[1]' in result.message.content
    assert rag.model.calls == 1


@pytest.mark.asyncio
async def test_rag_records_chain_and_retriever_observations(rag):
    await rag.register('guide.md', '# 프로젝트 안내\n문의는 담당자에게 전달합니다.')
    langfuse = FakeLangfuse()
    rag.langfuse = langfuse

    await rag.run([ChatMessage(role='user', content='문의 방법')])

    assert [(item['as_type'], item['name']) for item in langfuse.observations] == [
        ('chain', 'mori-rag'),
        ('retriever', 'mori-hybrid-retrieval'),
    ]
    assert langfuse.observations[0]['output']['source_count'] == 1
    assert langfuse.observations[1]['output'][0]['document'] == 'guide.md'


def test_display_document_name_hides_upload_identifier():
    name = '5a98cbfc-5036-4933-a41d-c85c0eb916c8_유지호__Python_Backend__OCRAI_Portfolio.pdf'
    assert display_document_name(name) == '유지호 · Python Backend · OCRAI Portfolio.pdf'


@pytest.mark.asyncio
async def test_no_relevant_results_never_calls_model(rag):
    await rag.register('guide.md', '문의 담당자')
    result = await rag.run([ChatMessage(role='user', content='은하수 별자리')])
    assert '관련 근거를 찾지 못했습니다' in result.message.content
    assert rag.model.calls == 0


def test_chunks_are_bounded_and_keep_line_ranges():
    text = 'header\n' + '가' * 1400 + '\nlast line'
    chunks = split_document(text)
    assert len(chunks) >= 3
    assert all(len(chunk['text']) <= 700 for chunk in chunks)
    assert chunks[0]['start'] == 1
    assert chunks[-1]['end'] == 3
    assert all(1 <= chunk['start'] <= chunk['end'] <= 3 for chunk in chunks)


def test_structure_chunks_preserve_heading_path_and_paragraphs():
    chunks = split_document('# 경력\n\n## Mori\nLangChain과 Redis를 적용했습니다.\n\n## OCR\nOpenCV를 사용했습니다.')
    assert [chunk['section'] for chunk in chunks] == [
        '경력', '경력 > Mori', '경력 > OCR',
    ]
    assert chunks[1]['text'].startswith('## Mori')


@pytest.mark.asyncio
async def test_colloquial_query_is_rewritten_but_original_remains_fallback(rag):
    await rag.register('resume.md', '# 인적 사항\n이름은 유지호입니다.')
    messages = [ChatMessage(role='user', content='이 이력서의 주인은?')]
    rewritten = await rag.rewrite_query(messages, 'test')
    assert rewritten == '유지호 이력서 주인 이름'
    hits = await rag.context(messages[-1].content, [messages[-1].content, rewritten])
    assert hits
    assert len(hits) <= 3


@pytest.mark.asyncio
async def test_resume_summary_uses_all_active_chunks_in_document_order(rag):
    text = '\n'.join(f'경력 항목 {number}: OCR 프로젝트와 담당 업무 상세 설명' for number in range(100))
    await rag.register('resume.txt', text)
    hits = await rag.context('이력서 전체 경력을 요약해줘')
    assert len(hits) > 3
    assert [hit['ordinal'] for hit in hits] == sorted(hit['ordinal'] for hit in hits)
    assert sum(len(hit['text']) for hit in hits) <= 9000


def test_pdf_layout_text_is_normalized():
    from backend.services.pdf_text import normalize_page_text
    raw = 'OCR 경력을 보유하고 있습니다. 문서 전처리와 FastAPI 기반\nAPI 개발을 담당했습니다.\n\n\nL\ninux 서버 배포'
    assert normalize_page_text(raw) == (
        'OCR 경력을 보유하고 있습니다. 문서 전처리와 FastAPI 기반 API 개발을 담당했습니다.\n\nLinux 서버 배포'
    )


@pytest.mark.asyncio
async def test_document_api_and_rag_chat_routes(rag):
    app = FastAPI()
    app.include_router(router)
    app.state.rag_service = rag
    app.dependency_overrides[get_chat_service] = lambda: None
    with TestClient(app) as client:
        registered = client.post('/api/knowledge/documents', json={'name': 'guide.txt', 'content': '문의 담당자'})
        assert registered.status_code == 200
        identifier = registered.json()['id']
        assert len(client.get('/api/knowledge/documents').json()['documents']) == 1
        assert client.get('/api/knowledge/documents/' + identifier).json()['content'] == '문의 담당자'
        payload = {'messages': [{'role': 'user', 'content': '문의'}], 'use_knowledge': True, 'use_tools': False}
        answer = client.post('/api/chat', json=payload)
        assert answer.status_code == 200
        assert 'guide.txt' in answer.json()['message']['content']
        streamed = client.post('/api/chat/stream', json=payload)
        assert 'event: done' in streamed.text
        assert 'guide.txt' in streamed.text
        assert client.delete('/api/knowledge/documents/' + identifier).status_code == 200
        assert client.get('/api/knowledge/documents/' + identifier).status_code == 404



def pdf_bytes(pages, encrypted=False):
    """In-memory PDF fixture with extractable text and no external assets."""
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=600, height=800)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
                DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 30 750 Td ({text}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('secret')
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_pdf_pages_sources_empty_pages_and_deduplication(rag):
    data = pdf_bytes(['contact first page', '', 'contact third page'])
    registered = await rag.register_pdf('guide.pdf', data)
    assert registered['pages'] == 3
    assert registered['empty_pages'] == [2]
    assert (await rag.register_pdf('guide.pdf', data))['unchanged']
    stored = rag.store.read(registered['id'])['content']
    assert '[페이지 3]' in stored and 'contact third page' in stored
    hits = await rag.search('contact')
    assert {hit['page'] for hit in hits} == {1, 3}
    result = await rag.run([ChatMessage(role='user', content='contact')])
    assert 'guide.pdf (p.1,' in result.message.content
    assert 'guide.pdf (p.3,' in result.message.content
    assert 'p.2,' not in result.message.content


@pytest.mark.asyncio
@pytest.mark.parametrize(('kind', 'expected'), [
    ('blank', 'OCR'), ('encrypted', '암호'), ('broken', 'PDF'), ('pages', '100페이지'),
])
async def test_pdf_rejects_unreadable_input_without_writes(rag, kind, expected):
    data = {
        'blank': lambda: pdf_bytes(['']),
        'encrypted': lambda: pdf_bytes(['contact'], encrypted=True),
        'broken': lambda: b'%PDF-1.7 not a valid PDF',
        'pages': lambda: pdf_bytes([''] * 101),
    }[kind]()
    with pytest.raises(ValueError, match=expected):
        await rag.register_pdf('guide.pdf', data)
    assert rag.store.documents() == []


@pytest.mark.asyncio
async def test_pdf_upload_api_and_size_limit(rag, monkeypatch):
    from backend.api import knowledge_routes
    app = FastAPI()
    app.include_router(router)
    app.state.rag_service = rag
    with TestClient(app) as client:
        response = client.post('/api/knowledge/pdf?name=guide.pdf',
            content=pdf_bytes(['contact']), headers={'Content-Type': 'application/pdf'})
        assert response.status_code == 200
        assert response.json()['pages'] == 1
        assert client.post('/api/knowledge/pdf?name=bad.pdf', content=b'not PDF').status_code == 400
        monkeypatch.setattr(knowledge_routes, 'MAX_PDF_BYTES', 4)
        assert client.post('/api/knowledge/pdf?name=big.pdf', content=b'12345').status_code == 413


def test_pdf_extracted_text_size_is_bounded(monkeypatch):
    from backend.services import pdf_text
    monkeypatch.setattr(pdf_text, 'MAX_EXTRACTED_BYTES', 4)
    with pytest.raises(ValueError, match='200 KB'):
        pdf_text.extract_pdf(pdf_bytes(['too much text']))
