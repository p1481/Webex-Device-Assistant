# Webex Device Assistant

Natural-language assistant for controlling Cisco Webex RoomOS devices through Webex cloud xAPI, with policy/approval guardrails and an admin browser UI.

## What this project does

Webex Device Assistant receives a user message such as:

```text
Room Bar 카메라 모드 Frames로 변경
Room Bar 상태 알려줘
Room Bar 다음 회의 참가해줘
```

It then:

1. Parses the request with a rule-based provider or a local Ollama LLM provider.
2. Converts the request into a canonical action contract.
3. Applies per-intent policy and approval rules.
4. Executes the action through Webex cloud xAPI or returns a read-only status response.
5. Surfaces settings, policies, devices, approvals, audit records, and documentation in the admin page.

## Current architecture

```text
User / Debug API / Webex webhook
        |
        v
FastAPI app: assistant_app.main
        |
        +--> ProviderRegistry: rule-based or Ollama
        +--> Orchestrator: intent, slots, cards, pending actions
        +--> PolicyStore / ApprovalStore / AuditStore
        +--> ModeRouter
                +--> separated mode: DeviceExecutor -> DeviceClient -> Webex cloud xAPI
                +--> all-LLM mode: AllLlmToolRuntime -> execute_device_action -> DirectToolAdapter

Admin UI: /admin-page
Docs: /admin-page/docs, /admin-page/architecture-guide
```

For the detailed current-state document, see:

- [`ARCHITECTURE_CURRENT.md`](ARCHITECTURE_CURRENT.md)
- Browser HTML: `/admin-page/architecture-guide`
- Documentation index: `/admin-page/docs`

## Main features

### Read-only

- Device status
- Environment/room analytics
- Camera mode observation
- Room booking / OBTP status
- Organization device list

### Meeting and call control

- Join Webex meeting
- Join next OBTP meeting
- Dial SIP/address
- Hang up
- Send DTMF

### Audio/video controls

- Microphone mute/unmute
- Microphone processing mode
- Volume
- Main video mute/unmute
- Selfview on/off

### Camera and display controls

- Camera mode via RoomOS command:

```text
Cameras.SpeakerTrack.Set
```

Supported `Behavior` values:

- `Manual`
- `Dynamic`
- `BestOverview`
- `Closeup`
- `Frames`
- `GroupAndSpeaker`

- Camera preset activation
- Camera pan/tilt/zoom step adjustments
- SpeakerTrack on/off
- Video layout changes
- Presentation start/stop
- Input-source switching
- Video matrix assign/unassign/swap
- Display mode via:

```text
Configuration.Video.Output.Connector[n].MonitorRole
```

Display card choices:

- `왼쪽영상, 오른쪽영상`
- `왼쪽영상, 오른쪽프리젠테이션`
- `왼쪽프리젠테이션, 오른쪽영상`
- `양쪽모두 프리젠테이션`

### Maintenance

- Standby on/off
- Reboot
- Factory reset

## Execution modes

### `separated`

Default and safest mode.

- Provider proposes an action.
- App validates the canonical action.
- Policy/approval is applied.
- `DeviceExecutor` executes the action through `DeviceClient`.

### `all-llm`

LLM-assisted execution mode.

- App still creates a canonical action and applies policy/approval.
- LLM runtime must call exactly one allowed tool: `execute_device_action`.
- Tool arguments are validated before device execution.
- The same `DeviceClient` path performs the actual Webex xAPI call.

## Quick start

```bash
cd "/home/p1481/youngcle_code/06. Device Assistant"
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/admin-page
```

Health check:

```bash
curl -sS http://127.0.0.1:8000/healthz
```

Local debug message:

```bash
curl -sS -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  --data '{"text":"Room Bar 상태 알려줘","preferred_mode":"separated","session_id":"local-test"}'
```

Camera-mode card smoke test:

```bash
curl -sS -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  --data '{"text":"Room Bar 카메라 모드 변경","preferred_mode":"all-llm","session_id":"camera-card"}'
```

## Configuration

The app reads environment variables in `assistant_app/config.py`.

### Core

- `ADMIN_STATE_PATH`: optional persisted admin-state path.
- `DEFAULT_EXECUTION_MODE`: `separated` or `all-llm`; default `separated`.
- `DEFAULT_TARGET_DEVICE`: fallback target device.

### Provider / LLM

- `DEFAULT_PROVIDER`: `rule-based` or `ollama` are implemented for runtime analysis.
- `DEFAULT_PROVIDER_MODEL`: model name.
- `DEFAULT_PROVIDER_BASE_URL`: provider base URL. Ollama defaults to the local Ollama URL.

### Webex ingress

- `WEBEX_MOCK_MODE`: defaults to `true`.
- `WEBEX_API_BASE`: defaults to `https://webexapis.com/v1`.
- `WEBEX_BOT_TOKEN`: Webex bot token.
- `WEBEX_BOT_PERSON_ID`: bot person id.
- `WEBEX_WEBHOOK_SECRET`: webhook shared secret.
- `WEBEX_WEBHOOK_TARGET_URL`: public HTTPS webhook URL.
- `WEBEX_WEBHOOK_RECONCILE_ON_STARTUP`: create/update expected webhooks on startup when enabled.

### Device execution

- `DEVICE_MOCK_MODE`: defaults to `true`.
- `WEBEX_TOKEN_MANAGER_BASE_URL`: token manager sidecar URL.
- `WEBEX_TOKEN_MANAGER_API_KEY`: token manager sidecar key.

Real Webex/device operation normally requires:

```bash
export WEBEX_MOCK_MODE=false
export DEVICE_MOCK_MODE=false
export WEBEX_BOT_TOKEN=...
export WEBEX_BOT_PERSON_ID=...
export WEBEX_WEBHOOK_SECRET=...
export WEBEX_TOKEN_MANAGER_BASE_URL=http://127.0.0.1:3000
export WEBEX_TOKEN_MANAGER_API_KEY=...
```

## HTTP routes

### Service/debug

- `GET /healthz`
- `GET /debug/webex/runtime`
- `POST /debug/messages`
- `POST /debug/webex/simulate-message`
- `POST /debug/approvals/{request_id}`

### Webex webhooks

- `POST /webhooks/webex/messages`
- `POST /webhooks/webex/attachment-actions`

### Admin APIs

- `POST /admin/auth/start`
- `GET /admin/auth/status/{session_id}`
- `POST /admin/auth/logout`
- `GET /admin/providers`
- `GET /admin/settings`
- `GET /admin/policies`
- `PATCH /admin/policies/{intent}`
- `GET /admin/approvals`
- `GET /admin/audit`
- `GET /admin/actions`
- `GET /admin/devices`
- `GET /admin/stats`

### Admin pages/docs

- `GET /admin-page`
- `GET /admin-page/docs`
- `GET /admin-page/docs-ko`
- `GET /admin-page/architecture-guide`
- `GET /admin-page/manuals/ARCHITECTURE_CURRENT.md`

## Project layout

```text
assistant_app/        FastAPI app, orchestration, providers, policy/admin wiring
device_executor/     Webex device execution and cloud xAPI client
direct_tool_adapter/ all-LLM direct execution adapter
shared/contracts/    Pydantic/dataclass contracts for actions, admin, execution, chat
admin_page/          Static admin UI and docs route definitions
tests/               Pytest suite
```

## Development checks

Run before committing:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m pyright
```

Useful service checks:

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/admin-page/healthz
```

## Documentation

- [`ARCHITECTURE_CURRENT.md`](ARCHITECTURE_CURRENT.md): current service/API/config/LLM/feature guide.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): earlier architecture manual.
- [`INSTALL.md`](INSTALL.md): install and setup guide.
- [`USER_MANUAL.md`](USER_MANUAL.md): user-facing usage guide.
- [`MANUAL_KO.md`](MANUAL_KO.md): Korean companion guide.
- `/admin-page/architecture-guide`: HTML current guide in the admin UI.
- `/admin-page/docs`: browser documentation index.

## Operational notes

- Mock-first defaults are intentional for local development.
- Real device actions require token-manager access and Webex cloud xAPI permissions.
- Mutating actions are approval-gated by default.
- Device support varies by RoomOS model/software version, especially for camera/display features.
