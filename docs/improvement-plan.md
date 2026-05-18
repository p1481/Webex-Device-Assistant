# Device Assistant — 후속 개선 계획서

작성일: 2026-05-18
선행 작업: 실패 테스트 수정 + pyright 0-error + GitHub Actions CI + ruff format 일괄 적용 완료

---

## #2. `tests/test_app.py` 도메인별 분할

**현황:** 7,514 lines, 단일 파일에 300+ 테스트 함수 집중.

**위험 요인:**
- 모듈 전역 `client = build_authenticated_client(app)` 패턴 (line 93) — 모든 테스트가 공유.
- `temporary_env`, `as_mapping`, `as_sequence`, `build_authenticated_client`, `build_unauthenticated_client` 등 헬퍼가 인라인 정의됨.
- import 그래프가 거대 — 60+ 심볼.

**분할 전략:**

1단계: `tests/conftest.py` 신설하여 공통 fixture/helper 이관
   - `build_authenticated_client`, `build_unauthenticated_client` → fixture로 변환
   - `temporary_env`, `as_mapping`, `as_sequence` → `tests/_helpers.py`
   - 모듈 전역 `client = ...` 제거 → `@pytest.fixture` 의존성으로 대체

2단계: 도메인별 파일 분할 (목표 파일 크기 ~500~1000 lines)
   - `tests/admin/test_admin_auth.py` — 어드민 로그인/세션/쿠키
   - `tests/admin/test_admin_policies.py` — 정책 CRUD
   - `tests/admin/test_admin_providers.py` — provider 설정
   - `tests/admin/test_admin_audit.py` — 감사 로그
   - `tests/orchestration/test_orchestrator_intents.py` — 인텐트 라우팅
   - `tests/orchestration/test_pending_state.py` — pending action 흐름
   - `tests/orchestration/test_approval_flow.py` — 승인 흐름
   - `tests/webhooks/test_webhook_signature.py` — 시그니처 검증
   - `tests/webhooks/test_webhook_ingest.py` — Webex 인제스트
   - `tests/integration/test_debug_messages.py` — `/debug/messages` 엔드포인트
   - `tests/integration/test_health.py` — health/startup-config
   - `tests/integration/test_provider_runtime.py` — provider 런타임

3단계: 각 분할마다 `pytest`로 검증 — 한 번에 옮기지 말고 50~100 테스트씩.

**소요:** 3~4시간 / 별도 PR 권장.

**작업 단위 분리 권장:**
- PR-1: conftest + helpers 추출 (테스트 파일은 그대로, fixture만 사용)
- PR-2~5: 도메인별 4~5개 PR로 분할 (병합 충돌 회피)

---

## #3. `device_executor/device_client.py` mixin 분리

**현황:** 2,386 lines, 단일 `DeviceClient` 클래스.

**경계 제약 (AGENTS.md §7):**
> `device_executor/device_client.py` is the transport-detail boundary.
> Webex cloud xAPI 전용: `/v1/devices`, `/v1/xapi/status`, `/v1/xapi/command/{commandKey}`.

**위험 요인:**
- 외부 API 면 — 시그니처 변경 시 호출부(`executor.py`, `orchestrator.py`, `direct_tool_adapter/*`) 전체 영향.
- mock 모드 + 실제 cloud xAPI 양쪽이 같은 인터페이스 공유.
- 디바이스 디스앰비규에이션(`DeviceResolutionError`) 로직이 다른 도메인과 얽혀 있음.

**분할 전략 (mixin 접근):**

`device_executor/device_client/` 패키지화:
```
device_executor/device_client/
├── __init__.py          # DeviceClient(전체 mixin 결합), DeviceResolutionError export
├── base.py              # HTTPX 클라이언트, token 주입, retry, 공통 에러
├── devices_mixin.py     # /v1/devices, list_devices, resolve_device
├── xapi_status_mixin.py # /v1/xapi/status
├── xapi_command_mixin.py# /v1/xapi/command/*
├── camera_modes.py      # list_supported_camera_modes
└── mock.py              # mock 모드 응답 픽스처
```

**전제 작업:**
- ADR 작성: "왜 mixin인가, 왜 composition이 아닌가" (단순 mixin이면 결국 한 클래스에 다 붙음 — composition + protocol이 더 깔끔할 수 있음)
- 인터페이스를 protocol로 추출 → `DeviceClientProtocol` 정의 → 호출부는 protocol에 의존

**검증 기준:**
- 모든 import 경로 `from device_executor.device_client import DeviceClient` 유지 (BC)
- `tests/test_webex_integration.py`, `tests/test_app.py`의 device 관련 테스트 전부 통과

**소요:** 4~6시간 / 별도 PR + ADR 선행 권장.

---

## #4. Observability — structlog + OTel + Prometheus

**현황:** 표준 `logging`, 메트릭/트레이싱 부재.

**도입 단계:**

### Phase A — structlog (소요 2시간)
- 의존성: `structlog`, `python-json-logger`
- `assistant_app/logging_config.py` 신설:
  - JSON 출력 (production) / 컬러 콘솔 (dev) 모드 분기
  - `structlog.contextvars.bind_contextvars`로 request_id, session_id, user_id 자동 주입
- `main.py:_configure_logging` 대체
- FastAPI 미들웨어로 request_id 발급 + bind
- 기존 `logging.getLogger(__name__)` 호출은 그대로 유지 (structlog가 stdlib 인터셉트)

### Phase B — OpenTelemetry (소요 1.5시간)
- 의존성: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx`, `opentelemetry-exporter-otlp`
- `assistant_app/tracing.py` 신설:
  - OTLP exporter (env: `OTEL_EXPORTER_OTLP_ENDPOINT`)
  - FastAPI + httpx 자동 instrument
  - 수동 span: `orchestrator.handle_message`, `device_client.execute_command`, `provider.analyze_message`
- 환경변수로 on/off (`OTEL_ENABLED=false` 기본값 — opt-in)

### Phase C — Prometheus (소요 1시간)
- 의존성: `prometheus-client`
- `/metrics` 엔드포인트 (`assistant_app/routes/metrics.py`)
- 핵심 메트릭:
  - `assistant_requests_total{intent, mode, outcome}` Counter
  - `assistant_request_duration_seconds{intent}` Histogram
  - `device_xapi_calls_total{endpoint, status}` Counter
  - `device_xapi_duration_seconds{endpoint}` Histogram
  - `provider_analyze_duration_seconds{provider}` Histogram
  - `approvals_pending` Gauge
- 어드민 페이지에서 `/metrics` 보호 (인증 필요 여부 결정)

**위험 요인:**
- OTel과 structlog 둘 다 `logging` 후킹 — 충돌 주의. structlog 먼저, OTel은 별도 트레이서.
- 테스트 환경에서 OTel 익스포터가 OTLP endpoint 없으면 startup 실패 가능 — `OTEL_SDK_DISABLED=true` 기본값.
- Prometheus 멀티프로세스 모드는 uvicorn workers > 1일 때만 필요.

**소요:** 4~5시간 / Phase A→B→C 순차 PR 권장.

---

## 권장 진행 순서

1. **PR-1 (small):** test_app.py conftest 추출 (1.5h, 위험 낮음)
2. **PR-2 (medium):** structlog 도입 — Phase A만 (2h, 즉시 가치)
3. **PR-3 (large):** test_app.py 도메인별 분할 (2h, PR-1 후속)
4. **PR-4 (large):** device_client mixin 분리 + ADR (5h, 별도 세션)
5. **PR-5 (medium):** OTel + Prometheus — Phase B+C (2.5h)

각 PR은 독립적으로 머지 가능하고, 실패해도 롤백 영향이 다른 PR에 미치지 않음.
