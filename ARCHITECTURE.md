# Architecture Manual

> Current reference for the running FastAPI service, admin page, Webex cloud xAPI integration, LLM provider wiring, configuration, and supported user workflows.

## 1. Purpose

Webex Device Assistant is a FastAPI application that converts natural-language requests into safe Cisco Webex RoomOS device actions.

It supports two main entry paths:

1. **Local/debug usage** through HTTP endpoints such as `POST /debug/messages`.
2. **Real Webex usage** through message and attachment-action webhooks.

The app keeps decision-making, policy/approval, and device execution separated so that read-only questions can run immediately while mutating device actions can be reviewed through approval cards or admin controls.

### Core architecture constraints

- Read-only questions should run immediately when policy allows.
- Mutating device actions should remain reviewable through approval cards or admin controls.
- **Separated mode** remains the safest default architecture.
- **All-LLM mode** still operates on canonical validated requests and the same device action path.
- The execution-mode difference is execution ownership, not user experience.

## 2. Architecture Diagram

```text
User / Webex message / Debug API
        |
        v
FastAPI app: assistant_app.main
        |
        +--> ProviderRegistry
        |       +--> RuleBasedProvider
        |       +--> OllamaProvider
        |
        +--> Orchestrator
        |       +--> intent proposal
        |       +--> slot extraction
        |       +--> cards / approval prompts
        |
        +--> PolicyStore + ApprovalStore
        |       +--> per-intent execution mode
        |       +--> approval-required flag
        |
        +--> ModeRouter
                +--> separated mode: DeviceExecutor -> DeviceClient -> Webex cloud xAPI
                +--> all-LLM mode: AllLlmToolRuntime -> execute_device_action tool -> DirectToolAdapter -> DeviceClient

Admin browser UI
        |
        +--> /admin-page static HTML/CSS/JS
        +--> /admin/* JSON APIs
        +--> /admin-page/manuals/* markdown files
```

## 3. Modules and Runtime Services

### 3.1 FastAPI service

- **Entrypoint:** `assistant_app.main:app`
- **Typical dev command:**

```bash
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

- **Health check:** `GET /healthz`
- **Admin UI:** `GET /admin-page`

### 3.2 Assistant app layer

- `assistant_app/main.py`
  - Creates the FastAPI app.
  - Registers debug, webhook, admin, and admin-page routes.
  - Wires config, provider registry, orchestration, policy store, approval store, audit store, and device execution.
- `assistant_app/orchestrator.py`
  - Converts incoming text into canonical `ActionProposal` objects.
  - Handles card selection and pending-action follow-up.
  - Builds confirmation/approval UX for mutating actions.
- `assistant_app/provider_registry.py`
  - Describes available providers.
  - Builds rule-based and Ollama providers.
- `assistant_app/providers/rule_based.py`
  - Deterministic parser for common Korean/English device-control phrases.
- `assistant_app/providers/ollama.py`
  - Local LLM-backed parser and structured proposal normalizer.
- `assistant_app/mode_router.py`
  - Routes canonical execution requests into separated mode or all-LLM mode.
- `assistant_app/agentic_tool_runtime.py`
  - In all-LLM mode, requires the provider to call exactly one allowed `execute_device_action` tool before direct execution.

### 3.3 Device execution layer

- `device_executor/executor.py`
  - Separated-mode executor wrapper.
- `device_executor/handlers.py`
  - Maps every supported intent to a `DeviceClient` method.
- `device_executor/device_client.py`
  - Resolves Webex devices.
  - Reads statuses.
  - Executes RoomOS xCommands through Webex cloud xAPI.
  - Patches device configurations when needed.
- `direct_tool_adapter/adapter.py`
  - all-LLM execution adapter; still uses canonical validated requests and the same `DeviceClient` action path.

### 3.4 Shared contracts

- `shared/contracts/actions.py`
  - Intents, action payloads, camera/display enums, and action proposal schema.
- `shared/contracts/execution.py`
  - Execution requests/results and execution status.
- `shared/contracts/admin.py`
  - Admin settings, policies, approvals, provider descriptors.
- `shared/contracts/conversation.py`
  - Chat/provider request and response contracts.

### 3.5 Admin page

- `admin_page/api.py`
  - Serves static admin pages under `/admin-page`.
  - Serves markdown manuals through `/admin-page/manuals/{manual_name}`.
- `admin_page/static/index.html`
  - Main control dashboard.
- `admin_page/static/docs.html`
  - Manual index page.
- `admin_page/static/docs-ko.html`
  - Korean guide page.
- `admin_page/static/architecture-guide.html`
  - Browser-friendly architecture and operations guide generated from this document.

## 4. API Surface

### 4.1 Health and debug

- `GET /healthz`
  - Returns service status plus default execution/mock-mode indicators.
- `GET /debug/webex/runtime`
  - Shows runtime diagnostics for Webex integration.
- `POST /debug/messages`
  - Sends a local text request through the same orchestration path.
  - Useful for testing without Webex.

Example:

```bash
curl -sS -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  --data '{"text":"Room Bar 상태 확인","preferred_mode":"all-llm","session_id":"local-test"}'
```

- `POST /debug/webex/simulate-message`
  - Simulates a Webex message payload.
- `POST /debug/approvals/{request_id}`
  - Approves/rejects approval requests during local testing.

### 4.2 Webex webhooks

- `POST /webhooks/webex/messages`
  - Handles real Webex message-created webhooks.
- `POST /webhooks/webex/attachment-actions`
  - Handles adaptive-card button selections, including approvals and card-mode choices.

### 4.3 Admin APIs

- `POST /admin/auth/start`
  - Starts admin authentication/session flow.
- `GET /admin/auth/status/{session_id}`
  - Checks admin auth session status.
- `POST /admin/auth/logout`
  - Clears admin session.
- `GET /admin/providers`
  - Lists available provider descriptors.
- `GET /admin/settings`
  - Returns active admin/runtime settings.
- `GET /admin/policies`
  - Lists per-intent policy configuration.
- `PATCH /admin/policies/{intent}`
  - Updates a specific policy.
- `GET /admin/approvals`
  - Lists pending/recent approval requests.
- `GET /admin/audit`
  - Lists recent audit events.
- `GET /admin/actions`
  - Lists supported actions and default policy metadata.
- `GET /admin/devices`
  - Lists Webex organization devices or mock devices.
- `GET /admin/stats`
  - Returns process-local counters and runtime stats.

### 4.4 Admin-page static routes

- `GET /admin-page`
  - Main dashboard.
- `GET /admin-page/docs`
  - Documentation index.
- `GET /admin-page/docs-ko`
  - Korean browser guide.
- `GET /admin-page/architecture-guide`
  - HTML architecture and operations guide.
- `GET /admin-page/manuals/ARCHITECTURE.md`
  - Markdown source for the architecture HTML guide.
- `GET /admin-page/manuals/{INSTALL.md|USER_MANUAL.md|MANUAL_KO.md}`
  - Additional top-level manuals.

## 5. Configuration

Configuration is read from environment variables in `assistant_app/config.py`.

### 5.1 Core runtime

- `ADMIN_STATE_PATH`
  - Optional path for persisted admin state.
- `DEFAULT_EXECUTION_MODE`
  - `separated` or `all-llm`.
  - Default: `separated`.
- `DEFAULT_TARGET_DEVICE`
  - Device name used when the user does not specify a target.

### 5.2 Provider / LLM

- `DEFAULT_PROVIDER`
  - `rule-based` or `ollama` are implemented for runtime analysis.
  - Provider descriptors also advertise OpenAI, Gemini, and Anthropic, but runtime analysis currently builds rule-based or Ollama providers.
- `DEFAULT_PROVIDER_MODEL`
  - Model name for selected provider.
- `DEFAULT_PROVIDER_BASE_URL`
  - Provider base URL. For Ollama this defaults to the local Ollama base URL.

### 5.3 Webex ingress

- `WEBEX_MOCK_MODE`
  - `true` by default.
  - When `false`, Webex bot token/person id/webhook secret validation is required.
- `WEBEX_API_BASE`
  - Default: `https://webexapis.com/v1`.
- `WEBEX_BOT_TOKEN`
  - Bot token for Webex messaging.
- `WEBEX_BOT_PERSON_ID`
  - Bot person id used to ignore self messages.
- `WEBEX_WEBHOOK_SECRET`
  - Shared secret for webhook validation.
- `WEBEX_WEBHOOK_TARGET_URL`
  - Public HTTPS URL for webhook reconciliation.
- `WEBEX_WEBHOOK_RECONCILE_ON_STARTUP`
  - If enabled, startup checks/creates expected Webex webhooks.
- `WEBEX_WEBHOOK_NAME`, `WEBEX_WEBHOOK_DIRECT_NAME`, `WEBEX_WEBHOOK_GROUP_NAME`
  - Names used for managed webhooks.
- `WEBEX_WEBHOOK_RESOURCE`
  - Must be `messages`.
- `WEBEX_WEBHOOK_EVENT`
  - Must be `created`.
- `WEBEX_WEBHOOK_FILTER`
  - Optional Webex webhook filter.

### 5.4 Device execution

- `DEVICE_MOCK_MODE`
  - `true` by default.
  - When `false`, real Webex device xAPI access is used.
- `WEBEX_TOKEN_MANAGER_BASE_URL`
  - Token manager sidecar base URL.
  - Default: `http://127.0.0.1:3000`.
- `WEBEX_TOKEN_MANAGER_API_KEY`
  - API key for token manager sidecar.

Real device mode uses these Webex cloud APIs:

- `GET /v1/devices`
- `GET /v1/xapi/status`
- `POST /v1/xapi/command/{commandKey}`
- `PATCH /v1/deviceConfigurations`

## 6. LLM Integration

### 6.1 Provider modes

The runtime has two practical analysis providers:

1. **Rule-based provider**
   - Deterministic parser.
   - Fast and predictable.
   - Good for known Korean/English command phrases.

2. **Ollama provider**
   - Local LLM provider.
   - Generates structured action proposals.
   - Normalizes model output into strict shared contracts.

### 6.2 Execution modes

1. **Separated mode**
   - LLM/provider proposes an action.
   - App policy/approval produces a canonical `ExecutionRequest`.
   - `DeviceExecutor` executes the request.
   - This is the safest and default architecture.

2. **All-LLM mode**
   - App still creates a canonical request and applies policy/approval.
   - LLM runtime must call a single allowed tool: `execute_device_action`.
   - Tool arguments are validated against request id, intent, and target device.
   - Direct adapter executes the same canonical device action.

## 7. Supported Features

### 7.1 Read-only features

- **Get status**
  - Example: `Room Bar 상태 알려줘`
  - Reads product/platform, network, volume, mic state, call state, presentation state, selfview, SpeakerTrack, standby, etc.
- **Get environment info**
  - Example: `Room Bar 온도랑 습도 알려줘`
  - Reads room analytics such as temperature, humidity, ambient noise, people count, air-quality index when available.
- **Get camera mode**
  - Example: `Room Bar 카메라 모드 조회`
  - Reads observed camera/SpeakerTrack-related status.
- **Get room booking**
  - Example: `Room Bar 다음 회의 알려줘`
  - Reads room availability and upcoming booking information.
- **List devices**
  - Example: `장비 목록 보여줘`
  - Lists Webex organization devices or mock devices.

### 7.2 Meeting and call control

- **Webex join**
  - Example: `Room Bar에서 123456789 미팅 조인해줘`
- **Join OBTP**
  - Example: `Room Bar 다음 회의 참가해줘`
- **Dial**
  - Example: `Room Bar에서 user@example.com으로 전화 걸어줘`
- **Hang up**
  - Example: `Room Bar 통화 종료`
- **Send DTMF**
  - Example: `Room Bar에서 DTMF 1234 보내줘`

### 7.3 Audio and video controls

- **Microphone mute/unmute**
  - Example: `Room Bar 마이크 음소거`
- **Microphone mode**
  - Example: `Room Bar 마이크 모드 music으로 바꿔줘`
- **Volume**
  - Example: `Room Bar 볼륨 50으로 설정`
- **Video mute/unmute**
  - Example: `Room Bar 비디오 끄기`
- **Selfview**
  - Example: `Room Bar 셀프뷰 켜줘`

### 7.4 Camera controls

- **Camera mode**
  - Uses RoomOS command `Cameras.SpeakerTrack.Set`.
  - Supported `Behavior` values:
    - `Manual`
    - `Dynamic`
    - `BestOverview`
    - `Closeup`
    - `Frames`
    - `GroupAndSpeaker`
  - Example: `Room Bar 카메라 모드 Frames로 변경`
  - Webex xAPI command payload:

```json
{
  "deviceId": "...",
  "arguments": {
    "Behavior": "Frames"
  }
}
```

- **Activate camera preset**
  - Example: `Room Bar 카메라 프리셋 2번 실행`
- **Adjust camera position**
  - Example: `Room Bar 카메라 오른쪽으로 조금 이동하고 줌 인`
- **SpeakerTrack on/off**
  - Example: `Room Bar SpeakerTrack 켜줘`

### 7.5 Layout, presentation, and routing

- **Set video layout**
  - Example: `Room Bar 레이아웃 Grid로 변경`
- **Start/stop presentation**
  - Example: `Room Bar 프레젠테이션 시작`
- **Switch input source**
  - Example: `Room Bar 입력 2번으로 전환`
- **Video matrix assign/unassign/swap**
  - Example: `Room Bar matrix output 1에 source 2 assign`

### 7.6 Display mode

Display mode uses `Configuration.Video.Output.Connector[n].MonitorRole` configuration patches.

Supported card choices:

- `왼쪽영상, 오른쪽영상`
  - Connector 1: `First`
  - Connector 2: `Second`
- `왼쪽영상, 오른쪽프리젠테이션`
  - Connector 1: `First`
  - Connector 2: `PresentationOnly`
- `왼쪽프리젠테이션, 오른쪽영상`
  - Connector 1: `PresentationOnly`
  - Connector 2: `First`
- `양쪽모두 프리젠테이션`
  - Connector 1: `PresentationOnly`
  - Connector 2: `PresentationOnly`

### 7.7 Device power and maintenance

- **Standby on/off**
  - Example: `Room Bar 대기모드로 전환`
- **Reboot**
  - Example: `Room Bar 재부팅`
- **Factory reset**
  - Example: `Room Bar factory reset`
  - Requires explicit acknowledgement in the action contract.

## 8. Approval and Policy Behavior

Each action has a policy entry:

- `selected_mode`: `separated` or `all-llm`
- `approval_required`: whether approval is needed before execution
- supported mode list from the action registry

Default behavior:

- Read-only actions generally do **not** require approval.
- Mutating actions generally require approval.
- `reboot` and `factory_reset` are separated-mode only.

Admin users can review and adjust policies in `/admin-page` or through `/admin/policies` APIs.

## 9. Admin Page

Open:

```text
http://127.0.0.1:8000/admin-page
```

The admin page shows:

- runtime settings
- provider settings
- default execution mode
- action registry
- policy controls
- organization device inventory
- approval queue
- audit events
- process stats
- documentation links

Docs:

- `/admin-page/docs`
- `/admin-page/docs-ko`
- `/admin-page/architecture-guide`
- `/admin-page/manuals/ARCHITECTURE.md`

## 10. Development Commands

Create and run locally:

```bash
cd "/home/p1481/youngcle_code/06. Device Assistant"
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

Run checks:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m pyright
```

Smoke test:

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  --data '{"text":"Room Bar 카메라 모드 변경","preferred_mode":"all-llm","session_id":"smoke"}'
```

## 11. Operational Notes and Warnings

- Mock mode is intentionally the default so the app starts without live Webex credentials.
- Real device execution requires `DEVICE_MOCK_MODE=false` and token-manager configuration.
- Real Webex ingress requires `WEBEX_MOCK_MODE=false` and Webex bot/webhook configuration.
- Mutating device actions should remain approval-gated unless a trusted operator intentionally changes policy.
- Webex cloud xAPI responses and RoomOS capability support can vary by device model and software version.

## 12. Concise Summary

Webex Device Assistant is a FastAPI-based orchestration service that accepts debug or Webex inputs, turns them into canonical action requests, enforces policy and approval, and executes device operations through either separated mode or all-LLM mode against Webex cloud xAPI. The safest default is separated mode with approval for mutating actions, while the admin page and debug endpoints provide the primary operator surface for configuration, inspection, and local testing.
