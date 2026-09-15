# Notion 반영 초안 — AWS 배포 확인 후 적용

대상: https://app.notion.com/p/3d10800670e98163b9fac85fedcdc5de

## 현재 구현

- Qdrant만 사용하는 문서 RAG. 원문·파일명·활성 버전과 임베딩을 Qdrant에 저장한다.
- Ollama embeddinggemma로 임베딩 생성. 의미 검색과 키워드 후보를 결합한다.
- UI 문서 관리: 등록·보기·갱신·삭제. 문서 질문 모드는 서버가 먼저 검색한다.
- Markdown/TXT 200 KB, PDF 10 MB·100페이지·추출 텍스트 200 KB까지 지원한다.
- PDF는 페이지별 텍스트를 추출하고 답변에 페이지·줄 번호를 표시한다.
- 스캔 PDF 자동 OCR과 암호화 PDF는 지원하지 않는다. 텍스트 없는 페이지를 안내한다.
- `get_datetime`과 단순 상대 날짜·일자 후속 질문의 서버 처리, 계산 답변 추가 검토를 지원한다.

## API 추가

- `use_knowledge: true`: JSON/SSE 문서 질문 모드.
- `GET/POST /api/knowledge/documents`: 목록·텍스트 등록.
- `GET/DELETE /api/knowledge/documents/{id}`: 원문 조회·삭제.
- `POST /api/knowledge/pdf?name=guide.pdf`: PDF 바이너리 등록.

## 검증 기록

로컬 자동화 테스트 176개 통과. Qdrant·Ollama 연결은 모사한 테스트이며 실제 AWS 검증을 뜻하지 않는다.
AWS 이미지 태그, 적용 일시, health·문서 등록·질의·PDF 페이지 출처·OCR 확인 결과는 배포 완료 후 기록한다.

## 기존 페이지에서 고칠 내용

- 구현 범위의 파일 첨부 미지원 설명을 이미지 및 RAG 문서 등록 지원으로 갱신.
- 소스 탐색에 rag.py, rag_store.py, pdf_text.py, date_validation.py 추가.
- 기존 날짜 지침만으로 처리한다는 설명을 현재의 제한된 서버 처리와 구분.
- AWS 구성에 Qdrant 볼륨과 embeddinggemma 모델 준비 절차 추가.
- 과거 배포 검증 기록은 보존하고 최신 결과를 날짜와 함께 추가.
