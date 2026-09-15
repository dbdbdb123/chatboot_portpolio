# AWS RAG·PDF 배포 준비

현재 상태: 배포 전. SSH 접속 대상·키 경로가 필요하며 Docker 이미지 빌드는 아직 수행되지 않았다.

## 대상 서버 확인

기존 문서의 경로는 `/home/ubuntu/mori`, 앱 포트는 8080이다.
실제 서버에서 디스크·메모리, Compose 파일, 이미지 이름과 OCR 연결을 확인한 후 적용한다.
SSH 키와 인증 값은 배포 파일이나 Notion에 복사하지 않는다.

## 적용 순서

1. 로컬 이미지 `mori-app:rag-pdf-20260915`를 빌드하고 tar로 내보낸다.
2. 이미지 tar와 이 디렉터리의 `compose.rag.yaml`을 서버에 전송한다.
3. 기존 앱 이미지에 백업 태그를 지정하고 기존 Compose/override를 백업한다.
4. 새 이미지를 load하고 서버의 앱 이미지 이름에 맞춰 태그를 지정한다.
5. 아래 명령으로 기존 Compose와 OCR 설정에 RAG 구성을 추가한다.

```bash
cd /home/ubuntu/mori
docker compose -f compose.yaml -f compose.override.yaml -f compose.rag.yaml config --quiet
docker compose -f compose.yaml -f compose.override.yaml -f compose.rag.yaml pull qdrant
docker compose -f compose.yaml -f compose.override.yaml -f compose.rag.yaml up -d qdrant
docker compose exec -T ollama ollama pull embeddinggemma
docker compose -f compose.yaml -f compose.override.yaml -f compose.rag.yaml up -d --no-deps app
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8080/api/knowledge/documents
curl -fsS http://127.0.0.1:8080/api/mcp/tools
```

`compose.override.yaml`의 존재와 앱 이미지 태그를 실제 서버에서 먼저 확인해야 한다.
Qdrant는 Docker 내부 네트워크로 연결하며 이 추가 설정은 DB 외부 포트를 열지 않는다.
모델 다운로드가 실패하면 앱을 교체하지 않는다.

## 실사용 확인

- 일반 대화와 `get_datetime` 조회.
- 검증용 TXT 등록 → 관련 질문 → 출처 확인 → 삭제.
- 텍스트 PDF 등록 → 페이지 출처 확인 → 삭제.
- OCR MCP 조회와 기존 네트워크 유지 확인.
- `docker stats --no-stream`, 앱·Qdrant 로그 확인.

실패 시 백업 이미지 태그를 기존 앱 이미지 이름으로 복구하고 이전 Compose 구성으로 앱을 재생성한다.
Qdrant·Ollama 볼륨은 삭제하지 않는다. 실제 검증 결과를 확보한 뒤 Notion을 갱신한다.
