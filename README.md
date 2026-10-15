# Spatial LLM Server

기존 Python 벡터 프로그램과 독립적으로 실행하는 Python/FastAPI AI 백엔드입니다.
현재는 **LLM 도구 선택 → WebSocket 실행 → 결과를 반영한 답변 생성**까지 구현했습니다. 별도 벡터 프로그램 프로젝트에는 도킹·분리 가능한 채팅 UI를 연결했습니다.

## 현재 범위

- FastAPI 앱과 `/api/v1` API 경로
- 서버 생존 확인 API, Swagger API 문서, OpenAPI 명세
- 환경변수 및 `.env` 설정
- 독립 가상환경, 의존성 잠금 파일, 기본 검증 테스트

Ollama 연결 확인, 비스트리밍 채팅, 프로그램별 도구 목록 등록·조회·형식 검증을 제공합니다.
WebSocket으로 연결된 벡터 프로그램의 레이어 조회·Photoshop ping을 직접 테스트할 수 있습니다.
읽기 전용 두 도구의 LLM 선택을 제공합니다. 영상 편집 자동화, 사용자 인증·세션 저장은 아직 구현하지 않았습니다.
기존 `C:\workspace\spatial_editor_tool`의 코드나 환경을 사용하거나 변경하지 않습니다.
별도 웹 UI는 만들지 않으며 `/docs`는 개발용 API 문서입니다.

## 환경

- Python 3.11 이상 (현재 로컬 검증: Python 3.11)
- Windows PowerShell 기준 명령
- 서버 생존 확인에는 Ollama가 필요하지 않습니다. 실제 채팅에는 실행 중인 Ollama와 설치된 모델이 필요합니다.
- Node·Photoshop은 이번 단계에서 사용하지 않습니다.

## 설치

```powershell
Set-Location 'C:\workspace\AI project\llm-server'
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
```

이미 `.venv`와 `.env`가 있다면 생성·복사 명령은 생략합니다.
가상환경을 활성화하지 않고 해당 Python을 직접 사용하므로 PowerShell 실행 정책 변경은 필요 없습니다.
`requirements-lock.txt`는 로컬 검증 환경의 정확한 버전 목록이며 개발 테스트 의존성도 포함합니다.

의존성을 새로 해결하여 업데이트할 때:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip freeze --exclude-editable | Set-Content -Encoding utf8 requirements-lock.txt
```

## 개발 서버 실행

프로젝트 루트에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- 상태 확인: http://127.0.0.1:8000/api/v1/health
- API 문서: http://127.0.0.1:8000/docs
- API 명세: http://127.0.0.1:8000/openapi.json
- 종료: 서버 터미널에서 `Ctrl+C`

다른 PowerShell 창에서 확인:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health'
```

예상 JSON 응답: `{"status":"ok"}`. 백엔드 생존 상태만 의미하며 Ollama·Photoshop 연결 상태는 아닙니다.
`/` 경로는 구현하지 않았으므로 404가 정상입니다.
포트가 사용 중이면 `--port 8001`로 변경하고 확인 URL도 변경합니다.

자동 재시작 없이 실행:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

현재는 로컬 HTTP 개발용입니다. 중앙 배포 시 HTTPS/WSS, 인증, 접근 제어와 운영 실행 구성을 추가합니다.

## 설정

`.env.example`을 참고합니다. OS 환경변수가 `.env`보다 우선합니다.

| 변수 | 기본값 | 역할 |
|---|---|---|
| `LLM_SERVER_APP_NAME` | `Spatial LLM Server` | API 문서의 서비스 이름 |
| `LLM_SERVER_ENVIRONMENT` | `local` | 실행 환경 표시값; 배포·인증 모드를 자동 변경하지 않음 |

`.env`는 프로젝트 루트 기준으로 읽습니다. 호스트·포트는 Uvicorn 실행 인자로 지정합니다.
설정 변경 후 서버를 재시작합니다. `.env`와 `.venv`는 Git 추적에서 제외합니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

헬스 응답, OpenAPI 경로, API 문서 제공, 환경변수 적용을 검사합니다.

## 모듈 구성

```text
app/
  main.py             # 앱 생성과 라우터 연결
  api/health.py       # /api/v1/health
  core/config.py      # 환경 설정
tests/test_app.py     # 기본 API·설정 검증
pyproject.toml       # 프로젝트·의존성 범위
requirements-lock.txt # 검증한 정확한 의존성 버전
.env.example         # 설정 예시
```

## 이후 개발 경계

1. 완료: 독립 FastAPI 프로젝트와 로컬 실행 검증
2. 완료: FastAPI ↔ Ollama 연결과 기본 비스트리밍 채팅
3. 백엔드 완료: 프로그램·도구 등록/조회/검증 API. 벡터 프로그램 측 전송 모듈은 별도 연결 필요
4. 완료: WebSocket 도구 실행과 LLM 도구 선택·최종 답변. 채팅 UI는 별도 개발
5. OpenCV 자동화 기능을 실행 가능한 도구로 연결
6. 사용자 세션 및 동시 요청 처리 고도화

Ollama가 추론을 담당하고, 백엔드가 대화·도구 선택·작업 전달을 담당합니다.
실제 벡터 편집·OpenCV·Photoshop MCP 실행은 벡터 프로그램 측에서 담당하는 구조입니다.
향후 통신 계약에는 사용자/대화/클라이언트/작업/호출 식별자를 포함하고, 도구 결과와 연결 복구를 설계합니다.
이번 단계에서는 미확정 채팅·도구 API나 임시 에코 WebSocket을 만들지 않습니다.

## 참고

- [FastAPI 공식 시작 문서](https://fastapi.tiangolo.com/tutorial/first-steps/)
- [Pydantic Settings 공식 문서](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

## 2단계: Ollama 준비와 채팅 실행

### Ollama 준비

이 PC에서는 실행 중인 Ollama와 `qwen2.5:0.5b` 모델을 확인했습니다.
로컬 `.env`는 이 모델로 설정했습니다. 이 모델은 연결 검증용이며 편집 도구 선택 품질은 검증하지 않았습니다.
새 서버에서는 [Ollama Windows](https://ollama.com/download/windows)를 설치하고 다음을 확인합니다.

```powershell
ollama --version
ollama list
Invoke-RestMethod 'http://127.0.0.1:11434/api/version'
```

Ollama 앱을 실행하면 기본적으로 백그라운드 API가 시작됩니다.
앱 대신 CLI로 실행할 때만 별도 터미널에서 `ollama serve`를 사용합니다.
이미 API가 실행 중이면 `ollama serve`를 중복 실행하지 않습니다.
백엔드는 Ollama 프로세스를 시작·종료하거나 모델을 자동 다운로드하지 않습니다.

6GB VRAM 서버에서 다음 단계의 모델 후보로 `qwen3:4b`를 사용할 경우:

```powershell
ollama pull qwen3:4b
```

다운로드 후 `.env`의 모델 값을 `qwen3:4b`로 변경하고 FastAPI를 재시작합니다.
모델 다운로드 크기와 실제 VRAM 사용량은 다르며, Photoshop과 함께 실행하는 자원 검증은 별도입니다.

### 백엔드 환경 설정

```dotenv
LLM_SERVER_OLLAMA_BASE_URL=http://127.0.0.1:11434
LLM_SERVER_OLLAMA_MODEL=qwen2.5:0.5b
LLM_SERVER_OLLAMA_TIMEOUT_SECONDS=120
LLM_SERVER_OLLAMA_NUM_CTX=4096
LLM_SERVER_OLLAMA_NUM_PREDICT=512
LLM_SERVER_OLLAMA_KEEP_ALIVE=5m
```

| 설정 | 의미 |
|---|---|
| `OLLAMA_BASE_URL` | `LLM_SERVER_` 접두사를 붙여 사용. Ollama 주소이며 `/api`는 붙이지 않음 |
| `OLLAMA_MODEL` | `ollama list`에 나오는 모델 이름. 예시 파일 기본값은 `qwen3:4b` |
| `OLLAMA_TIMEOUT_SECONDS` | 채팅 대기 시간과 추론을 합친 최대 시간; HTTP 요청 제한에도 사용 |
| `OLLAMA_NUM_CTX` | 컨텍스트 토큰 수; 초기값 4096 |
| `OLLAMA_NUM_PREDICT` | 최대 생성 토큰 수; 초기값 512 |
| `OLLAMA_KEEP_ALIVE` | 응답 후 모델 유지 시간. `5m` 또는 즉시 해제를 위한 `0` 등 Ollama 형식 |

설치 디렉터리와 관계없이 HTTP로 연결합니다. Ollama 버전은 조회 결과로 표시하며 백엔드가 변경하지 않습니다.
모델 저장 디렉터리는 백엔드 `.env`가 아니라 **Ollama 프로세스의 `OLLAMA_MODELS` 환경변수**로 설정하고 Ollama를 재시작합니다.
공식 설명: [Ollama Windows 설정](https://docs.ollama.com/windows).

### Swagger에서 확인

1. 위의 개발 서버 명령으로 FastAPI를 실행합니다.
2. http://127.0.0.1:8000/docs 에 접속합니다.
3. `GET /api/v1/ollama/status` → Try it out → Execute로 연결과 설치 모델을 확인합니다.
4. `POST /api/v1/chat` → Try it out에서 다음 JSON을 실행합니다.

```json
{
  "messages": [
    {"role": "user", "content": "안녕하세요. 한국어로 짧게 자기소개해 주세요."}
  ]
}
```

응답의 `message.content`에 모델 답변이 표시됩니다. 첫 요청은 모델 로딩으로 더 오래 걸릴 수 있습니다.
후속 질문은 이전 user/assistant 메시지와 새 질문을 순서대로 모두 보냅니다.
현재는 대화를 서버에 저장하지 않으며 `request_id`는 개별 응답 추적용입니다.
생성 길이 제한으로 잘리면 완성된 답변으로 반환하지 않고 `502 ollama_output_truncated`로 처리합니다.

PowerShell에서도 테스트할 수 있습니다. 한글은 UTF-8 바이트로 전송합니다.

```powershell
$chatBody = @{ messages = @(@{ role = 'user'; content = '안녕하세요. 짧게 답해 주세요.' }) } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/chat' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($chatBody))
```

### 오류와 실행 제한

- `422`: 빈 메시지, 허용하지 않은 역할·필드 등 입력 오류
- `503 / ollama_unavailable`: Ollama 미실행 또는 연결 주소 오류
- `504 / ollama_timeout`: 대기·추론 시간 초과
- `502 / ollama_model_unavailable`: 모델 없음; `ollama list`와 `.env` 확인
- 기타 `502`: Ollama 오류 또는 잘못된 응답; Ollama 로그·버전·모델 확인
- Ollama가 꺼져 있어도 `/api/v1/health`는 정상 응답할 수 있습니다.

추론은 프로세스 내에서 한 번에 하나씩 처리합니다. 지금은 Uvicorn **단일 worker**로 실행합니다.
대기 중인 요청도 설정한 시간이 지나면 종료되며, 자동 재시도하지 않습니다.
타임아웃·취소 후 Ollama 내부 추론이 즉시 멈춘다고 보장하지 않습니다.
다중 사용자 인증·세션 저장·영속 작업 큐·스트리밍·WebSocket·Tool Calling은 이후 단계입니다.
메시지는 최대 32개, 각 내용은 최대 16,000자이며 실제 컨텍스트 예산은 토큰 수에 따라 달라집니다.
현재 채팅 API는 이미지나 도구 호출을 받지 않습니다. 도구 정의 등록은 아래의 별도 API를 사용합니다.

추가 모듈: `app/llm/ollama.py`, `app/schemas/chat.py`, `app/api/chat.py`, `app/api/ollama.py`.
테스트는 Ollama 모의 응답으로 정상 전달·연결 실패·타임아웃·모델 없음·응답 오류·입력 검증을 확인합니다.

API 참고: [Ollama Chat](https://docs.ollama.com/api/chat), [모델 목록](https://docs.ollama.com/api/tags).

## 3단계: 프로그램·도구 목록 등록

이 단계는 벡터 프로그램이 "내가 실행 가능한 기능"을 백엔드에 알려주는 수신부입니다.
Ollama·Photoshop이 꺼져 있어도 등록을 테스트할 수 있습니다.
등록 정보는 SQLite에 유지되지만 온라인 여부·기능 실행 성공·MCP 호환성을 보증하지 않습니다.
현재 `/chat`은 일반 채팅만 수행하며 등록한 도구를 LLM에 전달하거나 실행하지 않습니다.

### 업데이트 후 실행

실행 중인 서버를 Ctrl+C로 종료하고 다음 명령을 실행합니다. 기존 `.env`는 유지합니다.

```powershell
Set-Location 'C:\workspace\AI project\llm-server'
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Swagger 테스트 순서

http://127.0.0.1:8000/docs 에서 **clients & tools** 그룹을 펼칩니다.
표시되지 않으면 서버 재시작 후 Ctrl+F5로 새로고침합니다. 각 요청은 Try it out → Execute로 실행합니다.

**1. `PUT /api/v1/clients/{client_id}`: 프로그램 등록**

`client_id`에는 `dev-vector-pc`를 입력하고 본문은 다음과 같이 보냅니다.

```json
{
  "display_name": "개발 PC 벡터 프로그램",
  "app_version": "1.0.0"
}
```

**2. `PUT /api/v1/clients/{client_id}/tools`: 도구 목록 등록**

같은 `client_id`를 사용합니다. 아래는 등록 형식 테스트용이며 실제 연결 확인은 실행하지 않습니다.

```json
{
  "tools": [
    {
      "name": "photoshop_ping",
      "description": "Photoshop 연결 상태를 확인합니다.",
      "source": "photoshop_mcp",
      "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": false
      }
    },
    {
      "name": "photoshop_open_image",
      "description": "지정한 파일을 Photoshop에서 엽니다.",
      "source": "photoshop_mcp",
      "input_schema": {
        "type": "object",
        "properties": {
          "filePath": {"type": "string", "minLength": 1}
        },
        "required": ["filePath"],
        "additionalProperties": false
      }
    }
  ]
}
```

응답에는 `client_id`, 도구 목록 `tools`, 변경 번호 `revision`, 변경 시각 `updated_at`이 표시됩니다.

**3. `GET /api/v1/clients/{client_id}/tools`: 저장한 도구 확인**

**4. `GET /api/v1/clients`: 등록된 프로그램 확인**

### 규칙과 오류

- 프로그램 설치별로 고유한 `client_id`를 생성해 보관하고 재시작 시 재사용합니다.
- ID는 영문·숫자로 시작하고 영문·숫자·밑줄·하이픈으로 구성하며 최대 64자입니다.
- 같은 ID 재등록은 표시 이름·버전만 갱신하고 도구 목록을 유지합니다.
- 도구 등록은 **전체 교체**입니다. 생략한 기존 도구는 제거되며 `{"tools": []}`는 모두 해제합니다.
- 동일한 목록을 그대로 재전송하면 변경 번호와 변경 시각이 유지됩니다.
- 동시 갱신은 마지막으로 저장된 목록이 적용됩니다. 한 설치에서 목록을 관리하는 주체는 하나로 둡니다.
- 서로 다른 프로그램은 같은 도구 이름을 등록할 수 있습니다. 실행 시에는 client_id와 이름을 함께 사용해야 합니다.
- `source`는 `photoshop_mcp` 또는 `python`입니다. 코드·스크립트·실행 URL은 받지 않습니다.
- 도구 이름은 영문·밑줄로 시작하고 영문·숫자·밑줄·하이픈을 사용하며 최대 64자입니다.
- 목록은 최대 128개이며 같은 프로그램 안에서 이름이 중복되면 전체 요청을 거부합니다.
- 입력 스키마는 최상위 `type: object`인 Draft 2020-12 인라인 JSON Schema입니다.
- `$schema`는 생략 가능하며 `$ref` 등 참조는 아직 지원하지 않습니다. MCP 스키마에 참조가 있다면 클라이언트에서 인라인으로 변환해야 합니다.
- 스키마는 도구당 64KiB, 중첩 깊이 32 이하이며 최상위 `required`는 `properties`에 정의된 이름이어야 합니다.
- `404 / client_not_found`: 먼저 프로그램을 등록해야 합니다.
- `422`: 필수 항목 누락·형식 오류·중복 이름·잘못된 JSON Schema. 전체 요청을 거부하고 기존 목록을 보존합니다.

검증은 정의의 형식 검사입니다. 등록된 기능의 존재나 설명의 사실 여부, 파일 접근 가능 여부는 검사하지 않습니다.
현재 인증·소유권 검사가 없는 로컬 개발 API입니다. 중앙 배포 전에 사용자별 접근 제어를 추가해야 합니다.

### 저장 경로

기본 파일은 `data/registry.sqlite3`이며 첫 서버 기동 시 생성됩니다. `.gitignore`에서 제외합니다.
필요하면 `.env`에 다음을 추가하고 서버를 재시작합니다.

```dotenv
LLM_SERVER_REGISTRY_DATABASE_PATH=data/registry.sqlite3
```

상대 경로는 프로젝트 루트 기준입니다. 절대 경로도 사용할 수 있습니다.
예: `LLM_SERVER_REGISTRY_DATABASE_PATH=C:/llm-server-data/registry.sqlite3`.
저장 경로를 바꾸면 다른 DB를 사용하며 기존 등록을 자동으로 옮기지 않습니다.

### 이후 벡터 프로그램에서 연결할 규격

1. 시작 시 설치별 ID로 프로그램 등록 PUT을 호출합니다.
2. 실행 가능한 도구를 준비하여 도구 목록 PUT을 호출합니다.
3. MCP `tools/list` 결과의 `inputSchema`는 `input_schema`로 매핑하고 `source: photoshop_mcp`를 추가합니다.
4. 실제 실행 가능한 도구만 선택해 등록합니다. Python 기능은 같은 형식에 `source: python`으로 등록합니다.

벡터 프로그램을 수정할 때 참고할 최소 예제입니다. 이 코드는 백엔드에서 자동 실행하지 않습니다.

```python
import httpx

client_id = "dev-vector-pc"  # 실제 앱에서는 설치별 고유 ID를 보관해서 재사용
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as api:
    api.put(f"/api/v1/clients/{client_id}", json={
        "display_name": "개발 PC 벡터 프로그램", "app_version": "1.0.0",
    }).raise_for_status()
    api.put(f"/api/v1/clients/{client_id}/tools", json={"tools": [{
        "name": "photoshop_ping",
        "description": "Photoshop 연결 상태를 확인합니다.",
        "source": "photoshop_mcp",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    }]}).raise_for_status()
```

추가 모듈: `app/api/clients.py`, `app/schemas/registry.py`, `app/storage/registry.py`.
3단계 당시에는 벡터 프로그램을 변경하지 않았습니다. 이후 WebSocket 연결 모듈을 추가했으며 아래 4단계 테스트를 참고합니다.

## 4단계 일부: WebSocket 실행 요청과 결과 반환

LLM을 거치지 않고 지정 도구를 실행하는 개발용 API입니다. 기존 `/chat`은 일반 채팅 그대로입니다.
벡터 프로그램이 HTTP 등록 후 `/api/v1/clients/{client_id}/ws`에 연결합니다.
정상 연결 중에는 전체 도구 목록을 주기적으로 재등록하지 않습니다.
15초마다 작은 heartbeat 메시지로 연결을 확인하고, 끊어진 뒤 재연결할 때만 HTTP 재등록합니다.

### 실행 준비

벡터 프로그램 환경에 `websockets` 패키지가 추가되었습니다. 해당 프로젝트에서 사용 중인 Python으로 설치하고 재시작합니다.

```powershell
Set-Location 'C:\workspace\spatial_editor_tool'
.\.venv\Scripts\python.exe -m pip install 'websockets>=15,<18'
.\.venv\Scripts\python.exe -m app.main
```

Conda 사용자는 같은 패키지를 **실제로 앱을 실행하는 환경**에 설치하세요.
백엔드는 기존 실행 명령으로 시작합니다. 백엔드·벡터 프로그램 모두 재시작해야 합니다.
벡터 프로그램 하단에 `AI: 연결됨`이 표시되어야 합니다.

### Swagger 테스트

1. `GET /api/v1/connections`에서 현재 연결된 프로그램의 `client_id`를 찾습니다.
2. `POST /api/v1/clients/{client_id}/tools/call`을 펼쳐 해당 ID와 아래 본문을 입력합니다.

```json
{
  "tool_name": "get_layer_list",
  "arguments": {},
  "timeout_seconds": 15
}
```

응답의 `status: succeeded`, `result.layers`에서 래스터·벡터 레이어 메타데이터를 확인합니다.
레이어가 없으면 빈 목록이 정상입니다. 조회 시점의 index는 영구 피처 ID가 아닙니다.
레이어 버퍼·영상·전체 피처를 전송하지 않으며 최대 1000개 레이어를 반환합니다.

Photoshop을 실행한 상태에서 다음 요청으로 MCP 경로를 테스트합니다.

```json
{
  "tool_name": "photoshop_ping",
  "arguments": {},
  "timeout_seconds": 60
}
```

`status: succeeded`, `result.connected: true`가 정상 연결 확인입니다.
Photoshop 미실행·MCP 오류는 `status: failed`와 `error`로 반환될 수 있습니다.
현재 연결한 실제 실행기는 **get_layer_list와 photoshop_ping만** 허용합니다.
앞서 예시로 등록했던 photoshop_open_image는 아직 실행기를 제공하지 않으므로 벡터 프로그램의 실제 목록에서 제외했습니다.

### 오류·연결 복구

- `503 client_offline`: 등록 정보는 있으나 WebSocket 연결 없음
- `409 client_busy`: 같은 프로그램의 이전 요청 결과를 기다리는 중
- `404 tool_not_registered`, `422 invalid_arguments`: 도구·인자 검증 오류
- `504 execution_timeout`: 대기 시간 초과. 실행 완료 여부는 불명확하며 취소나 재실행을 의미하지 않음
- `503 client_disconnected` 또는 `delivery_failed`: 결과 불명확. 자동 재전송하지 않음
- HTTP 200의 `status: failed`: 프로그램에서 실행을 시도했거나 거부한 결과; `error` 확인

클라이언트는 실행 중인 도구가 끝나기 전 다른 도구 요청을 거부합니다.
타임아웃 후 도착한 결과는 다른 호출에 적용하지 않습니다.
`call_id`는 서버가 생성하며, 같은 실행 세션 내 중복 수신은 최근 256개 결과 캐시·진행 중 ID로 재실행을 막습니다.
이 캐시와 대기 중인 작업은 메모리에만 있으며 프로그램 재시작을 넘는 exactly-once 실행을 보장하지 않습니다.
연결이 끊겨도 작업을 자동 재전송하지 않습니다. 서버 재시작 후에는 대기 요청도 유지하지 않습니다.

같은 ID로 두 프로그램이 동시에 연결하면 두 번째 WebSocket은 4409로 거부됩니다.
미등록 프로그램은 4404로 거부됩니다. 메시지 규격 오류는 1008, 과대 메시지는 1009로 닫습니다.
서버는 클라이언트 메시지를 45초간 받지 못하면 연결을 종료하며, 클라이언트는 40초 동안 heartbeat 응답이 없으면 재연결합니다.
벡터 프로그램은 재연결 시 서버 URL을 기준으로 ws/wss를 자동 구성합니다.
실행 요청 만료 시각 검사를 위해 각 PC와 서버의 시스템 시간을 동기화해야 합니다.
이전 `AI_BACKEND_REFRESH_SECONDS`는 더 이상 사용하지 않습니다.

### 메시지 규격 v1

서버 준비: `{"type":"ready","protocol_version":1,"connection_id":"..."}`

서버 → 프로그램:

```json
{"type":"tool_call","call_id":"서버가 생성한 32자리 ID","tool_name":"get_layer_list","arguments":{},"expires_at":1800000000.0}
```

프로그램 → 서버:

```json
{"type":"tool_result","call_id":"동일한 ID","status":"succeeded","result":{"layers":[],"count":0}}
```

실패 시 `status: failed`, `error: 설명`을 사용합니다.
heartbeat는 `{"type":"heartbeat"}` / `{"type":"heartbeat_ack"}`입니다.
Swagger는 WebSocket 자체 입력 UI를 제공하지 않으므로 **POST 실행 테스트 API**를 통해 테스트합니다.

현재 연결·실행 관리는 프로세스 메모리 기반이므로 **Uvicorn 단일 worker**로 실행해야 합니다.
인증과 소유권 검사는 아직 없어 로컬 개발 전용입니다. 중앙 배포 전에 해당 기능을 추가해야 합니다.
추가 모듈: `app/api/execution.py`, `app/execution/connections.py`, `app/schemas/execution.py`.

## 자연어 도구 선택 테스트 (채팅 UI 추가 전)

일반 `/api/v1/chat`은 기존처럼 도구를 실행하지 않습니다.
새 **POST `/api/v1/agent/chat`**에서 LLM이 도구를 선택하고, 연결된 벡터 프로그램에서 실행한 결과를 설명합니다.
기존 직접 실행 API도 유지합니다. 벡터 프로그램 코드 변경은 이번 기능에 필요하지 않습니다.

### 준비와 모델 선택

1. Ollama, 백엔드, 벡터 프로그램을 실행합니다.
2. 벡터 프로그램의 `AI: 연결됨`과 `/api/v1/connections`의 client_id를 확인합니다.
3. `/api/v1/ollama/status`에서 현재 `.env`의 모델이 설치되어 있는지 확인합니다.

설치되어 있는 `qwen2.5:0.5b`는 연결 확인용으로는 동작하지만, 실제 한국어 테스트에서 도구 선택 오류가 관찰되었습니다.
Tool Calling의 지원 표시와 실제 선택 품질은 다릅니다. 도구 선택 검증에는 `qwen3:4b`를 후보로 권장합니다.
이 모델의 6GB GPU·Photoshop 동시 실행 성능은 별도 실측해야 합니다. 모델을 자동 다운로드하거나 `.env`를 덮어쓰지 않습니다.

```powershell
ollama pull qwen3:4b
ollama list
```

백엔드 `.env`에서 다음 값을 변경하고 서버를 재시작합니다.

```dotenv
LLM_SERVER_OLLAMA_MODEL=qwen3:4b
LLM_SERVER_OLLAMA_NUM_CTX=4096
LLM_SERVER_OLLAMA_NUM_PREDICT=512
LLM_SERVER_AGENT_TIMEOUT_SECONDS=240
```

에이전트 모델 요청은 비스트리밍, think=false, temperature=0으로 보냅니다.
기본 `LLM_SERVER_OLLAMA_DISABLE_THINKING=true`이며 일반 채팅에도 think=false를 적용합니다.
Qwen3에서는 최신 사용자 메시지에 공식 `/no_think` 지시를 함께 적용합니다.
입력 대화 원본을 수정하지 않으며, `<think>...</think>` 형태가 남으면 최종 답변 부분만 사용합니다.
사고 과정만 있거나 응답이 길이 제한으로 잘렸다면 정상 최종 답변으로 표시하지 않습니다.
이미 도구 결과가 있으면 이를 보존하고, 한국어로 실제 결과를 요약하면서 warning을 반환합니다.
따라서 `warning: ollama_output_truncated` 등은 LLM 답변 생성 실패이며 도구 자체의 실패와 다릅니다.
해당 옵션·도구 API를 지원하지 않는 모델이나 Ollama 버전은 오류가 발생할 수 있습니다.

### Swagger 요청 예시

http://127.0.0.1:8000/docs 의 **AI agent → POST /api/v1/agent/chat**에 입력합니다.
`client_id`는 실제 연결 목록의 값으로 교체합니다.

```json
{
  "client_id": "연결 목록의 client_id",
  "messages": [
    {"role": "user", "content": "현재 레이어 목록을 조회해서 총 개수를 알려줘."}
  ]
}
```

Photoshop 테스트는 content를 `포토샵 연결 확인해줘.`로 변경합니다.
Photoshop 연결 상태를 바꾸거나 이미지 편집을 수행하지는 않습니다.

응답 확인:

- `message.content`: LLM이 작성한 답변
- `tool_results`: 실제 도구 처리 내역·call_id·성공/실패·실제 결과
- `warning`: 도구 결과 이후 최종 답변 생성 등이 실패한 경우 표시
- `tool_results: []`: 도구를 호출하지 않고 모델이 답변한 것. 실제 앱 조회 성공으로 판단하면 안 됨
- `warning: no_tool_called`: 해당 응답에서 실제 도구 호출이 없었음을 명시

**답변 문장만으로 성공을 판단하지 말고** `tool_results`에 의도한 도구와 `status: succeeded`가 있는지 확인합니다.
모델 선택 품질은 별도 검증 대상입니다. 아래의 제한된 완료 검사를 통해 두 조회 작업의 누락을 확인합니다.

### 실행 제한과 오류 처리

- 등록된 도구 중 `get_layer_list`, `photoshop_ping`만 모델에 제공합니다.
- 현재 두 도구의 인자는 빈 객체만 허용합니다. 미등록 도구·잘못된 인자·중복 호출은 실행 전에 거부합니다.
- 한 모델 응답의 전체 호출 묶음을 검사한 뒤 순서대로 실행합니다. 각 도구는 요청당 최대 1회입니다.
- 누락 복구를 포함해 최대 4회 모델 응답, 최대 2개 도구 실행으로 제한합니다.
- 연결된 PC가 대화 도중 바뀌면 추가 실행하지 않습니다. 연결 끊김·타임아웃·실패 시 자동 재실행하지 않습니다.
- 프로그램별 AI 요청은 하나만 진행합니다. 중복 요청은 `409 agent_busy`입니다.
- 도구 실패 후 남은 도구는 실행하지 않고, 실패 사실을 답변에 반영하도록 모델에 전달합니다.
- 잘못된 모델 호출은 `502 invalid_tool_call`, 일반 공급자 오류는 기존 Ollama 오류 형식입니다.
- 도구 결과를 이미 받은 뒤 최종 LLM 응답이 실패하면 HTTP 200에 실제 `tool_results`와 `warning`을 보존합니다.
- 전체 요청 제한은 `LLM_SERVER_AGENT_TIMEOUT_SECONDS`(기본 240초)이며 시간 초과가 원격 작업 취소를 보장하지 않습니다.

서버에 대화를 저장하지 않습니다. 후속 질문은 이전 user/assistant 대화와 새 질문을 messages에 함께 보내야 합니다.
도구의 원본 결과는 응답에 포함하되, 모델에는 레이어 이름·종류·표시 여부의 앞 30개와 총 개수 등 제한된 정보만 보냅니다.
레이어 정보는 조회 시점의 데이터입니다. 편집·선택 영역 분석·산림 합성 도구는 아직 연결하지 않았습니다.

추가 모듈: `app/agent/runner.py`, `app/api/agent.py`, `app/schemas/agent.py`.
검증 테스트는 모의 모델과 실제 WebSocket을 사용하여 호출·실행·최종 답변과 실패 처리를 확인합니다.
로컬 0.5B 모델 실측은 연결·호출 형식을 확인한 것이며 자동화 품질을 보증하지 않습니다.

### 복합 요청의 완료 검사

`현재 레이어 목록과 포토샵 연결 상태를 알려줘`와 같은 요청에서 하나만 실행한 뒤 끝나는 문제를 보완했습니다.
현재 두 도구에 한해 최신 사용자 문장의 레이어 조회·Photoshop 확인 표현을 검사하여 `requested_tools`를 구성합니다.
이는 지원하는 명확한 조회 표현을 다루는 제한된 검사이며, 일반적인 자연어 계획 전체를 검증하는 기능은 아닙니다.
도구 선택과 실제 호출은 계속 LLM이 담당하며 서버가 누락된 도구를 임의로 직접 실행하지 않습니다.

- 모델이 답변으로 종료하려는데 미실행 작업이 있으면 남은 도구만 제시해 **한 번** 선택을 다시 요청합니다.
- 이미 실행한 도구는 반복하지 않습니다. 실패한 작업을 자동 재시도하지 않습니다.
- `포토샵은 확인하지 말고 레이어 목록만 알려줘`처럼 도구 뒤에 명시된 제외 표현은 실행 제한에도 반영합니다.
- 보완 요청도 무시하면 누락을 그대로 표시합니다. 요청 이해가 불확실한 표현까지 완전 수행을 보장하지 않습니다.
- 현재 지원하는 조회 작업의 사용자 표시 문장은 서버가 실제 결과로 구성합니다. 모델의 허위 성공 문장은 사용하지 않습니다.
- 식별한 조회 도구가 모두 실행되면 결과로 즉시 응답하며, 답변 문장 생성을 위한 추가 LLM 호출은 하지 않습니다. 도구 실행 실패 시에도 실제 결과와 미완료 항목을 바로 반환합니다.
- 전체 레이어 목록은 계속 `tool_results[].result.layers`에서 확인합니다.

추가 응답 필드:

| 필드 | 의미 |
|---|---|
| `requested_tools` | 최신 요청에서 식별한 지원 도구 목록 |
| `missing_tools` | 식별한 요청 중 성공 결과가 없는 도구 목록 |
| `completion_status: completed` | 식별한 요청 모두 성공 결과 수신 |
| `completion_status: partial` | 일부만 성공 |
| `completion_status: failed` | 식별한 요청의 성공 결과 없음 |
| `completion_status: unverified` | 제한된 검사로 요청 범위를 식별하지 못함; 전체 완료를 보증하지 않음 |

일부 완료 시 예:

```json
{
  "message": {"role": "assistant", "content": "현재 레이어는 총 92개입니다. 미완료: 포토샵 연결 확인."},
  "requested_tools": ["get_layer_list", "photoshop_ping"],
  "missing_tools": ["photoshop_ping"],
  "completion_status": "partial",
  "warning": "partial_completion"
}
```

별도 공급자 오류가 발생하면 warning에는 그 오류 코드가 우선 표시되며, 완료 상태·실제 실행 내역은 보존됩니다.
회귀 테스트에는 누락 복구 성공, 복구 무시 시 부분 완료, 허위 Photoshop 성공 문장 제거, 제외 도구 실행 차단을 포함합니다.

연속 요청은 같은 프로그램에서 한 번에 하나만 처리합니다. 처리 중 중복 요청은 `409 agent_busy`로 거절하며, 완료·시간 초과 후 잠금은 해제됩니다. 정상 완료 및 모델 시간 초과 후 후속 질문, 겹친 요청 거절 후 재요청을 회귀 테스트합니다.

최신 문장만으로 식별되는 레이어 조회·Photoshop 연결 확인은 도구 선택 시 이전 대화의 성공 문장을 제외합니다. 인자가 없는 두 조회 도구에 한정된 처리이며, 이전 답변을 현재 상태로 오인하는 소형 모델의 연속 질문 문제를 줄입니다. 채팅창의 대화 기록은 유지하며, 요청 범위를 식별하지 못하는 일반 대화는 기존처럼 이력을 전달합니다.

Uvicorn 콘솔의 `Agent start/end`, `Agent tool start/end`, `Ollama acquired/response/timeout` 로그로 요청·도구 소요 시간과 모델 대기 시간을 구분할 수 있습니다. Ollama 시간 초과의 `phase=queue`는 서버 내 순서 대기, `phase=generation`은 Ollama HTTP 응답 대기입니다. 질문 본문과 레이어 경로는 이 로그에 기록하지 않습니다. 서버의 HTTP 대기가 끝나도 Ollama 내부 생성의 즉시 종료까지 보장하지는 않습니다.
