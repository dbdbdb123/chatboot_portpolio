# Mori 개발 문서

> 현재 소스는 PNG/JPEG/WebP 첨부를 지원합니다. 이미지는 Qwen3.5에 직접 전달하고 OCR 요청에 대한 모델의 도구 선택 시에만 MCP를 실행합니다. 배포 검증 기록은 별도 시점의 기록이며, 최신 요청 계약과 제한은 README의 “이미지 첨부 요청” 절을 참조하세요.

기준일: 2026-09-04 · 대상: Mori 개발·유지보수 담당자
현재 모델: **Qwen3.5 2B Q4_K_M** · Ollama 태그: `qwen3.5:2b-q4_K_M`
[프로젝트 소개 및 아키텍처](https://app.notion.com/p/3d10800670e981269a75d725ddaa3702) · [저장소](https://github.com/dbdbdb123/chatboot_portpolio)

## 1. 목적과 구현 범위
Mori는 Qwen3.5의 자연어 응답과 OCR 관련 MCP 도구 호출을 조율하는 FastAPI 애플리케이션이다. 브라우저가 대화 기록을 전송하면 모델이 직접 답하거나 도구를 선택한다. 백엔드는 허용된 도구의 인자를 검증하고 실행 결과를 모델에 전달한다.
구현 범위는 채팅 UI, Ollama 연결, SSE, Thinking 선택, stdio/Streamable HTTP MCP 연결, Docker 및 AWS 배포다. 이미지 첨부는 지원하며, 모델 파인튜닝, 자체 OCR 엔진, PDF 첨부, 사용자 인증 및 영구 대화 저장은 현재 구현 범위에 포함되지 않는다.

## 2. 구성과 소스 탐색
- `main.py`: FastAPI 앱 진입점.
- `backend/app.py`: lifespan에서 Settings·OllamaClient·ConfiguredMCPGateway·ChatService 생성 및 종료. API 등록 후 정적 UI 마운트.
- `backend/api/routes.py`: health, 도구 목록, JSON 채팅, SSE 채팅 라우터.
- `backend/models.py`: 요청·응답 Pydantic 모델.
- `backend/services/chat.py`: 모델 추론과 도구 실행 순서 조율.
- `backend/services/context.py`: 첨부 이미지와 시스템 안내를 포함한 모델 입력 구성.
- `backend/services/tools.py`: 공통 호출 검증, 정책 적용 후 MCP 실행과 결과 변환.
- `backend/services/tool_policy.py`: 도구 노출·실행 인자 정책 계약과 OCR 첨부 처리 규칙.
- `backend/services/interfaces.py`: 추론 구현을 교체할 수 있는 최소 스트리밍 계약.
- `backend/api/streaming.py`: SSE 직렬화, keep-alive, 오류 전달과 취소 정리.
- `backend/ollama.py`: HTTPX 기반 Ollama REST 및 NDJSON 스트림 처리.
- `backend/mcp/stdio_gateway.py`: ConfiguredMCPGateway. 파일명과 달리 stdio와 HTTP를 모두 지원하며 기존 StdioMCPGateway 이름을 별칭으로 유지.
- `backend/mcp/interface.py`: 도구 조회·실행·종료 인터페이스.
- `backend/mcp/validation.py`: 도구 인자 경량 검증.
- `backend/dataclass/settings.py`: JSON·환경변수 설정과 MCPServerConfig.
- `backend/dataclass/mcp.py`: MCPTool·MCPToolResult 및 모델용 도구 형식 변환.
- `chatbot-ui/`: HTML·CSS·JavaScript. 빌드 도구 없이 FastAPI가 제공.
- `compose.yaml`: 로컬 앱·Ollama·모델 초기화 구성.
- `compose.mcp.yaml`: 기존 OCR Docker 네트워크와 두 MCP 연결.
- `tests/`: 채팅·SSE·Thinking·설정·MCP·검증 테스트.
- `docs/mori-system-architecture.svg`: 시스템 아키텍처 이미지 원본.

## 3. 개발 환경 실행
Python 3.12 이상과 Ollama를 준비한다. 다음 명령은 저장소 루트의 PowerShell에서 실행한다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
ollama pull qwen3.5:2b-q4_K_M
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Ollama 서버가 먼저 실행되어 있어야 한다. 네이티브 Ollama 기본 주소는 `http://127.0.0.1:11434`다. 로컬 Docker Ollama를 사용할 경우 호스트 포트가 11435이므로 OLLAMA_BASE_URL을 해당 주소로 설정한다.

Docker만 사용하는 경우:
```powershell
docker compose up --build -d
docker compose ps
```

로컬 UI는 `http://127.0.0.1:8000`이다. 기본 로컬 설정의 MCP 목록은 비어 있으므로 일반 채팅부터 실행할 수 있다. AWS용 MCP DNS 이름은 로컬 Windows에서 해석되지 않는다.

## 4. 설정 계약
우선순위는 **환경변수 → .setting/settings.json → 코드 기본값**이다. 설정은 앱 시작 때 읽으므로 변경 후 프로세스 또는 컨테이너를 재생성한다. 앱이 임의의 .env 파일을 직접 로드하지는 않는다.

- `OLLAMA_BASE_URL` / `ollama_base_url`: 기본 http://127.0.0.1:11434. Docker 앱에서는 http://ollama:11434.
- `OLLAMA_MODEL` / `ollama_model`: qwen3.5:2b-q4_K_M.
- `REQUEST_TIMEOUT_SECONDS` / `request_timeout_seconds`: 기본 60초. HTTPX 요청의 연결·읽기 등 타임아웃이며 전체 채팅의 절대 실행 시간 제한은 아니다.
- `MAX_TOOL_ROUNDS` / `max_tool_rounds`: 기본 3. 이후 최종 응답용 추론 기회를 한 번 더 갖는다.
- `MCP_SERVERS_JSON` / `mcp_servers`: MCP 서버 배열. 환경변수는 전체 목록을 교체한다.
- MCP `timeout_seconds`: 기본 15초, AWS 연결은 서버별 30초. 초기화·작업·정리를 포함한 세션을 asyncio.timeout으로 감싼다.
- Ollama 컨테이너 설정: context 2048, parallel 1, max loaded models 1.

설정 예:
```json
{
  "name": "ocr",
  "transport": "streamable_http",
  "url": "http://ocr-pipeline-mcp-1:8001/mcp",
  "headers": {"Host": "localhost"},
  "allowed_tools": ["check_ocr_health", "get_ocr_capabilities", "inspect_document"],
  "timeout_seconds": 30
}
```

stdio는 transport를 생략하거나 stdio로 지정하고 command, args, env를 설정한다. HTTP는 http(s) URL이 필요하다. allowed_tools가 비어 있으면 도구가 모델에 노출되지 않는다. 서버 이름은 중복되지 않게 지정한다.

## 5. HTTP API
### GET /api/health
Ollama의 모델 목록 API에 접근 가능한지 확인하고 설정된 모델명과 MCP 서버 개수를 반환한다.

```json
{"status":"ok","ollama":true,"mcp_servers":2,"model":"qwen3.5:2b-q4_K_M"}
```

mcp_servers는 설정 개수다. MCP 연결 성공이나 모델 파일 존재·로드 성공을 의미하지 않는다. Ollama 접근 실패 시 본문 status는 degraded지만 HTTP 상태는 기본 200이다.

### GET /api/mcp/tools
각 MCP에서 발견한 도구 중 허용 목록을 통과한 항목을 반환한다. 항목은 server, name, qualified_name, description, input_schema를 포함한다. 예: ocr__check_ocr_health.
이 API는 실제 MCP 연결 검증에 사용한다. 현재 OSError·TimeoutError만 503으로 변환하며 SDK의 ExceptionGroup 등은 별도 대응이 필요하다.

### POST /api/chat 및 POST /api/chat/stream
두 API는 같은 요청 구조를 사용한다.

```json
{
  "messages": [{"role":"user","content":"오늘 OCR 처리 건수 조회해 줘"}],
  "use_tools": true,
  "think": false,
  "model": null
}
```

- messages: 1~100개. 각 메시지의 role은 system/user/assistant/tool, content는 문자열.
- use_tools: 기본 true. false이면 MCP 목록 조회와 모델용 도구 제공을 생략한다.
- think: 기본 false. Ollama의 think 필드로 전달하며 모든 추론 라운드에서 유지한다.
- model: 생략하거나 null이면 서버 기본 모델을 사용한다. 현재 API는 지정 가능한 모델의 별도 허용 목록을 두지 않는다.
- UI 입력 최대 길이는 2,000자다. 백엔드 content 필드에는 같은 길이 제한이 없다.

JSON API 최종 응답 예:
```json
{
  "message": {"role":"assistant","content":"OCR 서버가 준비되어 있습니다."},
  "model": "qwen3.5:2b-q4_K_M",
  "tools": [{"server":"ocr","name":"check_ocr_health","arguments":{},"is_error":false}]
}
```

JSON API는 HTTPX 오류를 503, 도구 인자·값 오류를 400, 처리되는 타임아웃을 504, RuntimeError를 422로 변환한다. 요청 스키마 오류는 FastAPI의 422다. 모든 MCP SDK 예외가 이 분류로 변환되는 것은 아니다.

## 6. SSE 프로토콜
브라우저는 POST 본문이 필요하므로 EventSource 대신 fetch의 ReadableStream을 사용한다. Content-Type은 text/event-stream이다.

- model: 선택 모델.
- round: 추론 라운드 index, 0부터 시작.
- delta: 답변 조각 text.
- tool: 도구 실행 후 server/name/arguments/is_error.
- done: JSON API와 같은 최종 응답.
- error: 사용자용 detail. 상세 예외는 서버 로그에 기록.

```text
event: delta
data: {"text":"OCR 서버가"}

event: tool
data: {"server":"ocr","name":"check_ocr_health","arguments":{},"is_error":false}

```

위는 각 프레임 형식의 예이며 고정된 발생 순서가 아니다. 모델이 도구 호출 전에 문장을 출력할 수도 있다. 프레임은 빈 줄로 구분하고 15초 동안 새 이벤트가 없으면 keep-alive 주석을 보낸다. Cache-Control: no-cache와 X-Accel-Buffering: no 헤더를 설정한다.
스트림 시작 후 오류는 HTTP 상태 변경 대신 error 이벤트로 전달한다. 프런트엔드는 UTF-8와 프레임 분할을 버퍼링하고 done 이전 연결 종료를 실패로 처리한다. 연결 종료 시 pending task와 Ollama 스트림을 정리한다.

## 7. 모델·MCP 실행 흐름
1. 모델명 결정 후 use_tools가 true면 허용 도구를 조회한다.
2. 도구가 있으면 OCR 운영 안내와 현재 UTC 시각을 system 메시지로 추가한다. 상대 날짜는 한국 시간 기준, 최대 31일 조회를 지시한다.
3. 대화 기록·도구 스키마·think를 Ollama에 전송한다.
4. NDJSON의 content·thinking·tool_calls를 누적하고 content만 SSE로 보낸다.
5. 도구 호출이 없으면 done을 반환한다.
6. 호출이 있으면 server__tool 형태의 이름을 등록 목록에서 확인한다. 문자열 인자는 JSON으로 해석하고 object인지 확인한다.
7. MCP 게이트웨이가 허용 목록과 캐시된 입력 스키마를 확인한 후 도구를 호출한다.
8. 실행 요약을 tool 이벤트로 보내고 structured_content 또는 content를 role=tool 메시지로 추가한다.
9. 도구 결과와 함께 모델을 다시 호출한다.

기본 설정에서는 최대 3개의 도구 실행 라운드와 1개의 추가 추론 라운드가 가능하다. 마지막 추론에서도 도구를 요청하면 실행하지 않고 오류를 반환한다. 한 라운드에서 여러 도구 호출이 가능하므로 “최대 도구 호출 수 3개”라는 의미는 아니다. 도구는 현재 순차 실행한다.

게이트웨이는 조회·호출마다 짧은 MCP 세션을 생성·초기화·정리한다. 도구 스키마 캐시는 유지하지만 연결 풀 형태의 영구 MCP 세션은 유지하지 않는다. SDK 2.x HTTP 전송은 httpx2 클라이언트를 사용하고 Ollama 요청은 httpx를 사용한다.

## 8. 두 MCP 서버의 데이터 계약
### OCR MCP
- check_ocr_health: 인자 없음. status, models_ready, detectors, recognizers 반환.
- get_ocr_capabilities: 인자 없음. MIME 형식, 크기·픽셀·PDF 페이지 제한, 엔진 목록 반환.
- inspect_document: data_base64, mime_type 필수. detector와 recognizer 선택. OCR 결과 request_id/status/text 반환.

현재 채팅은 PNG/JPEG/WebP 이미지 1장을 첨부할 수 있다. 이미지가 있을 때 모델에는 빈 인자의 inspect_document 도구를 제공한다. 모델이 OCR을 선택하면 백엔드가 실제 Base64와 MIME을 넣어 실행하며, UI 실행 요약에는 파일명과 MIME만 표시한다.

### Operations MCP
- get_ocr_summary: start_time, end_time ISO 8601 문자열. 처리 건수·성공률과 근거 반환.
- get_ocr_failures: 동일 기간 및 limit(기본 20). 실패 이벤트 메타데이터 반환.
- get_ocr_event: 정수 event_id. 해당 이벤트의 안전한 메타데이터 반환.

오늘 조회는 한국 시간 00:00부터 현재 시각까지다. 날짜 지시는 프롬프트에 있지만 날짜 해석과 인자 생성은 모델이 수행하므로 실제 요청 범위를 점검한다. 운영 서버가 조회 범위 등 최종 제약을 검증한다. 현재 운영 데이터는 오류 원인·지연 시간·엔진별 필터를 제공하지 않는다.

## 9. 프런트엔드 상태
- chatMessages는 현재 탭 메모리의 대화 기록이며 매 요청에 전송한다. 서버는 대화를 영구 저장하지 않는다.
- Thinking 선택은 localStorage의 mori.think에 저장한다. 기본 OFF이며 저장소 차단 시에도 현재 탭에서 사용한다.
- 전송 중 send 버튼과 Thinking 버튼을 비활성화한다.
- 도구 선택은 요청 시점의 aria-pressed 값을 읽는다.
- 실패한 user 메시지는 다음 요청 기록에서 제거하며 부분 답변은 화면에 응답 중단으로 표시한다.
- 모델명은 health와 응답 데이터에서 갱신한다. 생각 원문은 사용자에게 보내지 않는다.
- 메시지는 textContent와 텍스트 노드로 렌더링한다.

## 10. AWS 배포와 복구
현재 배포 환경은 Ubuntu, EC2 m7i-flex.large(2 vCPU / 8 GiB), 앱 외부 포트 8080이다. 로컬 Compose의 127.0.0.1:8000 바인딩과 다르다.
AWS의 /home/ubuntu/mori/compose.yaml은 image: mori-app:latest를 사용한다. compose.override.yaml은 저장소 compose.mcp.yaml과 같은 연결 설정이며 자동 적용된다. Mori 앱은 mori 기본 네트워크와 ocr-pipeline_default에 연결한다.
외부 Nginx 경유 시 MCP의 여러 프로토콜 요청이 요청 제한에 걸렸으므로 다음 내부 URL을 사용한다.
- OCR: http://ocr-pipeline-mcp-1:8001/mcp
- Operations: http://ocr-pipeline-ops-mcp-1:8002/mcp

Host: localhost는 서버의 기존 허용 호스트 설정에 맞춘 것이다. 인증 토큰을 대신하지 않는다. MCP 포트를 외부로 새로 공개할 필요가 없다.

배포 절차:
1. 로컬 테스트 후 docker compose build app으로 빌드한다.
2. docker save로 이미지를 파일로 내보내고 SSH/SCP로 대상 서버에 전달한다. SSH 키는 문서나 저장소에 포함하지 않는다.
3. 서버의 기존 이미지에 백업 태그를 지정하고 Compose 파일을 보관한다.
4. docker load 후 docker compose config --quiet으로 구성을 검증한다.
5. docker compose up -d --no-deps app으로 앱을 교체한다.
6. health → mcp/tools → 실제 도구 채팅 순으로 확인한다.

서버 명령 예:
```bash
cd /home/ubuntu/mori
stamp=$(date +%Y%m%d-%H%M%S)
docker tag mori-app:latest mori-app:backup-$stamp
cp compose.yaml compose.yaml.backup-$stamp
cp compose.override.yaml compose.override.yaml.backup-$stamp
docker load -i mori-app-deploy.tar
docker compose config --quiet
docker compose up -d --no-deps app
docker compose ps
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8080/api/mcp/tools
```

입력 tar 파일명은 실제 전달한 파일명으로 바꾼다. 복구 시 보관한 이미지 태그를 latest로 다시 지정하고 필요 시 동일 시점의 Compose 설정을 복원한 뒤 앱을 재생성한다. 이전 이미지가 HTTP MCP 설정을 지원하는지도 확인한다.
모델은 mori_ollama-data 볼륨에 저장되어 앱 이미지 교체와 분리된다. 모델 태그만 변경할 때는 대상 모델을 먼저 pull하고 앱의 OLLAMA_MODEL 및 이후 초기화에 쓰일 model-init 태그를 함께 맞춘다.

## 11. 검증과 장애 대응
로컬 검증:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check chatbot-ui/constants.js
node --check chatbot-ui/app.js
```

현재 소스의 로컬 리팩터링 검증 기록(2026-09-04):

- OCR 정책 분리 후 `pytest` 58개 통과.
- Ruff 정적 검사 통과 및 공통 포맷 적용.
- 상수 분리 시 `constants.js`와 `app.js` JavaScript 문법 검사 통과.
- 기존 Starlette/AnyIO 의존성의 폐기 예정 API 경고 1건이 남아 있다.
- 이 기록은 로컬 검증 결과다. 실제 모델·원격 MCP·AWS 재배포 검증을 대체하지 않는다.

이전 배포 시점의 검증 기록(2026-09-04):
- 자동화 테스트 25개 통과.
- 도구 6개 발견, OCR 상태·지원 형식·운영 통계 실제 조회 성공.
- Qwen3.5가 두 MCP를 호출한 Thinking OFF 시나리오: 약 48.5초에 SSE done.
- Thinking ON의 짧은 응답 시나리오: 약 30.4초에 SSE done.
서로 다른 질문의 기능 검증 기록으로 성능 비교나 응답시간 보장은 아니다.

증상별 확인:
- 모델 확인 불가: 앱 health 및 Ollama 주소 확인.
- health는 정상인데 채팅 실패: 모델 파일 존재, Ollama 로그, 요청 모델명 확인.
- MCP 도구 없음: use_tools, MCP_SERVERS_JSON, allowed_tools, 네트워크 DNS 확인.
- MCP 연결·호출 오류: MCP 컨테이너 health, Host 허용 목록, MCP 로그 확인.
- SSE가 한꺼번에 도착: 프록시 버퍼링과 스트림 타임아웃 확인.
- 답변 전 대기: Thinking 여부, CPU 사용량, 모델 로딩·입력 처리 시간 확인. keep-alive는 추론 완료 신호가 아니다.
- 모델이 잘못된 기간 조회: tool 카드의 인자를 확인하고 날짜를 명시해 재요청.

로그 확인:
```bash
docker logs --tail 100 mori-app-1
docker logs --tail 100 mori-ollama-1
docker logs --tail 100 ocr-pipeline-mcp-1
docker logs --tail 100 ocr-pipeline-ops-mcp-1
```

## 12. 현재 제약과 후속 개발
- 입력 검증은 required·기본 타입·명시된 additionalProperties=false를 처리한다. enum, 범위, 날짜 형식, 중첩 객체, $ref 등 전체 JSON Schema 검증기는 아니다. Python bool/int 관계도 엄밀히 분리하지 않는다.
- 서버 이름 중복과 도구 목록 페이지네이션에 대한 명시적 처리가 없다.
- MCP 일부 장애 시 나머지 서버만으로 계속하는 격리 처리가 없다. SDK 예외의 일관된 HTTP 오류 변환도 후속 과제다.
- 이미지 첨부는 현재 요청에만 포함된다. 후속 요청에서 같은 이미지를 다시 분석하려면 재첨부해야 한다.
- API 인증·사용자별 요청 제한·역할 제한은 미구현이다. 현재 공개 데모 수준과 운영 서비스 수준을 구분한다.
- 장기 대화 요약·토큰 예산 관리·사용자 취소 버튼·재시도 정책은 미구현이다.
- 날짜 안내는 프롬프트 수준이다. 결정적인 날짜 범위 생성이 필요하면 별도 서버 로직을 추가한다.

## 13. 변경 시 점검 기준
API 필드 변경은 models → routes → ChatService → OllamaClient → UI 순으로 전달 경로를 확인한다. Thinking처럼 라운드별로 유지되어야 하는 값은 도구 호출 이후에도 검사한다.
새 도구 추가는 MCP 서버의 스키마 확인 → 최소 allow-list 등록 → 직접 호출 → 모델의 도구 선택 및 최종 응답 검증 순으로 진행한다. 외부 상태를 바꾸는 도구는 현재 조회 도구와 동일하게 자동 허용하지 않는다.
문서·설정·배포 이미지가 서로 다른 시점을 가리키지 않도록 모델 태그와 검증 날짜를 함께 갱신한다.


## 14. 코드 작성과 상수 관리 기준

Python 3.12 이상을 기준으로 `Self`, 제네릭 타입 매개변수, `Annotated` 의존성 선언과 명시적인 반환 타입을 사용한다. 함수·메서드에는 역할을 설명하는 한국어 docstring을 작성한다. 프런트엔드는 같은 원칙으로 함수 설명과 이름 있는 이벤트 처리 함수를 사용한다.

상수 분리·Enum·포맷 통일은 코드의 일관성을 위한 기준이다. SOLID 적용 여부는 별도로 책임 경계, 확장 방식, 구현체 간 계약과 의존성 방향으로 평가한다. 현재 설계와 확장 기준은 15절에 정리한다.

포맷과 정적 검사 규칙은 `pyproject.toml`의 Ruff 설정으로 통일한다. 런타임 의존성을 추가하지 않고 다음 명령으로 실행한다.

```powershell
uv tool run --from ruff ruff check backend tests main.py
uv tool run --from ruff ruff format --check backend tests main.py
.\.venv\Scripts\python.exe -m pytest -q
node --check chatbot-ui/constants.js
node --check chatbot-ui/app.js
```

### 공통 상수와 Enum

- `backend/constants/`에서 앱 식별자, 환경변수, 경로, 채팅 제한값, 이미지 제한값을 관리한다.
- `backend/constants/enums.py`의 `StrEnum`은 메시지 역할, SSE 이벤트, MCP 전송 방식과 서비스 상태를 정의한다. API 문자열 값은 기존과 같다.
- `chatbot-ui/constants.js`는 UI 제한값과 `Object.freeze`로 고정한 역할·이벤트 선택값을 제공하며 `app.js`보다 먼저 로드한다.
- 이미지 제한과 SSE 이벤트를 변경할 때에는 Python과 JavaScript 양쪽 계약을 함께 갱신한다. 경로·용량처럼 선택지가 아닌 값은 일반 상수로 유지한다.

## 15. SOLID 적용 구조와 확장 기준

### 15.1 현재 평가와 적용 범위

현재 규모에서는 SOLID의 주요 책임·의존성 경계를 반영한 구조다. 대화 조율, HTTP 전송, 도구 공통 실행과 OCR 정책을 분리했고 실제 구현 생성은 앱 조립부에 둔다. 다만 인터페이스 선언과 테스트 통과만으로 모든 구현의 대체 가능성이나 향후 확장성을 보장하지는 않는다.

| 원칙 | 현재 적용 | 유지해야 할 경계와 한계 |
| --- | --- | --- |
| SRP: 단일 책임 | `ChatService`는 추론·도구 실행 순서를 조율한다. `chat_events`는 SSE 전송, `build_history`는 모델 입력 구성, `ToolExecutor`는 공통 호출 검증·실행·결과 변환, `OCRToolPolicy`는 OCR 노출·인자 규칙을 맡는다. | HTTP 처리나 새 도구의 특수 조건을 `ChatService`에 추가하지 않는다. OCR 자연어 안내는 현재 `context.py`의 프롬프트에도 존재한다. |
| OCP: 확장에 열림 | 모델·실행기·정책을 주입해 조율 코드를 바꾸지 않고 교체할 수 있다. | 여러 도구 정책을 선택·조합하는 등록 구조는 아직 없다. 별도 정책이 늘어나면 조합 필요성을 검토한다. |
| LSP: 대체 가능 | `Protocol` 계약에 맞는 대체 모델·실행기·정책으로 대화를 처리하는 테스트가 있다. | 반환 타입뿐 아니라 이벤트 순서, 오류 전달, 취소·자원 정리도 유지해야 한다. 모든 대체 구현에 공통 계약 테스트를 적용한 상태는 아니다. |
| ISP: 인터페이스 분리 | 조회는 `MCPToolCatalog`, 호출은 `MCPToolCaller`, 수명주기 종료는 `MCPGateway`로 구분한다. | 조회만 필요한 객체에 실행·종료 메서드를 요구하지 않는다. 정책의 노출과 인자 변환은 같은 규칙을 공유하므로 `ToolPolicy`에 함께 둔다. |
| DIP: 추상화에 의존 | 서비스와 실행기는 `Protocol`에 의존하며, `lifespan`에서 구체 구현을 생성한다. | 서비스 내부에서 `OllamaClient`, `ConfiguredMCPGateway`, `ToolExecutor`, `OCRToolPolicy`를 새로 생성하지 않는다. |

### 15.2 책임과 인터페이스

| 파일·구성 요소 | 책임 | 사용하는 계약 |
| --- | --- | --- |
| `backend/app.py`의 `lifespan` | 설정 로드, 구체 구현 생성·주입, 앱 종료 시 자원 정리 | 실제 Ollama·MCP·실행기·정책을 조립 |
| `backend/services/chat.py`의 `ChatService` | 도구 조회, 정책 적용, 추론 반복, 실행 요약·최종 결과 이벤트 생성 | `ChatModel`, `MCPToolCatalog`, `ToolRunner`, `ToolPolicy` |
| `backend/services/context.py`의 `build_history` | 원본 메시지를 보존하며 이미지와 시스템 안내를 모델 입력에 추가 | 메시지·도구·이미지 데이터 |
| `backend/services/tools.py`의 `ToolExecutor` | 등록된 도구명·객체 인자 확인, 정책 인자 적용, MCP 실행과 결과 변환 | `MCPToolCaller`, `ToolPolicy` |
| `backend/services/tool_policy.py`의 `OCRToolPolicy` | OCR 노출 여부, 모델용 빈 스키마, 실제 첨부 주입, 공개용 인자 구성 | `ToolPolicy`의 두 메서드 구현 |
| `backend/api/streaming.py`의 `chat_events` | SSE 직렬화, keep-alive, 사용자용 오류, 대기 작업 취소 | `ChatService`의 이벤트 스트림 |
| `backend/mcp/stdio_gateway.py`의 `ConfiguredMCPGateway` | 전송 연결, 허용 목록·입력 스키마 검증, SDK 결과 변환 | 조회·호출·종료 계약을 모두 구현 |

`ChatModel.stream_chat`은 종료 가능한 비동기 생성기를 반환한다. `ToolRunner.execute`는 `ToolExecution`을 반환하며, 여기에는 UI용 `activity`와 후속 추론용 `message`가 포함된다. `ToolPolicy.prepare_arguments`가 반환하는 `ToolArguments`는 서버 전달용 `execution`과 UI 공개용 `display`를 구분한다.

### 15.3 앱 조립과 동일 정책 주입

현재 조립은 `backend/app.py`의 `lifespan`에 있다. 아래 코드는 이미 생성된 `ollama`, `mcp`, `settings`를 사용한 해당 부분이다.

```python
tool_policy = OCRToolPolicy()
chat_service = ChatService(
    ollama,
    mcp,
    settings.ollama_model,
    settings.max_tool_rounds,
    tool_executor=ToolExecutor(mcp, tool_policy),
    tool_policy=tool_policy,
)
```

`tool_executor`와 `tool_policy`는 필수 키워드 인자다. 같은 정책 인스턴스를 서비스와 실행기에 전달해야 도구 노출 규칙과 실행 인자 규칙이 일치한다. 현재 생성자가 동일 인스턴스 여부를 강제하지 않으므로 앱 조립부와 테스트에서 이 관계를 유지한다.

`ChatService`는 MCP의 조회만 사용한다. 실제 호출은 주입된 실행기를 통해 수행한다. 앱 종료 시 연결 정리는 조립부의 책임이며, 모델 스트림과 요청별 MCP 세션의 정리는 각 처리 계층에서 수행한다.

### 15.4 OCR 정책의 처리 계약

1. 이미지가 없으면 `prepare_tools`가 OCR 도구를 모델 목록에서 제외한다. 일반 도구는 유지한다.
2. 이미지가 있으면 OCR 도구를 인자 없는 스키마로 노출한다. 모델에 Base64를 도구 인자로 생성하도록 요구하지 않는다.
3. 모델이 도구를 요청하면 `ToolExecutor`가 등록된 이름인지, 인자가 JSON 객체인지 확인한다.
4. `prepare_arguments`는 OCR에 첨부가 있는지와 모델 인자가 비어 있는지 확인한다. 잘못된 요청은 MCP 호출 전에 거부한다.
5. 서버 전달용 인자에는 실제 `data_base64`·`mime_type`을 넣고, UI 공개용 인자에는 파일명·MIME만 넣는다.
6. MCP 게이트웨이는 원래 서버 스키마와 허용 목록으로 실제 인자를 검증한 뒤 호출한다.

도구 정책은 MCP 허용 목록이나 서버 입력 검증을 대신하지 않는다. 일반 도구의 인자는 현재 정책에서 그대로 전달한다. 또한 OCR 정책이 도구를 실행하기로 결정하지는 않는다. 일반 이미지 질문은 모델의 시각 입력을 사용하고 OCR 호출 여부는 모델이 선택한다.

### 15.5 새 기능·도구를 추가할 때

- 일반 조회 도구가 기존 인자 전달 방식으로 충분하면 MCP 설정과 허용 목록을 추가하고 통합 흐름을 검증한다. 정책 클래스를 자동으로 늘리지 않는다.
- 새로운 도구에 첨부 주입·인자 변환·공개 정보 제한이 필요하면 해당 규칙을 정책으로 구현하고 앱 조립부에서 연결한다. `ChatService`나 `ToolExecutor`에 도구 이름별 분기를 추가하지 않는다.
- OCR과 독립된 정책이 함께 필요해지면 정책 선택·조합 구조를 검토한다. 이 구조는 현재 미구현이며, 확장 시 기존 OCR 규칙과 일반 도구 동작을 보존해야 한다.
- 추론 구현을 바꾸면 `ChatModel` 계약에 맞추고 Thinking 전달, 응답 조각, 도구 호출, 오류·종료 동작을 확인한다.
- 모델 안내도 바뀌는 기능이면 `context.py`의 프롬프트를 함께 검토한다. 정책 교체만으로 자연어 안내까지 자동 변경되지는 않는다.

현재 단계에서는 추가 계층보다 실제 요구에 맞는 경계를 유지한다. 추상화는 별도 책임 또는 실제 교체 필요성이 생겼을 때 추가한다.

### 15.6 검증 근거와 남은 점검

| 검증 파일 | 확인하는 동작 |
| --- | --- |
| `tests/test_chat_service.py` | 기본 도구 실행, 미등록·잘못된 호출 차단, 실행기 교체, 조회 전용·호출 전용 구현 사용 |
| `tests/test_tool_policy.py` | 첨부 누락·임의 OCR 인자 차단, 주입한 정책의 노출·실행 동시 적용, 공개용 인자 분리 |
| `tests/test_images.py` | 실제 이미지 검증, 모델의 OCR 선택, 도구 OFF 이미지 처리, Base64 노출 방지 |
| `tests/test_streaming.py` | 응답 조각 순서, SSE 오류 처리, keep-alive, 소비자 종료 시 작업 정리 |
| `tests/test_thinking.py` | 일반·스트리밍 요청과 도구 호출 이후 Thinking 선택 유지 |
| `tests/test_constants.py` | Enum 도입 후 기존 문자열 입력·직렬화 호환성 |

현재 58개 테스트 통과는 위 구현과 테스트 시나리오에 대한 근거다. 모든 구현체의 예외·취소 계약, 실제 원격 서비스 장애, 장시간 운영까지 검증했다는 의미는 아니다. 새 구현체에는 해당 경로의 계약 테스트를 적용하고, 배포 전에 실제 Ollama·MCP 연결을 별도로 확인한다.
