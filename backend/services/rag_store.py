"""Qdrant-only document and vector storage, using its REST API."""

import hashlib
import logging
import threading
import uuid

import httpx

logger = logging.getLogger(__name__)


class RagStore:
    def __init__(self, url, api_key=None, collection='mori', dimensions=768, transport=None):
        self.dimensions = dimensions
        self.docs = collection + '_documents'
        self.chunks = collection + '_chunks'
        self.http = httpx.Client(base_url=url.rstrip('/'), timeout=60,
            headers={'api-key': api_key} if api_key else {}, transport=transport)
        self._initialized = False
        self._lock = threading.Lock()

    def close(self):
        self.http.close()

    def request(self, method, path, **kwargs):
        response = self.http.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()['result']

    def initialize(self):
        with self._lock:
            if self._initialized:
                return
            for collection, size in [(self.docs, 1), (self.chunks, self.dimensions)]:
                response = self.http.get('/collections/' + collection)
                if response.status_code == 404:
                    self.request('PUT', '/collections/' + collection,
                        json={'vectors': {'size': size, 'distance': 'Cosine'}})
                else:
                    response.raise_for_status()
                    config = response.json()['result']['config']['params']['vectors']
                    if config.get('size') != size or config.get('distance') != 'Cosine':
                        raise ValueError('Qdrant 컬렉션의 벡터 설정이 다릅니다. 새 컬렉션 이름을 지정하세요.')
            for field in ('revision', 'keywords'):
                self.request('PUT', f'/collections/{self.chunks}/index?wait=true',
                    json={'field_name': field, 'field_schema': 'keyword'})
            self._initialized = True

    def manifests(self):
        self.initialize()
        points, offset = [], None
        while True:
            body = {'limit': 100, 'with_payload': ['name', 'chunks', 'model', 'revision', 'digest'],
                    'with_vector': False}
            if offset is not None:
                body['offset'] = offset
            result = self.request('POST', f'/collections/{self.docs}/points/scroll', json=body)
            points.extend(result['points'])
            offset = result.get('next_page_offset')
            if offset is None:
                return points

    def documents(self):
        return sorted([dict(id=point['id'], name=point['payload']['name'],
                            chunks=point['payload']['chunks'], model=point['payload']['model'])
                       for point in self.manifests()], key=lambda row: row['name'])

    def metadata(self, identifier):
        manifests = self.manifests()
        for point in manifests:
            if point['id'] == identifier:
                data = point['payload']
                return (data['digest'], data['model']), len(manifests)
        return None, len(manifests)

    def read(self, identifier):
        self.initialize()
        response = self.http.get(f'/collections/{self.docs}/points/{identifier}')
        if response.status_code == 404:
            raise ValueError('문서를 찾을 수 없습니다.')
        response.raise_for_status()
        data = response.json()['result']['payload']
        return {'id': identifier, 'name': data['name'], 'content': data['content']}

    def delete(self, identifier):
        if not any(point['id'] == identifier for point in self.manifests()):
            return False
        # Hide the document first so an interrupted cleanup cannot expose deleted data.
        self.request('POST', f'/collections/{self.docs}/points/delete?wait=true', json={'points': [identifier]})
        self.cleanup({'must': [{'key': 'id', 'match': {'value': identifier}}]})
        return True

    def cleanup(self, point_filter):
        try:
            self.request('POST', f'/collections/{self.chunks}/points/delete?wait=true',
                         json={'filter': point_filter})
        except httpx.HTTPError:
            # Only active revisions are searchable; failed cleanup leaves invisible old points.
            logger.warning('Qdrant inactive chunk cleanup failed')

    def save(self, identifier, name, content, digest, model, chunks):
        from backend.services.rag import terms
        self.initialize()
        revision = hashlib.sha256((identifier + digest + model).encode()).hexdigest()
        points = [{'id': str(uuid.uuid5(uuid.UUID(identifier), revision + ':' + str(index))),
                   'vector': chunk['vector'],
                   'payload': {'id': identifier, 'name': name, 'revision': revision,
                               'text': chunk['text'], 'start': chunk['start'], 'end': chunk['end'],
                               'page': chunk.get('page'),
                               'keywords': sorted(terms(chunk['text']))}}
                  for index, chunk in enumerate(chunks)]
        for offset in range(0, len(points), 32):
            self.request('PUT', f'/collections/{self.chunks}/points?wait=true',
                         json={'points': points[offset:offset + 32]})
        # Activate the complete revision with a single manifest upsert.
        self.request('PUT', f'/collections/{self.docs}/points?wait=true', json={'points': [{
            'id': identifier, 'vector': [1.0],
            'payload': {'name': name, 'content': content, 'digest': digest, 'model': model,
                        'revision': revision, 'chunks': len(chunks)},
        }]})
        self.cleanup({'must': [{'key': 'id', 'match': {'value': identifier}}],
                      'must_not': [{'key': 'revision', 'match': {'value': revision}}]})

    def candidates(self, model, vector, query_terms):
        from backend.services.rag import cosine
        revisions = [p['payload']['revision'] for p in self.manifests() if p['payload']['model'] == model]
        if not revisions:
            return []
        active = {'must': [{'key': 'revision', 'match': {'any': revisions}}]}
        body = {'query': vector, 'filter': active, 'limit': 20, 'with_payload': True, 'with_vector': True}
        points = self.request('POST', f'/collections/{self.chunks}/points/query', json=body)['points']
        if query_terms:
            lexical = {'must': [*active['must'], {'key': 'keywords', 'match': {'any': query_terms}}]}
            points += self.request('POST', f'/collections/{self.chunks}/points/scroll', json={
                'filter': lexical, 'limit': 20, 'with_payload': True, 'with_vector': True,
            })['points']
        unique = {point['id']: point for point in points}
        return [{**point['payload'], 'semantic': cosine(vector, point['vector'])} for point in unique.values()]
