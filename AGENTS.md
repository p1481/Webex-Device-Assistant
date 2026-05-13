# AGENTS.md

## Current repo state
- This repository now contains a Python/FastAPI scaffold for the Webex Device Assistant App.
- The workspace is a git repository; keep local secrets, runtime state, virtualenvs, build outputs, and caches ignored.
- Real Webex and device integrations are intentionally mock-first in the checked-in example config. Local deployment env files may switch mock modes off and must stay untracked.
- The current real device path is Webex cloud xAPI over HTTPS, not local RoomOS transport.

## Source of truth
- Prefer executable sources over prose: `pyproject.toml`, package code under `assistant_app/`, `device_executor/`, `direct_tool_adapter/`, `admin_page/`, `shared/`, and tests under `tests/`.
- `opencode_webex_device_prompt.md` remains the product-spec reference for intended future scope.
- Keep the markdown specs aligned with the code when architecture requirements change.

## Architecture constraints to preserve
- The Assistant App is always the LLM-first conversational layer.
- Both execution modes must exist:
  - **Separated Mode**: Assistant App orchestrates; `device_executor` performs execution.
  - **All LLM Mode**: Assistant App orchestrates; `direct_tool_adapter` may execute.
- The difference between modes is execution ownership, not user experience.
- Keep LLM provider integration swappable. Do not hardcode a single provider into orchestration.
- Keep approval and policy decisions explicit. High-risk actions should default to separated mode with approval.

## Intended module boundaries
- The documented target structure is `assistant_app/`, `device_executor/`, `direct_tool_adapter/`, `admin_page/`, and `shared/`.
- Keep these boundaries intact. Do not collapse orchestration, execution, and transport concerns into a single module.
- Keep `admin_page/` thin; backend policy/provider/auth logic belongs behind APIs in `assistant_app/` and shared services.

## Default implementation order
- Extend shared canonical contracts first, especially between the Assistant App and execution backends.
- Keep the thin end-to-end `get_status` flow working before adding broader command coverage.
- Add approval handling and executor safety checks before exposing mutating device actions.
- Keep admin-page thin; put policy/provider/auth logic behind backend APIs first.

## Verified developer commands
- Create the local virtualenv and install dependencies: `python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"`
- Run the app locally: `.venv/bin/python -m uvicorn assistant_app.main:app --reload`
- Run tests: `.venv/bin/python -m pytest`
- `pyrightconfig.json` excludes `.venv`, so type-checking should target repo code only.

## Repo-specific guardrails
- Webex webhook handling lives in `assistant_app/webhook_controller.py` and `assistant_app/webex_gateway.py`. Keep ingress thin: verify the raw webhook signature first, then normalize inbound messages.
- The desired Webex webhook set is two `messages.created` subscriptions: one with `roomType=direct`, one with `roomType=group&mentionedPeople=me`. Reconcile only app-owned hooks for those exact desired filters.
- Approval and admin-login delivery should use Webex card attachments plus `attachmentActions` fetch-by-id semantics. Do not assume the submit payload is present directly in the webhook body.
- Keep gateway-side filtering in `assistant_app/webex_gateway.py`. Drop self-messages and empty/non-actionable fetched Webex messages before orchestration.
- Keep provider-specific reasoning behind `assistant_app/providers/`, but route provider selection/config through backend services rather than hardcoding in the admin surface.
- `device_executor/device_client.py` remains the place for transport details. The first real path should stay Webex cloud xAPI via `/v1/devices`, `/v1/xapi/status`, and `/v1/xapi/command/{commandKey}` unless a later slice explicitly adds local transport.
- Real Webex setup needs bot credentials, webhook secret, and an HTTPS webhook target URL when startup reconciliation is enabled. Real approval-card handling also needs `attachmentActions` webhook registration and server-side click authorization.
- Real cloud xAPI command execution depends on the same Webex token plus the scopes needed to read devices/xAPI status and execute xAPI commands.
- Both execution paths must continue to return normalized `ExecutionResult` objects.
