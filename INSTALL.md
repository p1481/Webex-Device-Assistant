# Install Manual

## Requirements

- Python 3.12 or newer
- Linux, macOS, or another environment that can run FastAPI and `uvicorn`

Optional for real integrations:

- Webex bot credentials for real messaging
- Token manager sidecar for real device access
- Ollama if you want to use the `ollama` analysis provider

## Local install

Create the virtual environment and install the package in editable mode:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Default local run

The default configuration is mock-first:

- `WEBEX_MOCK_MODE=true`
- `DEVICE_MOCK_MODE=true`

Start the app:

```bash
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

Check health:

```bash
curl http://127.0.0.1:8000/healthz
```

## Optional durable control-plane state

If you want approval records, audit records, runtime admin overrides, provider settings, and policy overrides to survive restart, set `ADMIN_STATE_PATH`:

```bash
ADMIN_STATE_PATH=.local/admin-state.json .venv/bin/python -m uvicorn assistant_app.main:app --reload
```

This file does not persist session memory, processed webhook dedupe, admin session flags, org device cache, or process stats.

## Durable Linux service for the deployed host

This repository now includes a checked-in systemd unit for the app:

- `.deploy/webex-device-assistant.service`
- `.deploy/webex-device-assistant.env`

Install or refresh the service on the host:

```bash
sudo install -m 0644 \
  "/home/p1481/youngcle_code/06. Device Assistant/.deploy/webex-device-assistant.service" \
  /etc/systemd/system/webex-device-assistant.service
sudo systemctl daemon-reload
sudo systemctl enable --now webex-device-assistant.service
```

Useful service commands:

```bash
sudo systemctl restart webex-device-assistant.service
sudo systemctl status webex-device-assistant.service --no-pager
sudo journalctl -u webex-device-assistant.service -n 100 --no-pager
```

The checked-in unit binds the FastAPI app to `127.0.0.1:8000` and sources runtime settings from `.deploy/webex-device-assistant.env`. This matches the deployed nginx proxy that forwards `/admin-page/*`, `/admin/*`, `/healthz`, and Webex webhook paths to that upstream.

## Verification

Run tests:

```bash
.venv/bin/python -m pytest
```

## Mock-mode smoke checks

Read-only status request:

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get status of RoomKit-7F","preferred_mode":"separated"}'
```

List devices:

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"list devices"}'
```

Create an approval request:

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"set volume to 35 on Board Pro","session_id":"demo-approval"}'
```

Resolve that approval in debug mode:

```bash
curl -X POST 'http://127.0.0.1:8000/debug/approvals/<request-id>?approved=true'
```

## Real Webex messaging setup

Set these to turn off Webex mock mode:

- `WEBEX_MOCK_MODE=false`
- `WEBEX_BOT_TOKEN`
- `WEBEX_BOT_PERSON_ID`
- `WEBEX_WEBHOOK_SECRET`

Example:

```bash
WEBEX_MOCK_MODE=false \
WEBEX_BOT_TOKEN=... \
WEBEX_BOT_PERSON_ID=... \
WEBEX_WEBHOOK_SECRET=... \
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

Notes:

- The app validates the configured bot person id against `GET /v1/people/me` at startup.
- A startup identity mismatch raises an error and blocks startup.
- Other startup Webex identity failures are logged and startup continues.

## Optional Webex webhook reconciliation on startup

If you want the app to reconcile its message webhooks on startup, also set:

- `WEBEX_WEBHOOK_RECONCILE_ON_STARTUP=true`
- `WEBEX_WEBHOOK_TARGET_URL=https://.../webhooks/webex/messages`

Example:

```bash
WEBEX_MOCK_MODE=false \
WEBEX_BOT_TOKEN=... \
WEBEX_BOT_PERSON_ID=... \
WEBEX_WEBHOOK_SECRET=... \
WEBEX_WEBHOOK_RECONCILE_ON_STARTUP=true \
WEBEX_WEBHOOK_TARGET_URL=https://example.com/webhooks/webex/messages \
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

Current desired message webhook set:

- `roomType=direct`
- `roomType=group&mentionedPeople=me`

The target URL must be HTTPS when provided.

## Real approval card setup in Webex

The app can send approval cards in real Webex mode, but you also need to register a separate Webex webhook for attachment actions.

Register a Webex `attachmentActions.created` webhook that targets:

```text
POST /webhooks/webex/attachment-actions
```

Current behavior after a card click:

- the app fetches attachment-action details by id
- resolves the stored approval
- executes the attached action request when the decision is approve
- sends a follow-up reply to the room

## Real device access setup

Set this to turn off device mock mode:

- `DEVICE_MOCK_MODE=false`

Real device mode also requires token-manager settings:

- `WEBEX_TOKEN_MANAGER_BASE_URL`
- `WEBEX_TOKEN_MANAGER_API_KEY`

Example:

```bash
DEVICE_MOCK_MODE=false \
WEBEX_TOKEN_MANAGER_BASE_URL=http://127.0.0.1:3000 \
WEBEX_TOKEN_MANAGER_API_KEY=... \
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

Notes:

- Real device access uses Webex cloud xAPI and device configuration APIs.
- The app fetches a bearer token from `GET /api/tokens/current` on the token manager.
- This is separate from the direct bot-token path used for messaging APIs.

## Optional Ollama setup

If you want the analysis provider to use Ollama, make sure Ollama is reachable and the model exists.

Relevant settings:

- `DEFAULT_PROVIDER=ollama`
- `DEFAULT_PROVIDER_MODEL`, default `gemma4:latest`
- `DEFAULT_PROVIDER_BASE_URL`, default `http://127.0.0.1:11434/api`

Example:

```bash
DEFAULT_PROVIDER=ollama \
DEFAULT_PROVIDER_MODEL=gemma4:latest \
DEFAULT_PROVIDER_BASE_URL=http://127.0.0.1:11434/api \
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

The admin API can also switch to `ollama` live if the base URL is reachable and the model is installed.

## Useful admin endpoints

```bash
curl http://127.0.0.1:8000/admin/settings
curl http://127.0.0.1:8000/admin/providers
curl http://127.0.0.1:8000/admin/policies
curl http://127.0.0.1:8000/admin/actions
curl http://127.0.0.1:8000/admin/devices
curl http://127.0.0.1:8000/admin/approvals
curl http://127.0.0.1:8000/admin/audit
curl http://127.0.0.1:8000/admin/stats
curl http://127.0.0.1:8000/admin-page/healthz
```

## Current install and runtime limits

- Mock mode is the easiest supported starting point.
- Real Webex approval handling needs both message webhooks and attachment-action webhooks.
- Real device mode depends on the token manager sidecar.
- The repository does not include local RoomOS credentials or transport.
