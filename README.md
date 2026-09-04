# CPU 기반 Qwen3 챗봇

이 프로젝트는 AWS EC2에서 CPU만 사용해 Qwen3 기반 챗봇을 실행하는 것을 목표로 합니다.

## 확인된 AWS EC2 사양

- CPU: Intel Xeon Platinum 8488C, 2 vCPU
- 메모리: 3.7 GiB
- 확인 당시 사용 가능한 메모리: 약 2.6 GiB
- Swap: 없음
- 루트 디스크: 29 GB
- 확인 당시 디스크 여유 공간: 약 8.6 GB

## 권장 모델

기본 모델을 Qwen3 0.6B에서 `qwen3.5:2b-q4_K_M`로 변경했습니다.
이 태그는 약 1.9GB인 4비트 모델입니다. `qwen3.5:2b`는 약 2.7GB인
8비트 모델이므로 메모리가 작은 서버에서는 전체 태그를 사용합니다.
현재 EC2에서의 실제 메모리 사용량과 응답 속도는 배포 후 검증해야 합니다.

| 모델 | 판단 | 비고 |
| --- | --- | --- |
| `qwen3.5:2b-q4_K_M` | 기본 모델 | 짧은 대화·단일 요청으로 메모리와 속도 검증 필요 |
| `qwen3:0.6b` | 이전 모델 | 메모리 부족 시 되돌릴 후보 |
| `qwen3:1.7b` | 제한적으로 가능 | 응답이 느리고 메모리가 부족할 수 있음 |
| `qwen3:4b` | 비권장 | 메모리 부족 또는 OOM 종료 위험 |
| `qwen3:8b` 이상 | 실행 곤란 | 현재 CPU와 메모리로는 실용적이지 않음 |

## Ollama로 실행

Ollama가 설치된 환경에서 다음 명령으로 모델을 내려받아 실행합니다.

```bash
ollama run qwen3.5:2b-q4_K_M
```

Windows의 Ollama 실행 파일은 `D:\Ollama`에 있습니다. 이전 모델 파일은
`D:\Ollama\models`에 있지만, 2026-09-04 확인한 실행 중 서버는
`C:\Users\Administrator\.ollama\models`를 사용합니다.
모델 다운로드는 실행 중인 서버의 저장소에 기록됩니다. D: 저장소로 전환하려면
Ollama 서버 환경에 `OLLAMA_MODELS=D:\Ollama\models`를 적용하고 재시작해야 합니다.

Ollama API의 기본 주소는 다음과 같습니다.

```text
http://localhost:11434
```

서비스가 실행 중인지 확인하려면 다음 명령을 사용합니다.

```bash
curl http://localhost:11434/api/tags
```

## 더 큰 모델을 사용할 경우

`qwen3:4b`를 사용하려면 RAM 8 GB 이상이 필요하며, 운영체제와 다른 서비스의 메모리 사용량까지 고려하면 RAM 16 GB 구성을 권장합니다.

프로덕션 환경에서는 메모리 부족으로 프로세스가 종료되는 상황을 줄이기 위해 Swap을 추가하고, 모델 프로세스의 메모리 사용량을 모니터링하는 것이 좋습니다.

## 추론 서버 선정: Ollama와 vLLM

vLLM은 Linux x86 CPU와 Qwen3 모델을 기술적으로 지원합니다. 그러나 현재 EC2의 2 vCPU 및 3.7 GiB RAM 구성에서는 사용하지 않습니다.

vLLM은 Python과 PyTorch 런타임을 포함하므로 모델 이외에도 추가 메모리를 사용합니다. 현재 서버에서는 이 오버헤드 때문에 설치 또는 모델 로딩에 실패하거나, 실행 중 메모리 부족으로 프로세스가 종료될 가능성이 큽니다. 또한 vLLM의 주요 장점인 높은 동시 요청 처리량을 활용하기에도 CPU와 메모리가 부족합니다.

따라서 현재 환경에서는 GGUF 4비트 양자화 모델을 효율적으로 실행할 수 있는 Ollama를 사용합니다.

| 항목 | Ollama | vLLM |
| --- | --- | --- |
| 현재 서버 적합성 | 적합 | 부적합 |
| 권장 모델 | `qwen3.5:2b-q4_K_M` | 현재 환경에서는 사용하지 않음 |
| 메모리 부담 | 비교적 낮음 | 높음 |
| 주요 용도 | 소규모·단일 사용자 챗봇 | GPU 기반 고성능·다중 요청 API 서버 |

vLLM은 챗봇 사용자 화면이 아니라 모델 추론 API 서버입니다. 향후 인스턴스를 GPU 서버 또는 충분한 CPU와 메모리를 갖춘 서버로 확장하고 동시 요청 처리량이 중요해질 때 도입을 다시 검토합니다.

## 권장 챗봇 구성

현재 서버의 권장 요청 흐름은 다음과 같습니다.

```text
사용자
  ↓
가벼운 웹 채팅 화면
  ↓
FastAPI 또는 Flask 백엔드
  ↓
Ollama API (localhost:11434)
  ↓
Qwen3.5 2B
```

Ollama는 외부에 직접 노출하지 않고 로컬 주소에서만 실행합니다. 웹 백엔드가 Ollama API를 호출하게 구성하고, 외부 요청은 웹 서버를 통해서만 받는 방식을 권장합니다.

## MCP 지원 요구사항

이 챗봇은 향후 외부 데이터와 도구를 연결할 수 있도록 MCP(Model Context Protocol)를 지원하는 구조로 개발해야 합니다. vLLM은 MCP 사용을 위한 필수 요소가 아니며, FastAPI 또는 Flask 백엔드가 MCP Host 및 Client 역할을 담당합니다.

```text
사용자
  ↓
웹 채팅 화면
  ↓
FastAPI 또는 Flask 백엔드 (MCP Host/Client)
  ├─ Ollama API → Qwen3.5 2B
  └─ MCP Server → 파일, 데이터베이스, 검색, 외부 API
```

### 필수 동작

백엔드는 다음 순서로 요청을 처리해야 합니다.

1. 연결된 MCP 서버에서 사용 가능한 도구 목록과 입력 스키마를 조회합니다.
2. 사용자 요청과 허용된 도구 설명을 Qwen3에 전달합니다.
3. 모델이 생성한 도구 호출의 이름과 인자를 백엔드에서 검증합니다.
4. 검증에 성공한 요청만 MCP 서버로 전달합니다.
5. MCP 도구 실행 결과를 모델에 다시 전달합니다.
6. 모델이 생성한 최종 답변을 사용자에게 반환합니다.

MCP 연결 방식은 로컬 MCP 서버를 위한 `stdio`와 원격 MCP 서버를 위한 Streamable HTTP를 고려합니다. 초기 버전에서는 구현과 운영이 단순한 로컬 `stdio` 연결부터 지원합니다.

### 모델 및 도구 설계 제한

현재 사용하는 `qwen3.5:2b-q4_K_M`는 작은 모델이므로 복잡한 도구 선택이나 인자 생성의 정확도가 낮을 수 있습니다. 초기 버전에서는 읽기 중심의 단순한 도구를 2~5개 정도만 제공하고, Ollama의 구조화된 tool calling API를 사용합니다.

적합한 초기 MCP 도구 예시는 다음과 같습니다.

- 문서 또는 파일 검색
- 데이터베이스 읽기 조회
- 서비스 상태 확인
- 제한된 외부 정보 조회

### 보안 요구사항

- 백엔드에 명시된 허용 목록의 MCP 서버와 도구만 호출합니다.
- 모델이 생성한 도구 이름과 모든 입력값을 신뢰하지 않고 스키마로 검증합니다.
- 파일 쓰기, 삭제, 결제, 권한 변경 및 서버 설정 변경 작업은 기본적으로 비활성화합니다.
- 상태를 변경하는 도구는 실행 직전에 사용자 확인을 받아야 합니다.
- MCP 서버에는 작업에 필요한 최소 권한만 부여합니다.
- 인증 정보와 API 키를 프롬프트, 응답 또는 로그에 기록하지 않습니다.
- 도구 실행에 타임아웃, 결과 크기 제한 및 오류 처리를 적용합니다.
- Ollama와 로컬 MCP 서버 포트는 인터넷에 직접 공개하지 않습니다.

### 개발 단계

1. Ollama와 `qwen3.5:2b-q4_K_M`를 이용한 기본 대화 API를 구현합니다.
2. 백엔드에 MCP Client를 추가하고 로컬 MCP 서버 한 개와 연결합니다.
3. 도구 허용 목록, 입력 스키마 검증 및 실행 타임아웃을 구현합니다.
4. 도구 호출 전후 결과와 오류를 확인할 수 있는 감사 로그를 추가합니다. 단, 비밀 정보는 기록하지 않습니다.
5. 작은 모델에서 도구 선택과 인자 생성이 안정적인지 테스트합니다.
6. 안정성이 확인된 읽기 전용 도구부터 운영 환경에 활성화합니다.

## 웹 앱 실행

```powershell
uv sync --extra dev
uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

브라우저에서 `http://127.0.0.1:8000`을 엽니다. Ollama는 별도로 실행되어 있어야 하며
기본 주소와 모델은 각각 `http://127.0.0.1:11434`, `qwen3.5:2b-q4_K_M`입니다.

### API

- `GET /api/health`: Ollama 및 MCP 구성 상태
- `GET /api/mcp/tools`: 허용 목록을 통과한 MCP 도구
- `POST /api/chat`: Ollama 대화와 MCP 도구 호출 루프
- `POST /api/chat/stream`: 동일한 요청 본문으로 SSE 실시간 응답
- `GET /docs`: FastAPI OpenAPI 문서

웹 화면은 `fetch`로 `/api/chat/stream`을 호출해 답변을 한 말풍선에 이어서 표시합니다.
SSE 이벤트는 `model`(모델명), `round`(추론 시작), `delta`(텍스트 조각),
`tool`(도구 실행 결과), `done`(최종 ChatResponse), `error`(오류)입니다.
`done` 없이 연결이 끝나면 미완료 응답으로 처리합니다. 모델의 thinking 텍스트는
화면에 노출하지 않으므로 최종 답변 생성 전에는 로딩 표시가 유지될 수 있습니다.
15초마다 keep-alive 주석을 보내고 `X-Accel-Buffering: no`로 프록시 버퍼링을
해제하도록 요청합니다. 별도 프록시가 있다면 SSE 버퍼링 및 읽기 타임아웃 설정도
확인해야 합니다. 브라우저 연결 종료 시 진행 중인 Ollama HTTP 스트림을 닫습니다.

기본 설정은 `.setting/settings.json`, 환경 변수 예시는 `.setting/.env.example`에 있습니다.
환경 변수는 JSON 설정을 덮어씁니다. MCP 서버는 `MCP_SERVERS_JSON`에 등록하며,
`allowed_tools`에 명시한 도구만 모델에 노출됩니다. 초기 구현은 로컬 `stdio` 전송을
사용하고 도구 입력 스키마, 실행 제한 시간, 최대 반복 횟수를 검증합니다.

## Docker Compose 배포

Docker Desktop이 실행된 상태에서 다음 명령으로 전체 서비스를 배포합니다.

```powershell
docker compose up --build -d
```

Compose는 CPU용 Ollama를 먼저 시작하고 `qwen3.5:2b-q4_K_M` 모델을 영구 볼륨에 준비한 뒤
FastAPI를 시작합니다. 웹 UI는 `http://127.0.0.1:8000`, 컨테이너 Ollama API는
호스트의 `http://127.0.0.1:11435`에서 확인할 수 있습니다. 컨테이너 내부 FastAPI는
Compose DNS 이름인 `http://ollama:11434`를 사용합니다.

Compose의 Ollama는 컨텍스트 2048 토큰, 동시 추론 1개, 동시 로드 모델 1개로
제한합니다. 긴 대화에서는 이전 내용 일부가 컨텍스트에서 제외될 수 있습니다.
로컬 Ollama에도 같은 제한을 적용하려면 서버를 시작하는 환경에
`OLLAMA_CONTEXT_LENGTH=2048`, `OLLAMA_NUM_PARALLEL=1`,
`OLLAMA_MAX_LOADED_MODELS=1`을 설정하고 Ollama를 재시작합니다.
앱의 `.env` 예시만 바꿔서는 별도로 실행 중인 Ollama 서버 설정이 바뀌지 않습니다.

모델 변경 배포 시 `docker compose pull ollama model-init` 후 위 실행 명령을 사용합니다.
배포 후 짧은 한국어 질문과 도구 호출을 확인하고 `docker stats --no-stream`으로
메모리를 측정합니다. RAM 3.7 GiB에서의 안정적인 운영을 보장하지 않습니다.

```powershell
docker compose ps
docker compose logs -f app
docker compose down
```

`docker compose down`은 컨테이너만 제거하고 모델 볼륨은 유지합니다. 모델까지 지우려는
경우에만 명시적으로 `docker compose down --volumes`를 사용합니다.
