# 사용자 가이드

## 1. 문서 목적
이 문서는 Webex Device Assistant App의 실제 사용자를 위한 운영 가이드다. 설치 이후 어떤 방식으로 실행하고, 어떤 요청을 보낼 수 있으며, 승인 흐름과 관리자 기능을 어떻게 사용하는지 설명한다.

이 프로젝트는 자연어로 Webex 디바이스를 조회하거나 제어할 수 있게 해준다. 예를 들어 상태 조회, 볼륨 조정, 회의 참가, 카메라 모드 변경 등을 사람이 문장으로 요청할 수 있다.

---

## 2. 이 앱으로 할 수 있는 일
현재 구현 기준으로 다음 범주의 작업을 지원한다.

### 조회 기능
- 장치 상태 조회
- 환경 정보 조회
- 카메라 모드 조회
- 회의실 예약 및 OBTP 가능 여부 조회
- 조직 내 디바이스 목록 조회

### 제어 기능
- Webex meeting join
- OBTP로 다음 회의 참가
- SIP/주소 dial
- hang up
- DTMF 전송
- 마이크 음소거
- 마이크 모드 변경
- 볼륨 변경
- 비디오 mute
- selfview on/off
- 카메라 모드 변경
- 레이아웃 변경
- 프레젠테이션 시작/종료
- 입력 소스 전환
- 비디오 매트릭스 assign/unassign/swap
- 디스플레이 모드/역할 변경
- 카메라 preset 활성화
- 카메라 위치 조정
- SpeakerTrack on/off
- standby on/off
- reboot
- factory reset

주의: 일부 작업은 정책상 승인 절차가 필요하다.

---

## 3. 설치

## 3.1 요구 사항
- Python 3.12 이상 권장
- Linux/macOS 또는 FastAPI 실행 가능한 환경

## 3.2 설치 방법
프로젝트 루트에서 아래 명령을 실행한다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

---

## 4. 실행 방법

## 4.1 기본 실행
```bash
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

기본값은 mock-first 설정이다. 즉, 특별히 환경 변수를 바꾸지 않으면 실제 Webex 장치 없이도 앱 흐름을 테스트할 수 있다.

## 4.2 테스트 실행
```bash
.venv/bin/python -m pytest
```

---

## 5. 가장 쉬운 사용 방법, 로컬 디버그 API
개발/검증 단계에서는 `POST /debug/messages`를 사용하는 것이 가장 쉽다.

### 예제 1. 장치 상태 조회
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get status of Board Pro"}'
```

### 예제 2. 환경 정보 조회
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"show environment info for Board Pro"}'
```

### 예제 3. 볼륨 조정
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"set volume to 35 on Board Pro"}'
```

### 예제 4. 장치 목록 조회
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"list devices"}'
```

---

## 6. 실행 모드 이해하기
이 앱은 두 가지 실행 모드를 가진다.

## 6.1 separated mode
- 장치 실행을 `device_executor`가 담당
- 구조가 더 명시적이고 보수적
- 운영 안정성을 설명하기 쉬움

## 6.2 all-llm mode
- 장치 실행을 `direct_tool_adapter`가 담당
- 현재 구현에서는 tool-style dispatch 방식
- 향후 더 agentic한 확장 가능

## 6.3 요청에서 모드 지정하기
디버그 API에서는 `preferred_mode`를 넣을 수 있다.

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get status of Board Pro","preferred_mode":"separated"}'
```

또는:

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get status of Board Pro","preferred_mode":"all-llm"}'
```

---

## 7. 자주 쓰는 요청 예시

## 7.1 상태 및 정보 조회
```text
get status of Board Pro
show environment info for Board Pro
what is the camera mode on Board Pro
show room booking for Board Pro
list devices
```

## 7.2 회의 제어
```text
join obtp on Board Pro
join webex 123456789 on Board Pro
dial user@example.com on Board Pro
hang up on Board Pro
send dtmf 1234 on Board Pro
```

## 7.3 오디오/비디오 제어
```text
mute microphones on Board Pro
unmute microphones on Board Pro
set microphone mode to voice optimized on Board Pro
set volume to 25 on Board Pro
mute video on Board Pro
turn selfview on on Board Pro
```

## 7.4 카메라 및 화면 제어
```text
set camera mode to frames on Board Pro
set layout to Prominent on Board Pro
start presentation on Board Pro
switch input source to pc on Board Pro
set display mode to dual on Board Pro
activate camera preset 1 on Board Pro
move camera 1 left on Board Pro
```

## 7.5 시스템 제어
```text
enable speakertrack on Board Pro
activate standby on Board Pro
reboot Board Pro
factory reset Board Pro
```

---

## 8. 파라미터가 부족할 때의 동작
이 앱은 멀티턴 follow-up을 지원한다.

예를 들어 아래처럼 요청하면:

```text
set volume to 30
```

장치명이 없기 때문에 앱이 다시 물을 수 있다.

```text
Which device should I use?
```

그 다음 사용자가:

```text
Board Pro
```

라고 답하면 이전 요청을 이어서 처리한다.

### 지원되는 대표 follow-up 항목
- target device
- dial address
- meeting identifier
- volume level

Webex 환경에서는 디바이스 선택용 Adaptive Card가 제공될 수도 있다.

---

## 9. 승인 흐름

## 9.1 승인 없는 작업
일반적으로 조회성 작업은 승인 없이 실행된다.
- 상태 조회
- 환경 정보 조회
- 카메라 모드 조회
- 회의실 예약 조회
- 디바이스 목록 조회

## 9.2 승인 필요한 작업
변경성 작업은 정책에 따라 승인 카드가 먼저 올 수 있다.
예:
- 볼륨 변경
- 마이크 mute
- presentation 시작
- reboot
- factory reset

## 9.3 승인 시 사용자 경험
1. 사용자가 명령 요청
2. 앱이 승인 카드 전송
3. 사용자가 Approve 또는 Reject 선택
4. 승인되면 실제 실행

factory reset 같은 고위험 작업은 특히 주의해서 운영해야 한다.

---

## 10. Webex 연동 사용
실제 Webex 메시지로 사용하려면 mock 모드가 아니라 실제 자격 증명이 필요하다.

### 필요한 대표 설정
- `WEBEX_BOT_TOKEN`
- `WEBEX_BOT_PERSON_ID`
- `WEBEX_WEBHOOK_SECRET`
- `WEBEX_WEBHOOK_TARGET_URL`

또한 실제 장치 제어를 위해서는:
- `DEVICE_MOCK_MODE=false`
- `WEBEX_TOKEN_MANAGER_BASE_URL`
- `WEBEX_TOKEN_MANAGER_API_KEY`
설정이 필요하다.

### 참고
- webhook target URL은 https여야 한다.
- 실제 운영 전에는 debug API와 mock mode로 먼저 검증하는 것이 좋다.

---

## 11. 관리자 페이지 사용

## 11.1 접속 경로
브라우저에서:

```text
http://127.0.0.1:8000/admin-page
```

## 11.2 제공 기능
관리자 페이지 및 관련 API를 통해 다음을 확인하거나 조정할 수 있다.
- 런타임 설정
- 정책
- provider 설정
- 승인 상태
- 감사 로그
- 통계
- 문서 다운로드

## 11.3 문서 보기
다음 문서들을 관리자 페이지 경로에서 받을 수 있다.
- `ARCHITECTURE.md`
- `INSTALL.md`
- `USER_MANUAL.md`
- `MANUAL_KO.md`

정적 docs 페이지도 제공된다.
- `/admin-page/docs`
- `/admin-page/docs-ko`

---

## 12. 관리자 API 예시

## 12.1 설정 조회
```bash
curl http://127.0.0.1:8000/admin/settings
```

## 12.2 정책 업데이트 예시
```bash
curl -X PUT http://127.0.0.1:8000/admin/policies/set_volume \
  -H 'Content-Type: application/json' \
  -d '{
    "allowed_modes": ["separated", "all-llm"],
    "risk_level": "low",
    "approval_state": "required"
  }'
```

운영 중 정책을 바꿀 때는 조회성/변경성 작업의 경계를 먼저 정리하고 적용하는 것을 권장한다.

---

## 13. Mock mode와 Real mode 차이

## 13.1 Mock mode
기본값이다.
- 실제 Webex API 호출 없음
- 실제 장치 없이 응답 가능
- UI, 오케스트레이션, 정책 흐름 점검에 적합

## 13.2 Real mode
실제 Webex API와 장치를 사용한다.
- 실제 봇 메시지 수신 가능
- 실제 xAPI 호출 수행
- 장치 상태/예약/환경 센서 데이터 조회 가능
- 변경성 명령이 실제 장치에 반영됨

### 권장 운영 방식
1. mock mode로 먼저 테스트
2. debug API로 intent와 정책 검증
3. Webex webhook 연결
4. 실제 장치 제어 활성화

---

## 14. 문제 해결 가이드

## 14.1 앱은 뜨는데 장치 제어가 안 됨
확인할 것:
- `DEVICE_MOCK_MODE` 값
- `WEBEX_TOKEN_MANAGER_BASE_URL`
- `WEBEX_TOKEN_MANAGER_API_KEY`
- 대상 장치가 Webex inventory에 존재하는지
- 장치명이 정확한지

## 14.2 Webex webhook이 안 들어옴
확인할 것:
- `WEBEX_WEBHOOK_TARGET_URL`이 https인지
- `WEBEX_BOT_TOKEN`, `WEBEX_BOT_PERSON_ID`, `WEBEX_WEBHOOK_SECRET`
- Webex webhook 등록 상태

## 14.3 장치를 찾지 못함
장치명 매칭은 exact 또는 normalized 비교를 사용한다.
다음처럼 다시 요청해보는 것이 좋다.
- 장치 전체 이름 사용
- `list devices`로 실제 등록명 먼저 확인

## 14.4 승인 후에도 실행되지 않음
확인할 것:
- 정책상 해당 작업이 허용된 mode인지
- approval 상태가 실제로 approved로 기록되었는지
- 장치 해석 오류가 발생하지 않았는지

---

## 15. 운영 팁

1. **처음엔 조회 기능부터 테스트**
   - `get status`, `list devices`가 가장 안전하다.

2. **장치명 표준화**
   - 운영 시 장치 display name 규칙을 정하면 인식 오류가 줄어든다.

3. **고위험 작업은 항상 승인 유지**
   - reboot, factory reset은 자동 허용하지 않는 것이 낫다.

4. **all-llm mode는 운영 전 충분히 검증**
   - 현재 구조는 안정적이지만, 정책과 기대 결과를 꼭 확인해야 한다.

5. **문서와 관리자 페이지를 같이 사용**
   - 운영자가 바뀌어도 온보딩이 쉬워진다.

---

## 16. 현재 한계
- 기본적으로 일부 상태는 프로세스 재시작 시 유지되지 않을 수 있음
- 모든 provider가 런타임에서 실제 동작하는 것은 아님
- 자연어 해석은 완전 자유형이 아니라 현재 구현된 intent 범위에 최적화되어 있음
- 장치 capability는 Webex xAPI와 연결된 장치 범위에 제한됨

---

## 17. 추천 시작 시나리오
처음 사용자라면 아래 순서가 가장 안전하다.

1. 앱 실행
2. `POST /debug/messages`로 `list devices` 호출
3. `get status of <device>` 테스트
4. `show room booking for <device>` 테스트
5. `set volume to 20 on <device>`로 승인 흐름 확인
6. 관리자 페이지 접속
7. 필요 시 Webex webhook 및 real device mode 연결

---

## 18. 요약
이 앱은 Webex 디바이스를 자연어로 다루기 위한 운영 도구다.

가장 중요한 사용 포인트는 다음 세 가지다.
- 처음에는 mock mode와 debug API로 검증할 것
- 조회 작업과 변경 작업을 구분해서 운영할 것
- 승인 정책을 적절히 유지할 것

이 세 가지만 지켜도 꽤 안정적으로 운영할 수 있다.
