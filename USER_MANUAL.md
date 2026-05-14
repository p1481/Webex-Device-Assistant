# User Manual

## Purpose

This guide explains how to install, run, test, and operate the Webex Device Assistant App in day-to-day operations.

The app lets users manage supported Webex devices through natural-language requests such as status queries, volume control, meeting join actions, camera mode changes, and more.

---

## Capabilities

### What the app can do today

#### Read operations
- get device status
- get environment info
- get camera mode
- get room booking and OBTP availability
- list organization devices

#### Control operations
- Webex join
- join OBTP for the next joinable scheduled meeting
- dial
- hang up
- send DTMF
- microphone mute
- microphone mode
- volume
- video mute
- selfview
- camera mode
- layout
- presentation start and stop
- input source switch
- matrix assign, unassign, and swap
- display mode and display role
- camera preset activation
- camera position adjustment
- SpeakerTrack
- standby
- reboot
- factory reset

Read-only actions usually run immediately. Most mutating actions are approval-gated by default.

---

## Quick start

### Requirements
- Python 3.12 or newer recommended
- Linux, macOS, or another environment that can run FastAPI and `uvicorn`

### Install
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

### Run locally
```bash
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

### Run tests
```bash
.venv/bin/python -m pytest
```

By default, the repository runs in mock-first mode, so you can validate the flow without real Webex or device credentials.

### Recommended first-use path
1. start the app
2. call `list devices`
3. test `get status of <device>`
4. test `show booking info on <device>`
5. test a mutating action like `set volume to 20 on <device>` and observe approval behavior
6. open the admin page
7. only then enable real Webex and real device mode if needed

---

## Debug API

### Fastest way to use and validate the app
The easiest development and validation entry point is `POST /debug/messages`.

### Get device status
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get status of Board Pro","preferred_mode":"separated"}'
```

This read-only slice returns a best-effort status summary, including values such as mute state, call state, selfview state, presentation mode, system state, and software info when exposed by the device.

### Get environment info
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get environment info of Board Pro","preferred_mode":"separated"}'
```

### Get camera mode
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get camera mode of Board Pro","preferred_mode":"separated"}'
```

### Get room booking and OBTP info
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"show booking info on Board Pro","preferred_mode":"separated"}'
```

### List devices
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"list devices"}'
```

### Join the next OBTP-eligible meeting
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"join obtp on Board Pro","session_id":"join-obtp-demo"}'
```

### Set camera mode
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"set camera mode to frames on Board Pro","session_id":"camera-mode-demo"}'
```

### Reset session context
To clear stored conversation context and pending follow-up state for a session:

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"/reset","session_id":"demo-reset"}'
```

### Execution modes
The app supports two execution modes.

#### `separated`
- execution is handled by `device_executor`
- clearer separation of control-plane and execution responsibilities
- easier to explain in controlled operations

#### `all-llm`
- execution is handled by `direct_tool_adapter`
- current implementation is still deterministic tool dispatch
- useful as an architectural stepping stone toward richer tool-calling flows

### Choose a mode per request
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get status of Desk Pro","preferred_mode":"all-llm"}'
```

Supported values:
- `separated`
- `all-llm`

---

## Natural-language examples

### Read requests
```text
get status of Board Pro
show environment info for Board Pro
what is the camera mode on Board Pro
show booking info on Board Pro
list devices
```

### Meeting and call requests
```text
join obtp on Board Pro
join webex 123456789 on Board Pro
dial user@example.com on Board Pro
hang up on Board Pro
send dtmf 1234 on Board Pro
```

### Audio and video requests
```text
mute microphones on Board Pro
unmute microphones on Board Pro
set microphone mode to voice optimized on Board Pro
set volume to 25 on Board Pro
mute video on Board Pro
turn selfview on on Board Pro
```

### Camera and display requests
```text
set camera mode to frames on Board Pro
set layout to Prominent on Board Pro
start presentation on Board Pro
switch input source to pc on Board Pro
set display mode to dual on Board Pro
activate camera preset 1 on Board Pro
move camera 1 left on Board Pro
```

### System requests
```text
enable speakertrack on Board Pro
activate standby on Board Pro
reboot Board Pro
factory reset Board Pro
```

---

## Follow-up questions

The app does not always guess missing values. For some requests it asks follow-up questions and resumes the pending action.

### Typical supported follow-up fields today
- missing target device
- missing dial address
- missing Webex meeting identifier
- missing volume level

### Example flow
1. send `set volume to 30`
2. the app asks which device to use
3. reply with `Board Pro`
4. the original request continues

In Webex, missing `target_device` can be handled through an Adaptive Card device selector instead of free text only.

---

## Approvals

### Why approvals happen
Most mutating actions are policy-controlled and approval-gated by default.

Typical examples:
- volume changes
- microphone mute changes
- presentation start or stop
- reboot
- factory reset

### Request a mutating action
```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"set volume to 35 on Board Pro","session_id":"demo-approval"}'
```

The response includes approval information instead of immediate execution.

### Approve or reject in debug mode
Approve:
```bash
curl -X POST 'http://127.0.0.1:8000/debug/approvals/<request-id>?approved=true'
```

Reject:
```bash
curl -X POST 'http://127.0.0.1:8000/debug/approvals/<request-id>?approved=false'
```

If approved, the debug flow executes the action immediately and returns the updated approval plus execution result.

### Real Webex approval behavior
In Webex mode, the same pattern is used through Adaptive Cards:
1. request a mutating action
2. receive an approval card
3. click Approve or Reject
4. the server fetches the attachment-action details from Webex
5. if approved, the action executes and a follow-up reply is posted

Approval and admin-login delivery use Webex card attachments plus `attachmentActions` fetch-by-id semantics.

---

## Admin page

### Open the page
```text
http://127.0.0.1:8000/admin-page
```

### What it shows
The admin page is a thin control surface backed by `/admin/*` APIs. It currently exposes:
- runtime settings
- startup status
- provider settings
- action registry
- per-intent policy settings
- organization devices
- approvals
- audit records
- runtime stats

### Related docs pages
- `/admin-page/docs`
- `/admin-page/docs-ko`
- `/admin-page/manuals/ARCHITECTURE.md`
- `/admin-page/manuals/INSTALL.md`
- `/admin-page/manuals/USER_MANUAL.md`
- `/admin-page/manuals/MANUAL_KO.md`

### Admin login flow
Browser admin access is email-based and approval-backed.

1. open `/admin-page`
2. enter an allowed admin email address
3. the app sends a Webex direct approval card to that email
4. approve the request in Webex
5. the browser polls `/admin/auth/status/{session_id}`
6. after approval, the browser receives an admin session cookie and can load protected admin APIs

Current limitation:
- admin browser sessions are process-local and do not survive restart

### Useful admin API examples

#### Get runtime settings
```bash
curl http://127.0.0.1:8000/admin/settings
```

#### Update runtime settings
```bash
curl -X PUT http://127.0.0.1:8000/admin/settings \
  -H 'Content-Type: application/json' \
  -d '{
    "default_execution_mode": "separated",
    "default_user_email": "youngcle@cisco.com",
    "selected_provider": "rule_based",
    "selected_provider_model": "rule-based-default"
  }'
```

#### Get provider settings
```bash
curl http://127.0.0.1:8000/admin/providers
```

#### Update provider settings
```bash
curl -X PUT http://127.0.0.1:8000/admin/providers \
  -H 'Content-Type: application/json' \
  -d '{
    "provider": "rule_based",
    "model": "rule-based-default",
    "enabled": true
  }'
```

#### Get policy list
```bash
curl http://127.0.0.1:8000/admin/policies
```

#### Update a policy
```bash
curl -X PUT http://127.0.0.1:8000/admin/policies/set_volume \
  -H 'Content-Type: application/json' \
  -d '{
    "allowed_modes": ["separated", "all-llm"],
    "risk_level": "low",
    "approval_state": "required",
    "reason": "Volume changes require approval."
  }'
```

#### Read supporting resources
```bash
curl http://127.0.0.1:8000/admin/actions
curl http://127.0.0.1:8000/admin/devices
curl http://127.0.0.1:8000/admin/approvals
curl http://127.0.0.1:8000/admin/audit
curl http://127.0.0.1:8000/admin/stats
```

---

## Real Webex and device setup

### Real Webex setup notes
To use real Webex messaging, you need values such as:
- `WEBEX_MOCK_MODE=false`
- `WEBEX_BOT_TOKEN`
- `WEBEX_BOT_PERSON_ID`
- `WEBEX_WEBHOOK_SECRET`
- `WEBEX_WEBHOOK_TARGET_URL`

Important behavior:
- the webhook target URL must be HTTPS
- the app expects `POST /webhooks/webex/messages` for messages
- the app expects `POST /webhooks/webex/attachment-actions` for card clicks
- the server verifies `X-Spark-Signature`
- the gateway fetches the full message or attachment action from Webex before acting

### Real device setup notes
To use real device execution, you need:
- `DEVICE_MOCK_MODE=false`
- `WEBEX_TOKEN_MANAGER_BASE_URL`
- `WEBEX_TOKEN_MANAGER_API_KEY`

The real path uses Webex Cloud xAPI and device configuration APIs, not a local RoomOS transport path.

Current real behavior includes:
- device resolution through Webex inventory
- orchestration-facing filtering to main room or desk devices that are xAPI-capable
- best-effort status reads
- camera-mode state reads
- room booking and OBTP reads
- mutating operations for the supported command list

For configuration-backed operations, the app prefers inventory `webexDeviceId` for `/v1/deviceConfigurations` when available.

---

## Troubleshooting

### The app starts but device control fails
Check:
- `DEVICE_MOCK_MODE`
- `WEBEX_TOKEN_MANAGER_BASE_URL`
- `WEBEX_TOKEN_MANAGER_API_KEY`
- whether the target device exists in Webex inventory
- whether the device name matches the registered display name

### Webex messages do not arrive
Check:
- `WEBEX_WEBHOOK_TARGET_URL`
- `WEBEX_BOT_TOKEN`
- `WEBEX_BOT_PERSON_ID`
- `WEBEX_WEBHOOK_SECRET`
- webhook registration state

### A device cannot be found
Try:
- using the full device display name
- calling `list devices` first to confirm the exact registered name

### Approval succeeds but execution still fails
Check:
- whether the selected mode is allowed by policy
- whether the approval actually resolved to approved
- whether device resolution failed afterward

---

## Current limits

- Mock mode is still the default operating mode.
- Natural-language coverage is strongest for the patterns implemented in `rule_based.py`.
- Only `rule_based` and `ollama` are currently usable as runtime analysis providers.
- Session memory, pending state, event dedupe, and admin session flags are not restart-safe.
- The camera-mode writable slice is intentionally conservative.
- Booking support is focused on read state plus joining the next confidently joinable meeting.
- The admin page is a thin operational surface, not a full product UI.

---

## Summary

This app is an operations-oriented natural-language interface for Webex devices.

The safest adoption path is to start in mock mode, validate with the debug API, separate read actions from mutating actions, and keep meaningful approval gates for risky operations.
