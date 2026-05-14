# Install Manual

A practical setup guide for running Webex Device Assistant locally, as a Linux service, and with real Webex/device integrations.

## 1. Requirements

Required:

- Python 3.12 or newer
- Linux, macOS, or any environment that can run FastAPI and `uvicorn`

Optional, depending on integration mode:

- Webex bot credentials for real messaging
- Token manager sidecar for real device access
- Ollama when using the `ollama` analysis provider

## 2. Install locally

Create a virtual environment and install the package in editable development mode:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## 3. Run locally in mock mode

The default configuration is mock-first:

- `WEBEX_MOCK_MODE=true`
- `DEVICE_MOCK_MODE=true`

This lets the app start without Webex credentials or real device access.

Start the app:

```bash
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

Check health:

```bash
curl http://127.0.0.1:8000/healthz
```

Run tests:

```bash
.venv/bin/python -m pytest
```

## 4. Persist admin/control-plane state

Set `ADMIN_STATE_PATH` when you want these records to survive restart:

- approval records
- audit records
- runtime admin overrides
- provider settings
- policy overrides

Example:

```bash
ADMIN_STATE_PATH=.local/admin-state.json .venv/bin/python -m uvicorn assistant_app.main:app --reload
```

`ADMIN_STATE_PATH` does **not** persist:

- session memory
- processed webhook dedupe
- admin session flags
- organization device cache
- process stats

## 5. Install as a Linux systemd service

The repo includes deployment files for the host:

- `.deploy/webex-device-assistant.service`
- `.deploy/webex-device-assistant.env`

Install or refresh the service:

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

The checked-in unit:

- binds FastAPI to `127.0.0.1:8000`
- reads runtime settings from `.deploy/webex-device-assistant.env`
- matches the deployed nginx proxy that forwards `/admin-page/*`, `/admin/*`, `/healthz`, and Webex webhook paths to that upstream

## 6. Mock-mode smoke checks

### 6.1 Read device status

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"get status of RoomKit-7F","preferred_mode":"separated"}'
```

### 6.2 List devices

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"list devices"}'
```

### 6.3 Create an approval request

```bash
curl -X POST http://127.0.0.1:8000/debug/messages \
  -H 'Content-Type: application/json' \
  -d '{"text":"set volume to 35 on Board Pro","session_id":"demo-approval"}'
```

### 6.4 Resolve the approval in debug mode

```bash
curl -X POST 'http://127.0.0.1:8000/debug/approvals/<request-id>?approved=true'
```

## 7. Configure real Webex messaging

Set these values to turn off Webex mock mode:

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

Startup behavior:

- The app validates the configured bot person id against `GET /v1/people/me`.
- A startup identity mismatch raises an error and blocks startup.
- Other startup Webex identity failures are logged, and startup continues.

## 8. Reconcile Webex webhooks on startup

To let the app reconcile its message webhooks on startup, also set:

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

Important: `WEBEX_WEBHOOK_TARGET_URL` must be HTTPS when provided.

## 9. Configure real Webex approval cards

The app can send approval cards in real Webex mode. Card clicks require a separate Webex webhook for attachment actions.

Register a Webex `attachmentActions.created` webhook that targets:

```text
POST /webhooks/webex/attachment-actions
```

After a card click, the app:

1. fetches attachment-action details by id
2. resolves the stored approval
3. executes the attached action request when the decision is approve
4. sends a follow-up reply to the room

## 10. Configure real device access

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

## 11. Configure Ollama analysis

Use Ollama when you want local LLM-backed intent analysis.

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

## 12. Useful admin endpoints

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

## 13. Troubleshooting checklist

### App does not start

Check:

- Python version
- virtualenv activation/install state
- `WEBEX_MOCK_MODE`
- Webex bot identity variables when `WEBEX_MOCK_MODE=false`

### Webex messages do not arrive

Check:

- `WEBEX_WEBHOOK_TARGET_URL`
- `WEBEX_BOT_TOKEN`
- `WEBEX_BOT_PERSON_ID`
- `WEBEX_WEBHOOK_SECRET`
- webhook registration state
- HTTPS reachability from Webex

### Device control fails

Check:

- `DEVICE_MOCK_MODE`
- `WEBEX_TOKEN_MANAGER_BASE_URL`
- `WEBEX_TOKEN_MANAGER_API_KEY`
- target device display name
- whether the device supports the requested xAPI command/configuration

## 14. Current install/runtime limits

- Mock mode is the easiest supported starting point.
- Real Webex approval handling needs both message webhooks and attachment-action webhooks.
- Real device mode depends on the token manager sidecar.
- The repository does not include local RoomOS credentials or transport.
