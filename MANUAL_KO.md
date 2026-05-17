# Webex Device Assistant 앱 아키텍처 및 사용 가이드

## 1. 개요

이 저장소는 FastAPI 기반의 Webex Device Assistant 앱입니다. 현재 범위에는 다음 요소가 함께 포함됩니다.

- 로컬 테스트용 디버그 메시지 경로
- 실제 Webex 메시지 웹훅 수신 경로
- 승인 카드와 attachment action 처리 경로
- `/admin/*` JSON API와 얇은 `/admin-page` 브라우저 UI
- 두 가지 실행 모드에서 동일한 대화 경험을 유지하는 LLM-first 오케스트레이션

현재 기본 동작은 **mock-first** 입니다.

- `WEBEX_MOCK_MODE=true`
- `DEVICE_MOCK_MODE=true`

즉, 외부 자격 증명 없이도 앱을 먼저 실행하고 전체 흐름을 검증할 수 있습니다.

## 2. 상위 아키텍처

전체 구조는 다음과 같습니다.

```text
사용자 / 관리자 / Webex
        │
        ├─ POST /debug/messages
        ├─ POST /webhooks/webex/messages
        ├─ POST /webhooks/webex/attachment-actions
        └─ /admin-page, /admin-page/webex-test, /admin/*
                │
                ▼
          assistant_app/
            ├─ main.py
            ├─ orchestrator.py
            ├─ policy_evaluator.py
            ├─ webex_gateway.py
            ├─ webhook_controller.py
            └─ providers/
                │
                ├─ separated mode → device_executor/
                └─ all_llm mode   → direct_tool_adapter/
                                      │
                                      ▼
                         Webex cloud xAPI / deviceConfigurations
```

핵심 원칙은 다음과 같습니다.

- Assistant App이 항상 대화 처리와 정책 판단의 중심입니다.
- 실행 모드 차이는 **누가 실행을 담당하느냐** 이며, 사용자 경험 차이가 아닙니다.
- 실제 장치 연동 경로는 **로컬 RoomOS 전송이 아니라 Webex cloud xAPI** 입니다.

## 3. 모듈 경계

### `assistant_app/`

앱 조립과 오케스트레이션을 담당하는 중심 계층입니다.

- `main.py`: FastAPI 앱, 라우트, 상태 저장소, 제공자 등록, 실행기 바인딩, 스타트업 훅 구성
- `orchestrator.py`: 대화 처리, 후속 질문, 장치 선택 카드, 승인 생성, 승인 후 실행
- `policy_evaluator.py`: 인텐트별 실행 모드/승인 기본 정책 결정
- `webhook_controller.py`: Webex 원문 서명 검증, 이벤트 중복 방지, 메시지/카드 클릭 흐름 분기
- `webex_gateway.py`: Webex 메시지 fetch/send, self-message 필터링, attachment action 상세 조회, 메시지/attachmentActions 웹훅 정합성 처리
- `providers/`: 현재 분석 제공자 구현

### `device_executor/`

Separated Mode의 실행 담당 계층입니다.

- 승인 상태와 지원 인텐트를 확인한 뒤 실제 장치 호출로 연결합니다.

### `direct_tool_adapter/`

All LLM Mode의 실행 담당 계층입니다.

- 같은 정규화 요청을 직접 도구 호출 형태로 실행합니다.

### `admin_page/`

브라우저 문서 및 관리 화면을 정적 파일로 제공하는 얇은 표면입니다.

- 별도 백엔드 서비스가 아니라 기존 FastAPI 앱의 일부입니다.

### `shared/`

공유 계약과 기본 정책의 기준점입니다.

- 인텐트, 실행 결과, 승인 모델, 관리자 모델, 기본 정책을 정의합니다.

## 4. 실행 모드

두 실행 모드는 다음처럼 구분됩니다.

| 항목 | Separated Mode | All LLM Mode |
| --- | --- | --- |
| 오케스트레이션 | `assistant_app` | `assistant_app` |
| 실행 소유권 | `device_executor` | `direct_tool_adapter` |
| 공통 장치 전송 계층 | `device_client.py` | `device_client.py` |
| 기본 사용자 경험 | 동일 | 동일 |

정리하면 다음과 같습니다.

- 읽기 동작은 현재 두 모드 모두에서 많이 허용됩니다.
- 대부분의 변경 동작은 두 모드에서 가능하지만 기본적으로 승인 필요입니다.
- `reboot`, `factory_reset` 은 현재 **Separated Mode 전용** 입니다.

## 5. 주요 흐름

### 5.1 로컬 디버그 흐름

```text
POST /debug/messages
  → Orchestrator
    → 정책 평가
      → 즉시 실행 또는 승인 생성
        → ExecutionResult 정규화
          → 최종 응답 텍스트/선택적 markdown 반환
```

로컬 개발 시 가장 빠르게 전체 흐름을 확인할 수 있는 진입점입니다.

### 5.2 Webex 메시지 흐름

```text
POST /webhooks/webex/messages
  → raw body 서명 검증
  → messages.created payload 검증
  → Webex에서 실제 메시지 fetch
  → self-message / 빈 메시지 / 비허용 사용자 필터링
  → Orchestrator
  → Webex room으로 응답 전송
```

현재 메시지 웹훅은 다음 두 필터를 기준으로 맞춰집니다.

- `roomType=direct`
- `roomType=group&mentionedPeople=me`

### 5.3 승인 카드 및 attachment action 흐름

```text
변경 요청
  → 승인 카드 생성
  → 사용자가 Webex 카드 클릭
  → POST /webhooks/webex/attachment-actions
  → raw body 서명 검증
  → GET /v1/attachment/actions/{id} 로 상세 조회
  → 승인/거절 반영
  → 승인된 경우 실행 후 후속 메시지 전송
```

이 흐름에서 중요한 현재 동작은 다음과 같습니다.

- 승인 카드와 관리자 로그인 카드는 **fetch-by-id semantics** 를 사용합니다.
- 즉, 제출 데이터가 웹훅 바디에 직접 들어온다고 가정하지 않고, 서버가 attachment action id로 다시 조회합니다.
- 장치 선택 카드도 같은 attachment-actions 경로를 사용합니다.

### 5.4 브라우저 관리자 로그인 흐름

```text
/admin-page 접속
  → 허용된 관리자 이메일 입력
  → Webex DM 승인 카드 발송
  → 브라우저가 /admin/auth/status/{session_id} 폴링
  → 승인되면 관리자 세션 쿠키 발급
  → 이후 /admin/* 보호 데이터 로드 가능
```

이 흐름에서 기억할 현재 사실은 다음과 같습니다.

- `/admin-page` 자체는 인증 게이트 뒤에 있지 않습니다.
- 대신 **보호된 관리자 데이터 로드** 가 관리자 세션 쿠키에 의해 보호됩니다.
- 관리자 세션은 현재 프로세스 로컬 상태입니다.

## 6. Mock 모드와 Real 모드 설정

### 6.1 기본 Mock 모드

기본 개발 경험은 mock-first 입니다.

- Webex 메시지 송수신 없이도 `/debug/messages` 로 흐름 검증 가능
- 장치 실연동 없이도 대표 응답과 승인 흐름 검증 가능
- `/admin-page/webex-test` 에서 런타임 상태 확인 가능

### 6.2 Real Webex 모드

실제 Webex 메시징을 사용하려면 최소한 다음 값이 필요합니다.

- `WEBEX_MOCK_MODE=false`
- `WEBEX_BOT_TOKEN`
- `WEBEX_BOT_PERSON_ID`
- `WEBEX_WEBHOOK_SECRET`
- `ADMIN_COOKIE_SECRET` (관리자 UI 세션 쿠키 HMAC 키. 마이그레이션 가이드: `docs/MIGRATION_ADMIN_COOKIE_SECRET.md`)

선택적으로 스타트업 웹훅 정합성까지 맞추려면 다음 설정도 필요합니다.

- `WEBEX_WEBHOOK_RECONCILE_ON_STARTUP=true`
- `WEBEX_WEBHOOK_TARGET_URL=https://.../webhooks/webex/messages`

### 6.3 Real 장치 모드

실제 장치 실행을 사용하려면 최소한 다음 값이 필요합니다.

- `DEVICE_MOCK_MODE=false`
- `WEBEX_TOKEN_MANAGER_BASE_URL`
- `WEBEX_TOKEN_MANAGER_API_KEY`

현재 실제 장치 호출은 Webex cloud API를 사용합니다.

- `GET /v1/devices`
- `GET /v1/xapi/status`
- `POST /v1/xapi/command/{commandKey}`
- `PATCH /v1/deviceConfigurations`

## 7. 현재 제공 기능

### 7.1 읽기 기능

- 장치 상태 조회 (`get_status`)
- 환경 정보 조회 (`get_environment_info`)
- 카메라 모드 조회 (`get_camera_mode`)
- 룸 예약/OBTP 상태 조회 (`get_room_booking`)
- 조직 장치 목록 조회 (`list_devices`)

### 7.2 변경 기능

- Webex join
- 다음 join 가능한 일정에 대한 OBTP join
- dial / hang up / DTMF
- microphone mute / microphone mode
- volume
- video mute
- selfview
- camera mode 변경 (`best_overview`, `speaker_closeup`, `frames` 제한)
- layout
- presentation start/stop
- input source switch
- matrix assign / unassign / swap
- display mode / display role
- camera preset activation
- SpeakerTrack
- standby
- reboot
- factory reset

### 7.3 정책 기본값

- 읽기 기능은 대체로 승인 없이 실행 가능
- 대부분의 변경 기능은 기본적으로 승인 필요
- `reboot`, `factory_reset` 은 승인 필요 + separated only

## 8. 로컬 사용 방법

### 8.1 앱 실행

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

### 8.2 기본 확인

```bash
curl http://127.0.0.1:8000/healthz
```

### 8.3 디버그 메시지 보내기

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get status of Board Pro","preferred_mode":"separated"}'
```

### 8.4 승인 흐름 만들기

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"set volume to 35 on Board Pro","session_id":"demo-approval"}'
```

## 9. 관리자 페이지

### 9.1 접속 경로

브라우저에서 다음 페이지를 열 수 있습니다.

- `/admin-page`: 관리자 런타임 화면
- `/admin-page/docs`: 영문 문서 허브
- `/admin-page/docs-ko`: 한국어 요약 문서 페이지
- `/admin-page/webex-test`: Webex 런타임 확인 및 시뮬레이션 화면

### 9.2 현재 볼 수 있는 정보

관리자 페이지에서는 현재 다음 항목을 확인할 수 있습니다.

- 런타임 설정
- 스타트업 상태
- 제공자 설정
- 액션 레지스트리
- 인텐트별 정책
- 조직 장치 목록
- 승인 요청
- 감사 기록
- 프로세스 로컬 통계

### 9.3 Webex Test 페이지

`/admin-page/webex-test` 는 다음 용도로 사용합니다.

- `/debug/webex/runtime` 기반 Webex 런타임 표시
- Webex inbound message 시뮬레이션
- Webex를 우회하는 직접 디버그 메시지 전송

주의:

- `POST /debug/webex/simulate-message` 는 **`WEBEX_MOCK_MODE=true` 일 때만 동작** 합니다.

## 10. 실제 Webex 사용 시 기억할 점

- 메시지 수신 경로는 `POST /webhooks/webex/messages`
- 카드 클릭 수신 경로는 `POST /webhooks/webex/attachment-actions`
- Webex 그룹 메시지는 app-owned webhook 필터 기준으로 `mentionedPeople=me` 인 경우만 의도 범위입니다.
- 서버는 self-message 와 빈/non-actionable 메시지를 게이트웨이에서 먼저 걸러냅니다.

## 11. 현재 한계

- 기본 운영 모드는 아직 mock-first 입니다.
- 실제 장치 경로는 Webex cloud xAPI 기준이며 로컬 RoomOS 전송은 현재 범위가 아닙니다.
- 런타임 분석 제공자로 실제 활성화 가능한 것은 현재 `rule_based`, `ollama` 뿐입니다.
- `openai`, `gemini`, `anthropic` 는 설명자/관리 데이터에는 보이지만 현재 런타임 제공자로는 적용되지 않습니다.
- 카메라 모드 쓰기 지원은 제한적입니다.
- 룸 예약 영역은 조회와 "다음 join 가능한 회의 참여" 중심이며 booking CRUD 는 범위 밖입니다.
- 세션 메모리, pending follow-up 상태, processed-event dedupe, 관리자 세션 플래그는 재시작 안전하지 않습니다.
- 관리자 페이지는 얇은 제어면이지 별도 관리자 제품이 아닙니다.

## 12. 관련 문서

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [INSTALL.md](INSTALL.md)
- [USER_MANUAL.md](USER_MANUAL.md)

## 13. 요약

이 앱은 Assistant App 중심의 LLM-first 구조 위에서, 동일한 사용자 경험을 유지한 채 Separated Mode와 All LLM Mode를 모두 지원합니다. 기본값은 mock-first 이며, 필요 시 Webex 메시징과 Webex cloud xAPI 기반 실제 장치 실행으로 확장할 수 있습니다.
