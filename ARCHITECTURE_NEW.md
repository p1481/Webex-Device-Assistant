# 세부 아키텍처 문서

## 1. 문서 목적
이 문서는 `/home/p1481/youngcle_code/06. Device Assistant` 프로젝트의 현재 구현을 기준으로, 실행 구조, 모듈 책임, 요청 흐름, 정책 및 승인, 데이터 계약, 외부 연동, 한계 사항까지 포함한 세부 아키텍처를 설명한다.

이 프로젝트는 FastAPI 기반의 Webex Device Assistant 애플리케이션이다. 핵심 목적은 사용자의 자연어 요청을 해석해 Webex 디바이스 상태 조회나 제어 명령으로 변환하고, 정책에 따라 승인 절차를 거쳐 실제 장치에 반영하는 것이다.

---

## 2. 시스템 한눈에 보기

### 2.1 핵심 특성
- FastAPI 기반 API 서버
- Webex 메시지 수신 및 응답 지원
- 로컬 디버그 API 제공
- Web UI 기반 관리자 페이지 제공
- 자연어 해석 계층과 장치 실행 계층 분리
- `separated` / `all-llm` 두 가지 실행 모드 지원
- Mock-first 기본 설정

### 2.2 아키텍처 핵심 개념
이 시스템은 항상 **Assistant App이 중심 오케스트레이터** 역할을 수행한다. 즉, 사용자의 메시지를 받아서:
1. 의도 분석
2. 필요한 파라미터 보정
3. 정책 평가
4. 승인 필요 여부 판단
5. 실행 요청 생성
6. 실행 결과 포맷팅
의 흐름을 일관되게 담당한다.

실행 모드 차이는 오직 **명령 실행을 어떤 백엔드가 담당하는가**에 있다.

- **Separated mode**: `device_executor`가 실행 담당
- **All LLM mode**: `direct_tool_adapter`가 실행 담당

즉, 사용자 경험과 상위 대화 흐름은 동일하고, 하위 실행 계층만 바뀐다.

---

## 3. 상위 구성도

```text
[User / Webex / Debug Client]
          |
          v
[FastAPI Routes in assistant_app.main]
          |
          v
[WebexGateway / WebhookController / Debug Endpoint]
          |
          v
[Orchestrator]
  |- Session Memory
  |- Provider (Rule-based or Ollama)
  |- Policy Evaluator
  |- Approval Manager
  |- Mode Router
          |
          v
[Execution Backend]
  |- DeviceExecutor        (separated)
  |- DirectToolAdapter     (all-llm)
          |
          v
[DeviceClient / Webex Cloud xAPI / Mock Device]
```

---

## 4. 주요 패키지와 책임

## 4.1 `assistant_app/`
애플리케이션의 중심 계층이다. API 진입점, 오케스트레이션, 정책, 세션 컨텍스트, Webex 연동, 관리자 기능을 담당한다.

### 주요 파일
- `main.py`
  - FastAPI 앱 생성
  - 설정 로딩
  - 서비스 객체 조립
  - 라우트 등록
  - 런타임 상태 초기화
- `orchestrator.py`
  - 전체 대화 흐름의 핵심 컨트롤러
  - 의도 분석 결과를 기반으로 pending action, 승인, 실행, 응답 포맷팅 처리
- `config.py`
  - 환경 변수 기반 설정 로딩 및 검증
- `policy_evaluator.py`
  - 요청 intent별 정책 평가
  - 실행 모드 선택과 승인 필요 여부 판단
- `mode_router.py`
  - `ExecutionRequest`를 생성하고 적절한 실행기(`device_executor` 또는 `direct_tool_adapter`)로 전달
- `memory_store.py`
  - 세션별 대화 이력과 pending action 보관
- `webex_gateway.py`
  - Webex 메시지 송수신 처리
  - Webex webhook payload 해석
- `webhook_controller.py`
  - Webex webhook 검증 및 오케스트레이터 연결
- `provider_registry.py`
  - 분석 provider 메타데이터 및 provider 인스턴스 생성
- `approval_manager.py`
  - 승인 요청 생성 및 상태 관리
- `admin_service.py`, `admin_auth.py`
  - 관리자 인증, 설정, 정책, 통계, 감사 이벤트 처리
- `state_store.py`
  - 런타임 관리자 상태, 정책, 승인, 감사 내역 등을 저장

### 역할 요약
`assistant_app`은 단순한 API 레이어가 아니라, 이 시스템의 실제 애플리케이션 서비스 계층이다.

---

## 4.2 `device_executor/`
Separated mode 실행 계층이다.

### 주요 파일
- `executor.py`
  - 승인 상태 검사
  - 지원 intent 확인
  - 핸들러 호출 및 예외 변환
- `handlers.py`
  - intent별로 실제 장치 작업 분기
- `device_client.py`
  - Webex Cloud xAPI 호출
  - 장치 탐색, 상태 조회, 명령 실행, 설정 patch 수행

### 역할 요약
이 계층은 의도 분석을 하지 않는다. 이미 구조화된 `ExecutionRequest`를 받아, deterministic하게 장치 명령만 수행한다.

---

## 4.3 `direct_tool_adapter/`
All LLM mode 실행 계층이다.

### 주요 파일
- `adapter.py`
  - `ExecutionRequest`의 intent별 분기 처리
  - `DirectToolSet` 호출
- `tools.py`
  - `DeviceClient`를 감싼 도구 집합

### 역할 요약
현재 구현 기준으로는 separated mode와 유사하게 동작한다. 차이는 분리된 executor 대신 tool-style adapter를 거친다는 점이다. 즉, 이름은 all-llm이지만 현재 MVP에서는 완전한 agentic tool-calling 엔진보다는 “tool adapter 기반 실행 계층”에 가깝다.

---

## 4.4 `shared/contracts/`
시스템 전반의 데이터 계약을 정의한다.

### 포함 내용
- `actions.py`
  - `Intent`
  - `ActionProposal`
  - 각 intent용 파라미터 모델
  - `PendingActionProposal`
  - `OrchestrationDecision`
- `execution.py`
  - `ExecutionRequest`, `ExecutionResult`, 상태 스냅샷 모델
- `policy.py`
  - `ExecutionMode`, `ApprovalState`, `PolicyDecision`
- `provider.py`
  - provider 종류, capabilities, settings
- `inbound.py`
  - `InboundUserMessage`, `OutboundReply`
- `admin.py`, `approval.py`, `audit.py`, `conversation.py`
  - 관리자, 승인, 감사, 세션 관련 모델

### 역할 요약
이 레이어 덕분에 상위 오케스트레이션과 하위 실행 계층이 느슨하게 결합된다.

---

## 4.5 `admin_page/`
정적 파일 기반의 얇은 관리자 UI 레이어다.

### 주요 파일
- `api.py`
  - `/admin-page` 및 정적 문서/에셋 라우팅
  - 문서 파일 다운로드 제공
- `static/index.html`
  - 관리자 UI 진입점
- `static/admin.js`
  - 관리자 페이지 클라이언트 로직

### 특징
- 정적 파일 서빙 중심
- 실질적인 데이터/설정 변경은 `/admin/*` API가 처리
- 아키텍처 문서와 사용자 매뉴얼도 페이지에서 다운로드 가능

---

## 5. 런타임 조립 방식

`assistant_app.main.build_app()`가 애플리케이션의 composition root 역할을 한다.

### 생성되는 핵심 객체
- `AppConfig`
- `InMemorySessionStore`
- `InMemoryStateStore` 또는 파일 기반 상태 저장소
- `TokenManagerTokenProvider`
- `DeviceClient`
- `ExecutionHandlers`
- `DeviceExecutor`
- `DirectToolSet`
- `DirectToolAdapter`
- `ModeRouter`
- `ApprovalManager`
- `ProviderRegistry`
- `Orchestrator`
- `WebexGateway`
- `WebhookController`
- `AdminService`

즉, 별도 DI 프레임워크 없이 `main.py`에서 명시적으로 wiring 하는 구조다. 현재 규모에서는 추적이 쉽고 단순하다는 장점이 있다.

---

## 6. 요청 처리 흐름

## 6.1 로컬 디버그 요청 흐름
예: `POST /debug/messages`

1. 클라이언트가 텍스트 요청 전송
2. `main.py`가 `InboundUserMessage` 생성
3. `orchestrator.handle_message()` 호출
4. provider가 자연어를 `OrchestrationDecision`으로 변환
5. pending action 또는 직접 실행 여부 결정
6. `policy_evaluator`가 정책 평가
7. 승인 필요 시 승인 응답 생성
8. 아니면 `mode_router.execute()`로 실행 요청 전달
9. 실행 결과를 `OutboundReply`로 반환

## 6.2 Webex 메시지 흐름
1. Webex가 webhook 호출
2. `webhook_controller.py`가 서명 및 payload 검증
3. `webex_gateway.py`가 원문 메시지 조회 및 응답 송신 담당
4. `InboundUserMessage` 생성
5. 이후 흐름은 debug 요청과 동일

---

## 7. Orchestrator 상세 동작

`orchestrator.py`는 이 프로젝트에서 가장 중요한 애플리케이션 로직을 갖는다.

### 주요 책임
- 사용자 turn 저장
- pending action 확인
- reset context 처리
- provider 분석 수행
- 파라미터가 부족하면 follow-up 질문 생성
- 관리자 로그인 승인 요청 생성
- 정책 평가 후 승인 또는 실행 분기
- 실행 결과를 텍스트/markdown으로 정리

### 핵심 특징
1. **멀티턴 파라미터 수집 지원**
   - 예: “볼륨 올려줘” → 장치명 누락 시 어떤 장치인지 다시 질문
   - `PendingActionProposal`에 미완성 파라미터 저장

2. **Webex 카드 기반 선택 지원**
   - 디바이스 선택이 필요한 경우 Adaptive Card로 선택 UI 제공 가능

3. **실행 결과 정규화**
   - 장치 상태, 카메라 모드, 예약 정보 등을 사람이 읽기 쉬운 문장으로 변환

4. **실행 백엔드와 분리**
   - 실제 명령 실행은 직접 하지 않고 `ModeRouter`로 위임

---

## 8. Provider 계층

## 8.1 지원 provider
`provider_registry.py` 상의 메타데이터 기준:
- `rule_based`
- `openai` (메타데이터만, 런타임 분석 미구현)
- `gemini` (메타데이터만, 런타임 분석 미구현)
- `anthropic` (메타데이터만, 런타임 분석 미구현)
- `ollama`

실제 `build_analysis_provider()`에서 현재 런타임 분석에 사용 가능한 것은:
- RuleBasedProvider
- OllamaProvider

즉, 나머지 provider는 관리자 UI나 확장 포인트를 위한 descriptor 수준이며, 현재 구현에서 메시지 분석 provider로는 아직 연결되지 않았다.

## 8.2 RuleBasedProvider
- 정규식 및 키워드 기반 intent 추론
- 주요 MVP 기능을 빠르게 지원
- deterministic하며 디버깅이 쉬움

## 8.3 OllamaProvider
- Ollama `/chat` API 호출
- 실패 시 rule-based provider fallback 사용
- LLM 응답을 파싱해서 `OrchestrationDecision`으로 변환

### 해석 구조의 의미
현재 구조는 “LLM이 완전히 시스템을 통제”하는 구조라기보다,
**LLM은 의도 분석을 보조하고 시스템은 구조화된 계약과 정책을 유지**하는 형태다.

---

## 9. 실행 모드 구조

## 9.1 Separated mode
경로:
`Orchestrator -> ModeRouter -> DeviceExecutor -> ExecutionHandlers -> DeviceClient`

특징:
- 계층 분리가 더 뚜렷함
- intent별 실행 책임이 handlers에 모임
- 명령 실행 정책과 장치 호출이 안정적으로 분리됨

## 9.2 All LLM mode
경로:
`Orchestrator -> ModeRouter -> DirectToolAdapter -> DirectToolSet -> DeviceClient`

특징:
- tool adapter 스타일
- 현재 구현은 deterministic dispatch 기반
- 향후 agentic tool-calling으로 발전 가능한 구조

## 9.3 공통점
두 모드 모두 최종적으로 `DeviceClient`를 사용하며, 장치 제어 capability 자체는 거의 동일하다.

---

## 10. 정책 및 승인 모델

## 10.1 정책 평가
`policy_evaluator.py`는 다음을 결정한다.
- 어떤 execution mode로 실행할지
- approval이 필요한지
- 정책 이유 문자열

정책은 기본값과 런타임 admin 설정이 결합되어 판단된다.

## 10.2 승인 흐름
변경성 작업은 기본적으로 승인 대상이 될 수 있다.

흐름:
1. 오케스트레이터가 `PolicyDecision` 확인
2. 승인 필요 시 `ApprovalManager.create_action_approval()` 호출
3. 사용자에게 승인 카드 전송
4. 승인되면 `execute_approved_request()`에서 실제 실행

### approval-free 기본 허용 작업
현재 코드상 대표적인 read-only intent는 승인 없이 허용된다.
- `GET_STATUS`
- `GET_ENVIRONMENT_INFO`
- `GET_CAMERA_MODE`
- `GET_ROOM_BOOKING`
- `LIST_DEVICES`

---

## 11. 세션 메모리와 상태 저장

## 11.1 대화 세션 메모리
`InMemorySessionStore`
- 세션별 conversation turn 저장
- pending action 저장
- 처리된 이벤트 추적

특징:
- 프로세스 메모리 기반
- 재시작 시 유실 가능

## 11.2 관리자/승인/정책 상태
`state_store.py`
- 런타임 관리자 설정
- provider 설정
- startup config status
- action registry
- approval state
- audit record
등을 관리

상태 저장은 메모리 또는 파일 경로 기반으로 확장 가능하지만, 일부 세션성 정보는 여전히 restart-safe 하지 않다.

---

## 12. DeviceClient 상세

`device_executor/device_client.py`는 실질적인 Webex 연동 핵심이다.

### 주요 책임
- 장치 목록 조회
- 장치명 해석 및 장치 식별
- xAPI status 조회
- xAPI command 실행
- deviceConfigurations patch
- mock 응답 제공

### 12.1 장치 해석
장치명으로 바로 찾지 못하면 정규화 비교를 수행한다.
- exact match 우선
- normalized match 보조
- 여러 대면 ambiguous 오류
- 없으면 not_found 오류

이 오류는 상위 계층에서 사용자 친화적 안내 메시지로 변환된다.

### 12.2 상태 조회
- `/devices`
- `/xapi/status`
- `/deviceConfigurations`
- `/xapi/command/{commandKey}`
를 조합해서 사용한다.

### 12.3 지원 기능
현재 코드 기준으로 다음 기능이 구현되어 있다.
- 상태 조회
- 환경 정보 조회
- 카메라 모드 조회
- 회의실 예약 정보 조회
- OBTP join
- Webex join
- dial / hang up / DTMF
- 마이크 mute / mode
- volume
- video mute
- selfview
- camera mode 변경
- layout 변경
- presentation 시작/종료
- input source 전환
- video matrix assign/unassign/swap
- display mode / role
- camera preset activate
- camera position adjust
- speakertrack
- standby
- reboot
- factory reset
- device list 조회

### 12.4 Mock-first 설계
`DEVICE_MOCK_MODE=true`면 실제 Webex 호출 없이 mock 데이터 반환.
이는 초기 개발, 테스트, UI 검증에 매우 유리하다.

---

## 13. API 및 진입점

## 13.1 대화/디버그
- `POST /debug/messages`
  - 로컬 디버그용 자연어 메시지 테스트

## 13.2 Webex
- `POST /webhooks/webex/messages`
  - Webex 메시지 webhook
- 승인 카드 응답 처리용 엔드포인트들
  - `main.py`에 등록된 admin/approval/webex 관련 route 사용

## 13.3 관리자
- `/admin/*`
  - 설정, 정책, 승인, 통계, 감사 내역 등
- `/admin-page`
  - 정적 관리자 UI
- `/admin-page/manuals/{manual_name}`
  - 문서 다운로드

---

## 14. 설정 구조

`AppConfig`는 환경 변수 기반으로 구성된다.

### 핵심 설정값
- `WEBEX_MOCK_MODE`
- `DEVICE_MOCK_MODE`
- `DEFAULT_EXECUTION_MODE`
- `DEFAULT_PROVIDER`
- `DEFAULT_PROVIDER_MODEL`
- `DEFAULT_PROVIDER_BASE_URL`
- `DEFAULT_TARGET_DEVICE`
- `WEBEX_BOT_TOKEN`
- `WEBEX_BOT_PERSON_ID`
- `WEBEX_WEBHOOK_SECRET`
- `WEBEX_WEBHOOK_TARGET_URL`
- `WEBEX_TOKEN_MANAGER_BASE_URL`
- `WEBEX_TOKEN_MANAGER_API_KEY`

### 검증 특징
- mock mode가 아니면 Webex 자격 증명 필수
- 실제 디바이스 모드면 token manager 정보 필수
- webhook target URL은 https 검증 수행

---

## 15. 관리자 UI와 운영성

관리자 페이지는 가볍지만 운영상 의미가 크다.

### 제공 가치
- 현재 provider 및 실행 모드 확인
- 정책 조정
- 승인 흐름 관찰
- 문서 접근
- 상태/통계 확인

현재 UI는 thin client이고, 핵심 로직은 API 서버가 담당한다.

---

## 16. 테스트 관점

프로젝트에는 테스트 코드가 포함되어 있으며, 주로 다음을 검증한다.
- FastAPI endpoint 동작
- Webex webhook 처리
- 관리자 인증/세션
- 정책 및 응답 흐름
- 통합 수준의 앱 동작

MVP 구조상 rule-based 해석과 mock mode를 활용하면 테스트 안정성이 높다.

---

## 17. 현재 구현의 장점

1. **구조가 명확하다**
   - 오케스트레이션, 정책, 실행, 장치 호출이 분리되어 있음

2. **Mock-first 개발이 쉽다**
   - 실제 Webex 환경 없이도 대부분 흐름 검증 가능

3. **확장 포인트가 있다**
   - provider registry
   - execution mode 분기
   - shared contracts 기반 모델 확장

4. **승인 모델이 내장되어 있다**
   - 운영 환경에서 위험한 명령을 통제 가능

5. **자연어 멀티턴 수집이 가능하다**
   - target device나 세부 파라미터 누락 시 follow-up 가능

---

## 18. 현재 구현의 제약과 개선 포인트

## 18.1 provider 런타임 구현 범위 제한
메타데이터상 OpenAI, Gemini, Anthropic이 있으나 현재 실제 분석 provider로는 연결되지 않았다.

## 18.2 mode_router의 if-elif 확장 부담
`ModeRouter.build_request()`가 intent별 payload를 길게 직접 매핑하고 있어 intent 증가 시 유지보수 부담이 커질 수 있다.

## 18.3 DirectToolAdapter 중복 분기
`adapter.py`에는 일부 display 관련 분기가 중복되어 보이며, 리팩토링 여지가 있다.

## 18.4 In-memory 의존성
세션 pending action과 일부 상태는 프로세스 재시작 시 유실될 수 있다.

## 18.5 formatting 로직 집중
`Orchestrator._format_execution_result()`가 비교적 많은 표현 책임을 갖고 있어 presenter 계층 분리가 가능하다.

---

## 19. 권장 향후 개선 방향

1. **Provider runtime 확장**
   - OpenAI/Gemini/Anthropic 실제 구현 추가

2. **Intent dispatch 일반화**
   - payload field map 기반 request builder 추상화

3. **Execution result presenter 분리**
   - text/markdown renderer 모듈화

4. **Persistent session store 도입**
   - pending action, conversation context 복구성 향상

5. **권한/정책 고도화**
   - 사용자별 권한, 디바이스별 정책, 시간대 정책 등

6. **Agentic all-LLM mode 강화**
   - direct tool adapter를 실제 tool-calling orchestration으로 발전

---

## 20. 결론

이 프로젝트는 단순한 챗봇이 아니라, **정책 통제 가능한 Webex 디바이스 운영 어시스턴트 플랫폼의 MVP**에 가깝다.

현재 구조의 핵심 강점은 다음 세 가지다.
- Assistant App 중심의 일관된 오케스트레이션
- 실행 계층 분리로 인한 진화 가능성
- 자연어 인터페이스와 운영 안전장치의 공존

즉, 지금 상태만으로도 디버그, 운영 데모, 제한적 실사용이 가능한 구조이며, 이후에는 provider 확장, persistence, policy sophistication을 중심으로 발전시키기 좋은 기반이다.
