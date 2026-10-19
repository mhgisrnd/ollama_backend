# Spatial LLM Server

## AI 요청 중지

채팅 처리 중에는 전송 버튼이 **중지**로 바뀝니다. 클라이언트와 서버를 모두 업데이트·재시작해야 합니다. 개발 서버에도 변경 소스를 반영하고 FastAPI를 재시작하세요.

채팅 POST에 클라이언트가 생성한 `request_token`(32자리 소문자 hex)을 보내며, `POST /api/v1/agent/cancel`에 동일한 `client_id`와 `request_token`을 보내 중지합니다. 서버는 해당 요청의 LLM 대기와 후속 도구 호출을 취소하고 실행 잠금을 해제합니다. 이미 벡터 프로그램·Photoshop에 전달된 작업은 계속될 수 있으며 되돌리지 않습니다. Ollama 내부 계산이 즉시 종료되는 것은 보장하지 않습니다. 중지한 요청을 자동 재전송하지 않습니다.

중지 뒤 늦게 도착한 응답은 채팅에 반영하지 않으며, 조회 문맥과 번호 식별자를 초기화하므로 번호로 열기 전에는 목록을 다시 조회해야 합니다. 중지 서버 응답은 최대 8초 기다리고, 확인에 실패하면 이를 표시합니다. 이 경우 서버 작업이 계속될 수 있습니다.

## Photoshop 문서 조회·이미지 열기 (`general` 모드)

### 조회 목록 번호로 선택

서버·벡터 프로그램을 모두 재시작하고 새 대화에서 먼저 `현재 레이어 목록 알려줘`를 실행한 뒤 `1,2,4,5,6번 파일 열어줘`처럼 요청할 수 있습니다. 번호는 **가장 최근 채팅 조회 목록의 번호 열** 기준이며 왼쪽 레이어 패널의 순번과 다를 수 있습니다. 없는 번호나 비이미지 레이어가 섞이면 전체 선택을 열지 않습니다. 번호를 이미지 필터로 다시 매기지 않습니다. 중복 번호는 한 번만 선택하며 최대 5개 제한은 유지합니다.

번호는 서버가 저장한 목록 스냅샷의 행에 공통 `select_positions` 연산으로 연결합니다. 응답의 `query_result.reference_id`를 클라이언트가 다음 요청의 `reference_id`로 보내고 서버와 일치할 때만 실행합니다. 타임아웃으로 받지 못한 새 목록이 번호를 다른 파일로 바꾸는 상황을 방지합니다. Swagger에서는 같은 `session_id`와 마지막으로 받은 `reference_id`가 필요합니다. 새 대화·프로젝트 변경·서버 재시작·재연결 이후에는 목록을 다시 조회하세요. 전체 열기가 개수 제한에 걸린 경우에도 선택할 이미지의 번호 목록을 상세 표로 제공합니다.

```powershell
.\.venv\Scripts\python.exe -m app.experiments.evaluate_numbered_images --report data/evaluations/numbered_images_latest.json
```

실제 Ollama + 모의 목록에서 번호 생성, 비연속 5개 선택, 비이미지 번호 거절, 범위 초과 번호 거절을 검증했습니다. 개발 사례 4/5 통과이며, 0번 요청은 작업 없이 거절했으나 구체적인 번호 범위 대신 일반 안내를 반환했습니다. 모든 표현의 정확도 보장은 아닙니다. 이 평가에서 사용자 프로젝트 파일을 열지 않았습니다. 자동 테스트는 백엔드 95개, 클라이언트 관련 36개 통과했습니다.

‘활성화’가 레이어 표시 체크를 뜻한다면 `표시된 TIFF 중 첫 번째 하나를 포토샵에 열어줘`처럼 표현할 수 있습니다. 선택된 객체·레이어와 표시 여부는 별개이며 선택 상태는 아직 연결하지 않았습니다.

벡터 프로그램의 Photoshop MCP에 다음 도구를 연결했습니다. 서버와 벡터 프로그램을 **둘 다 재시작**하면 새 도구 목록이 등록됩니다. 설정은 `LLM_SERVER_AGENT_MODE=general`을 사용합니다.

- `photoshop_list_documents`: 열린 문서 목록
- `photoshop_get_document_info`: 활성 문서 이름·픽셀 크기
- `photoshop_get_layers`: 활성 문서 내부의 레이어 목록
- `photoshop_open_images`: 현재 프로젝트의 이미지 레이어를 새 작업 문서로 열기

채팅의 ‘질문 예시’에도 추가했습니다. 처음에는 이미지 하나로 확인하세요.

```text
포토샵에 열려 있는 문서 목록 알려줘.
포토샵 활성 문서 이름과 크기를 알려줘.
포토샵 문서의 레이어 목록 알려줘.
현재 목록의 이미지 중 첫 번째 하나를 포토샵에 열어줘.
```

이미지 열기는 TIFF뿐 아니라 JPEG·PNG·BMP·GIF·PSD·PSB·TGA·WebP·JPEG2000 확장자를 후보로 받으며, 실제 지원은 설치된 Photoshop과 파일 상태에 따라 달라집니다. 서버가 레이어 목록에서 실제 경로를 선택하고, 클라이언트가 **현재 프로젝트의 raster 레이어 경로인지 다시 검증**합니다. 임의 파일 경로나 모델 생성 스크립트는 실행하지 않습니다.

한 번에 최대 **5개**, 순차 실행입니다. 초과 요청은 일부만 몰래 열지 않고 대상을 좁히도록 안내합니다. 동일 이미지의 반복 요청도 새 작업 문서를 생성합니다. 원본 파일을 저장하거나 이미 열려 있던 문서를 닫지 않습니다. 파일을 새로 읽기 위해 내부적으로 연 원본 문서만 복제 후 저장 없이 닫습니다. 새 작업 탭 이름에는 `AI`와 실행 식별자가 붙습니다.

개수 제한은 실행 정책이며 사용자가 요청한 개수와 구분합니다. 전체 요청인데 모델 계획이 `limit=5`로 줄어든 경우, 전체 매칭 개수와 선택 개수를 비교해 실행을 막는 검증을 추가했습니다. 이 경로는 모의 WebSocket 회귀 테스트로 확인했습니다. 실제 Ollama의 ‘첫 번째 하나 열기’는 통과했지만 12개 전체 열기 검증에서는 분류·검토 단계가 먼저 실패하여, 아직 정확한 상한 안내까지 일관되게 도달하지 못합니다. 모델 해석 정확도가 해결됐다고 간주하지 않습니다. 이미지 열기의 내부 레이어 스냅샷은 채팅에 긴 목록으로 중복 표시하지 않습니다.

이미지 열기의 서버 대기는 최대 **180초**, 고정 Photoshop 스크립트는 최대 150초입니다. 타임아웃은 포토샵 작업 중단을 보장하지 않으므로 자동 재전송하지 않습니다. 앱 편집 기능은 응답을 기다리는 동안에도 사용할 수 있습니다. 채팅에는 움직이는 로딩 막대와 경과 시간이 표시됩니다. 일부 열기 실패는 전체 성공으로 표시하지 않습니다.

검증: 백엔드 자동 테스트 **90개**, 클라이언트 관련 **35개** 통과. 실제 Ollama + 모의 데스크톱에서 신규 질문 4개 통과. 실제 Photoshop에서는 임시 1×1 PNG를 두 번 열어 서로 다른 작업 문서 ID를 확인하고 문서·크기·레이어 조회까지 검증했습니다. 테스트 문서만 닫고 임시 파일을 삭제했으며, 사용자 프로젝트 이미지나 대용량 영상은 열지 않았습니다. 대용량·다른 이미지 형식의 실제 호환성은 별도 확인이 필요합니다.

```powershell
.\.venv\Scripts\python.exe -m app.experiments.evaluate_general_agent --model qwen3:4b-instruct --report data/evaluations/photoshop_tools_fixed.json --diagnostic-log data/evaluations/photoshop_tools_fixed.log --case-index 17 --case-index 18 --case-index 19 --case-index 20
```

기존 Python 벡터 프로그램과 독립적으로 실행하는 Python/FastAPI AI 백엔드입니다.
현재는 **LLM 도구 선택 → WebSocket 실행 → 결과를 반영한 답변 생성**까지 구현했습니다. 별도 벡터 프로그램 프로젝트에는 도킹·분리 가능한 채팅 UI를 연결했습니다.

## 현재 범위

- FastAPI 앱과 `/api/v1` API 경로
- 서버 생존 확인 API, Swagger API 문서, OpenAPI 명세
- 환경변수 및 `.env` 설정
- 독립 가상환경, 의존성 잠금 파일, 기본 검증 테스트

Ollama 연결 확인, 비스트리밍 채팅, 프로그램별 도구 목록 등록·조회·형식 검증을 제공합니다.
WebSocket으로 연결된 벡터 프로그램의 레이어 조회·Photoshop ping을 직접 테스트할 수 있습니다.
읽기 전용 레이어 조건 조회와 Photoshop 통신 확인을 제공합니다. 영상 편집 자동화, 사용자 인증·세션 영구 저장은 아직 구현하지 않았습니다.
백엔드는 기존 `C:\workspace\spatial_editor_tool`의 실행 환경에 의존하지 않습니다. 채팅 UI와 실행 클라이언트는 해당 별도 프로젝트에 구현합니다.
별도 웹 UI는 만들지 않으며 `/docs`는 개발용 API 문서입니다.

## 현재 채팅 방식: 3B 구조화 조회

범용 조회 엔진은 별도의 `general` 모드로 추가했습니다. 아래 `structured` 기본 채팅은 이전 구현이며, 범용 모드는 모델의 의도 해석 정확도가 아직 기준에 미달해 기본값으로 전환하지 않았습니다. 상세 설계와 검증은 다음 절을 참고하세요.

기본 설정은 `LLM_SERVER_OLLAMA_MODEL=qwen2.5:3b`, `LLM_SERVER_AGENT_MODE=structured`입니다. 모델은 기능 선택과 JSON 조회 조건 생성만 담당하고, 필터링·개수 계산·최종 상태 문장은 Python이 처리합니다. 기존 방식은 `AGENT_MODE=native`로 선택할 수 있습니다.

- `현재 레이어 목록 알려줘` → 최신 전체 조회
- `그중 tif는 몇 개야?` → 직전 결과에서 TIFF 개수 계산
- `그중 숨겨진 것만 이름을 보여줘` → 직전 결과에 숨김 조건 적용
- `전체 레이어에서 shp만 이름을 알려줘. 표시 여부는 상관없어.` → 최신 전체 대상에서 조건 변경
- `조건을 초기화하고 지금 전체 레이어 목록을 다시 확인해줘` → 새 조회
- `레이어 목록과 포토샵 연결 상태 알려줘` → 두 기능의 실제 결과 반환

조건은 현재 TIFF(`.tif`·`.tiff`), SHP(`.shp`), 표시 여부, 개수·목록을 지원합니다. 모든 자연어 표현의 정확성을 보장하지는 않습니다. 명시적인 개수·숨김 조건과 충돌하는 계획은 실행 전에 한 번 보정하며, 보정 실패 시 실행하지 않습니다. 질문 표현별 실행 코드를 추가하는 방식은 아닙니다.

POST `/api/v1/agent/chat`에는 기존 `client_id`, `messages`에 더해 선택적인 `session_id`가 있습니다. 같은 대화는 같은 ID, 새 대화는 새 ID를 사용합니다. 벡터 UI가 자동 관리합니다. `session_id` 생략 시 단일 요청이며 후속 조회 결과를 보관하지 않습니다.

세션은 프로그램별로 격리하고 최대 128개, 유효 기간 30분으로 메모리에만 보관합니다. 서버 재시작·프로그램 연결 변경 시 이전 결과를 재사용하지 않습니다. UI의 새 대화·프로젝트 경로 변경도 조회 맥락을 초기화합니다. 직전 결과는 조회 시점 스냅샷이며 실제 레이어가 바뀌면 현재 상태를 다시 조회해야 합니다.

조건 결과는 `query_result`에, 실제 실행 내역은 `tool_results`에 반환합니다. `query_layers`는 서버의 내부 계산 도구이며, 현재 데이터가 필요할 때만 기존 클라이언트 `get_layer_list`를 호출합니다. 클라이언트 MCP 도구 목록을 바꿀 필요는 없습니다. 일부 데이터만 수신하면 전체 개수를 추측하지 않습니다. 개수 응답에는 전체 목록을 표시하지 않습니다.

모듈: `app/agent/structured.py`(계획·세션·실행), `app/agent/layer_query.py`(스키마·계산), `app/llm/ollama.py`(모델 어댑터). 기능 확장 시 입력 명세·검증·실행기·응답 처리를 함께 추가합니다. 임의 코드 실행은 지원하지 않습니다.

반영 후 백엔드와 벡터 프로그램을 모두 재실행하세요. Ollama가 실행 중이고 모델이 설치되어 있어야 합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 실제 Ollama + 운영 에이전트 + 합성 데스크톱 데이터 검증 (벡터/포토샵 수정 없음)
.\.venv\Scripts\python.exe -m app.experiments.evaluate_structured_agent
```

2026-10-16 최종 연결 로직은 합성 데이터의 후속 질문 10개와 첫 질문 복합 조회 3개, 총 13/13을 통과했습니다. 예열된 모델과 Python 계산은 단일 조회 약 0.4~1.3초, 복합 조회 약 1.5~2초였습니다. 실제 GUI·배포 GPU 성능이나 모든 질문에 대한 정확도 보장은 아닙니다. 자동 검증은 백엔드 57개, 벡터 UI·연결 관련 31개가 통과했습니다.

`현재 레이어 목록은 어떻고 그중 tif는 몇개인지 알려줘`처럼 목록과 개수를 한 번에 요청할 수도 있습니다. 여러 출력이 필요한 요청은 LLM이 최대 3개의 작은 조회 질문으로 나누고, 기존 단일 조회 계획 생성기를 재사용합니다. 전체 계획 검증 후 순서대로 실행하므로 첫 질문 안의 `그중`도 앞 단계 결과를 대상으로 처리할 수 있습니다. 단독 `그중 tif는 몇 개야?`에 이전 결과가 없을 때는 임의로 새 전체 조회를 만들지 않습니다.

같은 요청의 최신 조회 단계들은 한 번 수신한 동일 스냅샷을 공유합니다. 첫 단계가 무조건 전체 목록일 때 두 번째 단계의 `current`와 `previous_result`는 이 스냅샷에서 같은 집합을 가리키므로 복합 조회 검증은 결과·전체 목록·실제 원격 조회 1회 여부로 판정합니다. 필터된 첫 결과를 대상으로 하는 일반 후속 질문은 계속 `previous_result`를 검증합니다. 여러 목록이 있으면 UI에서 각각 별도 목록 링크로 표시합니다.

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

현재 로컬 `.env`의 모델은 `qwen2.5:3b`입니다. 초기 연결 검증에는 `qwen2.5:0.5b`를 사용했으며 조건 조회에서 정확도가 부족했습니다.
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

현재 사용 모델을 설치하려면:

```powershell
ollama pull qwen2.5:3b
```

다운로드 후 `.env`의 모델 값을 `qwen2.5:3b`로 설정하고 FastAPI를 재시작합니다.
모델 다운로드 크기와 실제 VRAM 사용량은 다르며, Photoshop과 함께 실행하는 자원 검증은 별도입니다.

### 백엔드 환경 설정

```dotenv
LLM_SERVER_OLLAMA_BASE_URL=http://127.0.0.1:11434
LLM_SERVER_OLLAMA_MODEL=qwen2.5:3b
LLM_SERVER_AGENT_MODE=structured
LLM_SERVER_OLLAMA_TIMEOUT_SECONDS=120
LLM_SERVER_OLLAMA_NUM_CTX=4096
LLM_SERVER_OLLAMA_NUM_PREDICT=512
LLM_SERVER_OLLAMA_KEEP_ALIVE=5m
```

| 설정 | 의미 |
|---|---|
| `OLLAMA_BASE_URL` | `LLM_SERVER_` 접두사를 붙여 사용. Ollama 주소이며 `/api`는 붙이지 않음 |
| `OLLAMA_MODEL` | `ollama list`에 나오는 모델 이름. 기본값은 `qwen2.5:3b` |
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
일반 `/chat`은 대화를 저장하지 않습니다. WebSocket 실행과 에이전트 도구 호출은 아래 별도 API에서 제공합니다. 인증·세션 영구 저장·영속 작업 큐·스트리밍은 이후 단계입니다.
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
Tool Calling의 지원 표시와 실제 선택 품질은 다릅니다. 현재 기본은 위의 3B 구조화 방식이며, 아래 설명은 이전 native 방식의 참고입니다.
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

native 모드는 서버에 대화를 저장하지 않습니다. native 후속 질문은 이전 user/assistant 대화와 새 질문을 messages에 함께 보내야 합니다. structured 모드는 위의 session_id 방식으로 조회 결과를 보관합니다.
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

### 조건 조회·후속 질문 검증 (기존 채팅에 미적용)

`app/experiments/`는 범용 레이어 조회와 세션 맥락의 실험 모듈입니다. FastAPI 라우터나 벡터 프로그램에 연결하지 않았습니다. 기존 채팅·Photoshop MCP·서버 모델 설정을 변경하지 않습니다.

- `layer_query.py`: 엄격한 입력 스키마, Python 필터링·개수 계산, 세션별 직전 결과 보관. count 응답에서도 후속 필터링용 원본 행을 유지합니다.
- `evaluate_layer_query.py`: 현재 Ollama 모델의 도구 인자 선택 및 JSON 스키마 출력 방식 비교. 모델 답변을 정답으로 간주하지 않고 별도의 기대 결과와 비교합니다.
- 알려진 TIFF·SHP·GeoJSON 6개를 사용합니다. 전체 목록 → 그중 TIFF 개수 → 그중 숨김 이름 → 전체에서 SHP → 조건 초기화·재조회, 5개 질문을 반복합니다. 마지막 조회에서는 테스트 데이터를 하나 추가해 이전 결과 재사용과 새 조회를 구분합니다.
- `--context reference`는 올바른 이전 상태를 제공해 앞선 실패의 전파와 현재 질문 자체의 해석 오류를 구분합니다. 기대 정답은 모델에 전달하지 않습니다. 이전 정답 맥락만 전달합니다.

Ollama를 실행한 상태에서 프로젝트 루트에서 실행합니다. 벡터 프로그램 없이 실행할 수 있습니다.

```powershell
# 기본 Tool Calling, 실제 모델 응답을 다음 질문의 맥락으로 사용
.\.venv\Scripts\python.exe -m app.experiments.evaluate_layer_query --repeat 2

# 올바른 이전 맥락을 제공한 Tool Calling
.\.venv\Scripts\python.exe -m app.experiments.evaluate_layer_query --context reference --report data/evaluations/layer_query_reference.json

# JSON 스키마 출력 강제 방식 비교
.\.venv\Scripts\python.exe -m app.experiments.evaluate_layer_query --mode structured-json --report data/evaluations/layer_query_structured.json
.\.venv\Scripts\python.exe -m app.experiments.evaluate_layer_query --mode structured-json --context reference --report data/evaluations/layer_query_structured_reference.json
```

`--model <ollama에 설치된 모델명>`으로 실험 모델만 바꿀 수 있습니다. 모델을 자동 다운로드하지 않습니다. 결과 JSON은 Git에서 제외된 `data/evaluations/`에 저장됩니다.

선택적으로 `--backend-url http://127.0.0.1:8000 --client-id <연결된_ID>`를 붙이면 기존 읽기 전용 도구로 실제 레이어 스냅샷을 한 번 가져옵니다. 그 이후는 스냅샷에서 로컬 계산만 합니다. 이 모드는 최신 상태 재조회·실시간 편집 반영 검증이 아니며 보고서에 이 제한을 표시합니다. 실제 경로는 모델이나 보고서에 전달하지 않습니다.

2026-10-16 검증 결과 (`qwen2.5:0.5b`, 최종 프롬프트, 합성 데이터):

| 방식 | 실제 이전 응답 사용 | 올바른 이전 맥락 제공 |
|---|---:|---:|
| Tool Calling | 0/10 | 0/10 |
| JSON 스키마 강제 | 0/10 | 0/10 |

Tool Calling에서는 필수 인자 누락·호출 생략, JSON 방식에서는 질문과 다른 확장자·표시 여부·조회 대상 선택이 반복됐습니다. 초기 JSON 프롬프트에서는 4/10이었으나 설명 변경 후 0/10이 되어 프롬프트 민감성도 확인했습니다. 이 작은 고정 시나리오는 모델 전체 성능 점수가 아니며 temperature=0 반복은 독립적인 정확도 표본이 아닙니다. 현재 구성으로 실사용하기에는 부족하다는 근거입니다. 다른 모델도 동일 조건으로 비교한 후 적용해야 합니다.

Python 실행기 회귀 테스트 8개(정확한 계산·후속 조회·신규 조회·세션 격리·잘못된 인자 거절)는 통과했습니다. 모델의 의미 해석 실패를 자동 교정하거나 성공으로 처리하지 않습니다. 현 실험은 레이어 조회 하나에 한정되며 일반 도구 선택·편집 자동화 검증을 포함하지 않습니다.

동일 코드·질문으로 `qwen2.5:3b`를 비교한 결과:

| 방식 | 실제 이전 응답 사용 | 올바른 이전 맥락 제공 |
|---|---:|---:|
| Tool Calling | 0/10 | 3/10 |
| JSON 스키마 강제 | 8/10 | 9/10 |

3B의 JSON 방식은 전체 조회, TIFF 개수, 전체에서 SHP 조회, 조건 초기화를 처리했지만 `그중 숨겨진 것만 이름을 보여줘`에서 직전 결과·숨김 조건을 누락했습니다. 예열된 JSON 방식의 모델 응답은 약 0.4~0.7초였고 전체 성공률로 일반화할 수 없는 작은 테스트입니다. 이 시간은 합성 데이터의 계획 생성 시간이며, 벡터 프로그램 통신·Photoshop 실행·배포 대상 GTX 1660의 실측 시간이 아닙니다.

비교 명령 예시:

```powershell
.\.venv\Scripts\python.exe -m app.experiments.evaluate_layer_query --model qwen2.5:3b --repeat 2 --report data/evaluations/layer_query_3b.json
.\.venv\Scripts\python.exe -m app.experiments.evaluate_layer_query --model qwen2.5:3b --mode structured-json --repeat 2 --report data/evaluations/layer_query_3b_structured.json
```

결론: 모델 크기에 따른 개선이 관찰되지만 모델만 변경하면 해결되는 것은 아닙니다. JSON 계획 검증·세션 맥락 전달 방식과 함께 보완하고 더 넓은 질문 세트에서 검증한 뒤 기존 채팅에 연결해야 합니다. 서버 `.env`와 기존 API에는 아직 적용하지 않았습니다.

## 범용 조회 설계 (`general`, 개발 검증 모드)

질문 문장별 예외 분기 대신 데이터 필드·공통 연산·실행 어댑터를 조합합니다. `general.py`는 질문 키워드용 정규식, `request_scope`, 문장별 count/hidden 보정 규칙을 사용하지 않습니다. 기존 `structured`/`native` 모드는 이전 동작 비교용으로 남겨 두었습니다.

```text
사용자 원문 + 세션 맥락 + 사용 가능한 도구·필드 명세
→ LLM 작업 계획(최대 3개)
→ 필터·정렬·집계 JSON 질의 생성
→ Python 자료형·필드·연산 검증 + LLM 원문 의도 검토
→ 필요하면 계획을 1회 수정, 불명확·미지원이면 실행 중단
→ 읽기 전용 데이터 수집 → Python 계산 → 실제 값으로 답변
```

LLM의 의도 검토는 의미 해석의 수학적 보증이 아닙니다. JSON 형식이 맞더라도 질문의 의미를 놓칠 수 있으므로 별도 평가가 필요합니다. 원문을 계획·검토 단계까지 보존하고 하위 질문 요약이 조건을 누락하지 않게 합니다. 질의가 미지원 필드를 명시하면 Python이 거절합니다. 미지원 개념을 모델이 다른 필드로 바꿔 쓰는 오류는 모델 검토·실측 평가의 대상입니다.

### 공통 질의 언어

`app/agent/query_engine.py`가 필드와 연산의 단일 실행 경계입니다.

| 구성 | 지원 내용 |
|---|---|
| 필드 | name, extension, kind, visible, path, size_bytes, modified_at |
| 필터 | eq/in(값 중 하나), ne(값 모두 제외), contains, gt/ge/lt/le; 필터 사이는 AND |
| 정렬·제한 | 다중 필드 asc/desc, 상위 N개(limit 최대 1000) |
| 집계 | count(* 또는 비어 있지 않은 필드), sum/avg/min/max |
| 그룹 | group_by 한 필드; 집계 결과 group/value로 정렬 가능 |
| 맥락 | current 또는 previous_result; 서버 메모리 세션에 결과 행과 질의 보관 |

예: TIFF 중 가장 큰 파일은 `extension in [.tif,.tiff] → size_bytes desc → limit 1 → name,size_bytes 선택`입니다. 이 경우의 질문 문장을 판별하는 Python 코드는 없습니다. 같은 엔진으로 상위 5개, 숨김 조건의 총용량, 종류별 개수 등을 조합합니다. 임의 Python·SQL·쉘 코드는 실행하지 않습니다. 미지원 필드/연산은 가까운 기능으로 대체하지 않고 거절합니다.

숫자 비교 값에는 `100 MB`, `1 GiB` 등 명시 단위를 사용할 수 있습니다(MB=10^6, MiB=2^20 바이트). modified_at은 현재 Unix 초입니다. 해상도·좌표계·영상 내용은 현재 제공 필드가 아닙니다. 새 데이터 능력은 필드 명세와 수집 어댑터, 새 연산은 실행기를 확장합니다. 질문 표현마다 실행 분기를 늘리지 않습니다.

집계는 필터된 전체 행에서 계산하며 limit는 반환 행 수를 제한합니다. 일반 목록의 후속 질문은 실제 반환된 상위 N개를, 집계의 후속 질문은 집계에 사용된 행을 대상으로 합니다. 일부 크기를 읽지 못하면 최댓값·합계를 확정하지 않습니다. null을 0으로 간주하거나 모르는 파일을 빼고 전체 최댓값이라고 답하지 않습니다.

### 파일 정보 수집과 UI

벡터 클라이언트에 `get_layer_metadata`를 추가했습니다. 인자는 `{}`이고 현재 로드된 레이어 경로만 조회합니다. GUI 스레드는 가벼운 메타데이터 복사만 하며, 파일 stat은 최대 4개 daemon 작업으로 수행합니다. 네트워크 경로가 멈춰도 요청당 약 5초 예산 후 미확인 값은 null로 반환하고 GUI/종료를 막지 않습니다. 기존에 멈춘 stat 작업이 있으면 새 작업을 무제한 만들지 않습니다.

size_bytes는 실제 파일 하나의 크기입니다. SHP의 DBF/SHX 등 부속 파일 합계는 아닙니다. 같은 파일이 여러 레이어에 있으면 레이어별 집계로 중복될 수 있습니다. 가상 레이어·접근 불가 파일은 null입니다. 숫자 정보가 필요할 때만 수집하고, 직전 결과는 경로·종류가 같은 현재 레이어 메타데이터와 결합합니다. 이전 대상이 사라졌으면 값을 추측하지 않습니다.

일반 모드 결과는 `query_result.plan`(적용 조건), `records`(선택된 열 또는 집계값), `layers`(호환 표시용)에 반환합니다. 채팅의 `조회 결과 자세히 보기`는 열을 동적으로 구성하여 파일 크기·집계 결과 등을 표시합니다. 실제 읽기 도구와 내부 계산은 `tool_results`에 따로 남깁니다. 구형 클라이언트에 파일 정보 도구가 없으면 해당 필드 요청을 거절합니다.

### 실행·평가

일반 모드는 아직 기본 활성화하지 않았습니다. 개발용으로 사용할 때만 `.env`를 다음처럼 설정하고 백엔드·벡터 프로그램을 재실행합니다.

```dotenv
LLM_SERVER_AGENT_MODE=general
LLM_SERVER_OLLAMA_MODEL=qwen3:4b-instruct
```

현재 PC에는 비교용 `qwen3:4b-instruct`를 추가 설치했습니다. 기존 모델은 유지하며 기존 `.env`의 structured/3B 설정도 유지했습니다. 일반 모드의 의미 해석 정확도가 검증되기 전 기존 채팅을 자동 교체하지 않습니다.

```powershell
# 서버·실제 파일을 수정하지 않고 실제 Ollama와 합성 메타데이터로 평가
.\.venv\Scripts\python.exe -m app.experiments.evaluate_general_agent --model qwen3:4b-instruct --report data/evaluations/general_agent_qwen3_4b_instruct.json

# 공통 엔진과 API 경계 검증
.\.venv\Scripts\python.exe -m pytest -q tests/test_query_engine.py tests/test_general_agent.py
```

크기 순위·상위 N개·합계·평균·그룹별 개수·미지원 정보·삭제 거절 등 11문항은 개발 평가 세트이며 독립된 미공개 검증 세트는 아닙니다. 점수에는 지원하지 않는 요청을 올바르게 거절한 경우도 포함됩니다. 결과를 보고 질문별 코드 예외를 추가하지 않으며, 향후 다른 표현·다른 데이터로 별도 검증해야 합니다. Ollama 응답 시간이 초과되면 평가를 중단하여 다음 요청을 무작정 쌓지 않습니다.

최종 `qwen3:4b-instruct` 개발 평가: **8/11**. 지원 조회 9개 중 6개 성공, 3개 실행 전 거절, 미지원 요청 2개 올바른 거절입니다. 가장 큰 TIFF·가장 작은 TIFF·크기 조건 조회의 일부 계획은 확정하지 못했습니다. 성공한 지원 조회는 상위 N개·개수·합계·평균·그룹·이름 조건이었습니다. 이는 범용 배포 승인 기준을 충족하지 않으며 현재 기본 전환을 보류한 이유입니다. 모델 검토가 틀린 의도를 반드시 걸러 준다는 보장도 없습니다.

Python 실행기와 연결·UI 자동 테스트는 총 **107개(백엔드 73, 벡터 관련 34)** 통과했습니다. 자동 테스트는 형식·계산·경계 처리 검증이며 자연어 이해 정확도 점수와 다릅니다. JSON 스키마는 형식 강제 인자뿐 아니라 모델 프롬프트에도 전달합니다([Ollama 공식 안내](https://docs.ollama.com/capabilities/structured-outputs)).

### 범용 모드의 누락 정보 처리

단순 목록 계획에는 필요한 기본 필드만 선택하도록 지침·검토 기준을 적용합니다. 표시용 필드가 누락되어도 레이어를 제거하지 않으며 해당 값은 JSON `null`, 채팅·상세 표에서는 `확인 불가`로 표시합니다.

필터·정렬·숫자 집계에 필요한 값이 없으면 해당 행을 연산에서 제외하고, `query_result.is_partial=true`, `excluded_count`, `warnings`로 한계를 전달합니다. 응답은 `completion_status=partial`, `warning=incomplete_data`이며, 확인된 데이터 기준의 결과라고 명시합니다. 전체가 누락된 합계는 0이 아닌 `null`입니다. 부분 결과를 대상으로 한 후속 조회에도 이전 한계를 유지합니다. 따라서 확인된 파일 중 최대값을 전체 파일의 최대값으로 단정하지 않습니다.

서버 콘솔의 `Query plan`, `Query result`, `Query failed` 로그로 계획과 제외 개수·실패 원인을 확인할 수 있습니다. 계획 로그에는 질문에 포함된 필터 값이 포함될 수 있습니다. 이 변경은 누락 처리 개선이며 모델의 자연어 이해 정확도를 보장하지 않습니다.

`.env` 모드·모델 변경 후에는 서버를 종료하고 재시작하세요. 기존 벡터 프로그램도 재실행하면 새 안내 문구가 적용됩니다. 재시작 후 ‘새 대화’에서 목록·형식별 개수·용량 순위·후속 질문을 확인하세요.

### 조회 계획 오류 개선 및 재현

순위 위치는 `offset`(건너뛸 행 수)과 `limit`(반환 개수)으로 구분합니다. 필터 → 정렬 → offset → limit 순서로 처리하며, 상위 2개는 `offset=0, limit=2`, 두 번째 하나는 `offset=1, limit=1`입니다. 기존 요청이 offset을 생략하면 0으로 처리합니다. 모델 출력 스키마에서는 offset을 요구하고 계획·검토 지침에서도 위치와 개수를 구분합니다. 동률은 기존 목록 순서를 유지하는 행 위치 기준이며 서로 다른 용량값의 순위를 의미하지 않습니다. 원본 바이트로 정렬하고 단위 변환은 표시할 때만 수행합니다. 일부 크기가 누락되면 기존 부분 결과 안내를 유지합니다.

순위 기능 추가 후 백엔드 자동 테스트 **86개 통과**. 실제 Ollama 개발 사례는 **3/4 통과**(상위 두 개, 두 번째 하나, 세 번째 하나). “용량 순서로 두 번째부터 두 개”는 오름차순/내림차순 해석·검토 불일치로 실행되지 않았습니다. 정렬 방향을 명시하지 않은 표현의 처리는 여전히 검증이 필요하며 모든 질문의 성공을 보장하지 않습니다. 재현 보고서: `data/evaluations/general_ordinal.json`(로컬 생성, Git 제외).

파일 크기는 채팅과 상세 결과 표에서 B/KB/MB/GB/TB 단위를 자동 선택해 표시합니다(1 MB = 1,000,000바이트, 소수점 최대 두 자리). 용량 합계·평균·최댓값도 같은 표시 규칙을 사용합니다. API의 `size_bytes`와 계산 원본은 바이트 숫자로 유지됩니다.

파일의 이름을 반환하는 순위 조회와 숫자만 반환하는 집계를 모델 출력 스키마의 별도 분기로 구분합니다. 집계 출력에서 파일 이름을 선택하거나 원본 파일 크기로 정렬하는 모순된 조합은 생성 스키마에서 제한합니다. 실행 전 Python 검증은 계속 적용합니다. 수정 요청에는 거절된 원본 계획과 검증 오류·검토 결과를 함께 전달하며, 수정은 최대 1회로 제한합니다. 질문별 문자열 매칭이나 실행 명령 생성은 사용하지 않습니다.

모델의 검토·수정 지시문은 사용자 답변에 표시하지 않습니다. 실패 시 사용자에게 조회 방법을 확정하지 못했다는 안내를 제공하고, 서버 로그의 `Query candidate`, `Query review`, `Query failed`에 내부 진단을 남깁니다. 숫자 집계와 정보 누락 안내의 필드명도 사용자용 한글 이름으로 표시합니다.

```powershell
.\.venv\Scripts\python.exe -m app.experiments.evaluate_general_agent --model qwen3:4b-instruct --report data/evaluations/general_final_targeted.json --diagnostic-log data/evaluations/general_final_targeted.log --case-index 11 --case-index 0 --case-index 3 --case-index 1
```

최종 수정 후 실제 Ollama + 합성 데이터로 최대 파일·TIFF 최대/최소 파일·TIFF 개수 **4개 개발 사례가 모두 통과**했습니다(약 4~10초). 이는 해당 사례의 검증이며 전체 질문에 대한 정확도 보장은 아닙니다. 사용자 프로젝트의 실제 파일 접근은 별도 확인이 필요합니다. 백엔드 자동 테스트는 **80개 통과**했습니다.

### 기본 조회 및 복합 요청의 검토 범위

“레이어 목록에 대해 설명해줘”가 조회 조건 부족으로 분류되고, “레이어 목록과 포토샵 연결상태 확인해줘”의 레이어 계획 검토에서 별도 포토샵 작업을 누락으로 판단하는 실패를 실제 Ollama로 재현했습니다(수정 전 두 사례 모두 실패). 목록의 설명·요약·개요는 현재 프로젝트의 기본 메타데이터 조회로 처리하도록 기능 설명을 명확히 했습니다. 복합 요청의 검토에는 현재 하위 요청을 주 대상으로, 전체 요청은 참고 맥락으로 전달하고, 별도 작업 계획과 사용 가능한 도구도 함께 전달합니다. 레이어 조회 계획에 포토샵 상태 필드를 넣도록 요구하지 않습니다. 문장별 매칭 규칙은 사용하지 않습니다.

수정 후 실제 Ollama + 합성 데이터에서 위 두 사례 모두 통과했습니다. 테스트의 포토샵 응답은 모의 데스크톱 결과이며 사용자 PC의 실제 포토샵을 조작하지 않습니다. 자동 테스트는 백엔드 87개, 채팅 UI 18개 통과했습니다. 분류 결과와 입력·출력 토큰 수를 로그에 남겨 추후 실패가 분류·계획·검토 중 어느 단계인지 구분할 수 있습니다.

같은 최종 코드로 기존 개발 사례까지 재검증한 결과 **16/17 통과**했습니다(`data/evaluations/general_scope_regression.json`). 남은 실패는 “TIFF는 몇 개야?”에 합계 하나 대신 `.tif: 2, .tiff: 1`로 나누어 답한 경우입니다. 모델 검토도 이 출력 차이를 놓쳤습니다. 개발 중 사용한 사례의 결과이며 독립된 평가나 범용 정확도 보장은 아닙니다.

```powershell
.\.venv\Scripts\python.exe -m app.experiments.evaluate_general_agent --model qwen3:4b-instruct --report data/evaluations/general_basic_after.json --diagnostic-log data/evaluations/general_basic_after.log --case-index 15 --case-index 16
```
