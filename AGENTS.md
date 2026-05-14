# AGENTS.md

Repo-specific guidance for coding agents working on Webex Device Assistant.

## 1. Current repo state

- This repository contains a Python/FastAPI scaffold for the Webex Device Assistant App.
- The workspace is a git repository.
- Keep local secrets, runtime state, virtualenvs, build outputs, and caches ignored.
- Checked-in example config is mock-first for Webex and device integrations.
- Local deployment env files may switch mock modes off and must stay untracked.
- The current real device path is Webex cloud xAPI over HTTPS, not local RoomOS transport.

## 2. Source of truth

Prefer executable sources over prose:

- `pyproject.toml`
- package code under `assistant_app/`, `device_executor/`, `direct_tool_adapter/`, `admin_page/`, and `shared/`
- tests under `tests/`

Reference docs:

- `opencode_webex_device_prompt.md` is the product-spec reference for intended future scope.
- Markdown specs must stay aligned with code when architecture requirements change.

## 3. Architecture constraints to preserve

- The Assistant App is always the LLM-first conversational layer.
- Both execution modes must exist:
  - **Separated Mode**: Assistant App orchestrates; `device_executor` performs execution.
  - **All LLM Mode**: Assistant App orchestrates; `direct_tool_adapter` may execute.
- The difference between modes is execution ownership, not user experience.
- Keep LLM provider integration swappable.
- Do not hardcode a single provider into orchestration.
- Keep approval and policy decisions explicit.
- High-risk actions should default to separated mode with approval.

## 4. Module boundaries

Keep the documented target structure intact:

- `assistant_app/`
- `device_executor/`
- `direct_tool_adapter/`
- `admin_page/`
- `shared/`

Do not collapse orchestration, execution, and transport concerns into one module.

`admin_page/` should stay thin. Backend policy, provider, and auth logic belongs behind APIs in `assistant_app/` and shared services.

## 5. Default implementation order

1. Extend shared canonical contracts first, especially between Assistant App and execution backends.
2. Keep the thin end-to-end `get_status` flow working before adding broader command coverage.
3. Add approval handling and executor safety checks before exposing mutating device actions.
4. Keep the admin page thin; put policy, provider, and auth logic behind backend APIs first.

## 6. Verified developer commands

Create the local virtualenv and install dependencies:

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"
```

Run the app locally:

```bash
.venv/bin/python -m uvicorn assistant_app.main:app --reload
```

Run tests:

```bash
.venv/bin/python -m pytest
```

Type-checking note:

- `pyrightconfig.json` excludes `.venv`, so type-checking should target repo code only.

## 7. Repo-specific guardrails

### Webex ingress

- Webex webhook handling lives in `assistant_app/webhook_controller.py` and `assistant_app/webex_gateway.py`.
- Keep ingress thin: verify the raw webhook signature first, then normalize inbound messages.
- The desired Webex webhook set is two `messages.created` subscriptions:
  - `roomType=direct`
  - `roomType=group&mentionedPeople=me`
- Reconcile only app-owned hooks for those exact desired filters.

### Cards and approvals

- Approval and admin-login delivery should use Webex card attachments plus `attachmentActions` fetch-by-id semantics.
- Do not assume the submit payload is present directly in the webhook body.
- Real approval-card handling needs `attachmentActions` webhook registration and server-side click authorization.

### Gateway filtering

Keep gateway-side filtering in `assistant_app/webex_gateway.py`:

- drop self-messages
- drop empty/non-actionable fetched Webex messages before orchestration

### Providers

- Keep provider-specific reasoning behind `assistant_app/providers/`.
- Route provider selection/config through backend services rather than hardcoding it in the admin surface.

### Device transport

- `device_executor/device_client.py` is the transport-detail boundary.
- The first real path should stay Webex cloud xAPI via:
  - `/v1/devices`
  - `/v1/xapi/status`
  - `/v1/xapi/command/{commandKey}`
- Do not add local RoomOS transport unless a later slice explicitly requires it.

### Real integration requirements

Real Webex setup needs:

- bot credentials
- webhook secret
- HTTPS webhook target URL when startup reconciliation is enabled

Real cloud xAPI command execution depends on the same Webex token plus scopes needed to:

- read devices
- read xAPI status
- execute xAPI commands

Both execution paths must continue to return normalized `ExecutionResult` objects.
