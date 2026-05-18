"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

from pathlib import Path
from typing import cast

import pytest

from assistant_app.admin_auth import ADMIN_SESSION_COOKIE
from assistant_app.main import app, build_app
from assistant_app.webex_gateway import WebexGateway
from shared.contracts import (
    RuntimeAdminSettingsUpdate,
)
from tests._helpers import (
    as_mapping,
    as_sequence,
    build_authenticated_client,
    build_unauthenticated_client,
    temporary_env,
)

client = build_authenticated_client(app)


def test_admin_login_creates_approval_reply() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "admin login", "session_id": "admin-login-case"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    attachments = as_sequence(reply["attachments"])
    assert isinstance(text, str)
    assert "Approval required" in text
    assert len(attachments) == 1


def test_admin_routes_require_authenticated_session() -> None:
    scoped_client = build_unauthenticated_client()

    response = scoped_client.get("/admin/settings")

    assert response.status_code == 401
    assert response.json() == {"detail": "Admin login is required."}


def test_admin_auth_start_allows_default_admin_when_allowlist_empty() -> None:
    scoped_app = build_app()
    scoped_client = build_unauthenticated_client(scoped_app)

    response = scoped_client.post(
        "/admin/auth/start",
        json={"email": "youngcle@cisco.com"},
    )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    assert body["status"] == "pending"
    session_id = body["session_id"]
    assert isinstance(session_id, str)
    auth_session = scoped_app.state.services.admin_service.get_admin_auth_session(session_id)
    assert auth_session is not None
    assert auth_session.email == "youngcle@cisco.com"


def test_admin_auth_start_rejects_email_outside_explicit_allowlist() -> None:
    scoped_app = build_app()
    _ = scoped_app.state.services.admin_service.update_runtime_admin_settings(
        RuntimeAdminSettingsUpdate(
            allowed_admin_emails=["ops-admin@example.com"],
        )
    )
    scoped_client = build_unauthenticated_client(scoped_app)

    response = scoped_client.post(
        "/admin/auth/start",
        json={"email": "youngcle@cisco.com"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin email is not allowed."}


def test_admin_auth_browser_flow_sets_cookie_and_logout_clears_access() -> None:
    scoped_app = build_app()
    scoped_client = build_unauthenticated_client(scoped_app)

    start_response = scoped_client.post(
        "/admin/auth/start",
        json={"email": "youngcle@cisco.com"},
    )
    assert start_response.status_code == 200
    start_payload = cast(object, start_response.json())
    start_body = as_mapping(start_payload)
    session_id = start_body["session_id"]
    assert isinstance(session_id, str)

    pending_status_response = scoped_client.get(f"/admin/auth/status/{session_id}")
    assert pending_status_response.status_code == 200
    pending_status_payload = cast(object, pending_status_response.json())
    pending_status_body = as_mapping(pending_status_payload)
    assert pending_status_body["status"] == "pending"
    assert ADMIN_SESSION_COOKIE not in scoped_client.cookies

    approvals = scoped_app.state.services.state_store.list_approval_requests()
    pending_approval = next(
        approval for approval in approvals if approval.admin_session_id == session_id
    )

    approval_response = scoped_client.post(
        f"/debug/approvals/{pending_approval.request_id}?approved=true"
        f"&user_id=person-1&email=youngcle@cisco.com&admin_session_id={session_id}"
    )
    assert approval_response.status_code == 200

    approved_status_response = scoped_client.get(f"/admin/auth/status/{session_id}")
    assert approved_status_response.status_code == 200
    approved_status_payload = cast(object, approved_status_response.json())
    approved_status_body = as_mapping(approved_status_payload)
    assert approved_status_body["status"] == "approved"
    assert ADMIN_SESSION_COOKIE in scoped_client.cookies

    settings_response = scoped_client.get("/admin/settings")
    assert settings_response.status_code == 200

    logout_response = scoped_client.post(
        "/admin/auth/logout",
        json={},
    )
    assert logout_response.status_code == 200
    assert logout_response.json() == {"status": "logged_out"}

    after_logout_response = scoped_client.get("/admin/settings")
    assert after_logout_response.status_code == 401


def test_admin_auth_rejects_mismatched_admin_session_id() -> None:
    scoped_app = build_app()
    scoped_client = build_unauthenticated_client(scoped_app)

    start_response = scoped_client.post(
        "/admin/auth/start",
        json={"email": "youngcle@cisco.com"},
    )
    assert start_response.status_code == 200
    start_payload = cast(object, start_response.json())
    start_body = as_mapping(start_payload)
    session_id = start_body["session_id"]
    assert isinstance(session_id, str)

    approvals = scoped_app.state.services.state_store.list_approval_requests()
    pending_approval = next(
        approval for approval in approvals if approval.admin_session_id == session_id
    )

    reject_response = scoped_client.post(
        f"/debug/approvals/{pending_approval.request_id}?approved=true"
        "&user_id=person-1&email=youngcle@cisco.com&admin_session_id=wrong-session"
    )
    assert reject_response.status_code == 200
    reject_payload = cast(object, reject_response.json())
    reject_body = as_mapping(reject_payload)
    approval = as_mapping(reject_body["approval"])
    assert approval["status"] == "rejected"

    status_response = scoped_client.get(f"/admin/auth/status/{session_id}")
    assert status_response.status_code == 200
    status_payload = cast(object, status_response.json())
    status_body = as_mapping(status_payload)
    assert status_body["status"] == "rejected"
    assert ADMIN_SESSION_COOKIE not in scoped_client.cookies


def test_admin_provider_endpoints_are_available() -> None:
    response = client.get("/admin/providers")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    assert "providers" in body
    active = as_mapping(body["active"])
    assert active["provider"] == "ollama"


def test_admin_settings_endpoint_exposes_default_admin_user() -> None:
    response = client.get("/admin/settings")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    runtime = as_mapping(body["runtime"])
    assert runtime["default_user_email"] == "youngcle@cisco.com"


def test_admin_settings_report_split_webex_auth_config() -> None:
    async def fake_resolve_identity(_self: WebexGateway) -> object:
        return None

    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
            "ADMIN_COOKIE_SECRET": "test-cookie-secret",
        }
    ):
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(WebexGateway, "resolve_bot_identity", fake_resolve_identity)
        try:
            with build_authenticated_client() as scoped_client:
                response = scoped_client.get("/admin/settings")
        finally:
            monkeypatch.undo()

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    runtime = as_mapping(body["runtime"])
    startup = as_mapping(body["startup"])
    access_token = as_mapping(runtime["access_token"])
    bot_token = as_mapping(runtime["bot_token"])
    assert access_token["present"] is True
    assert access_token["masked_value"] == "***token-manager-configured***"
    assert bot_token["present"] is True
    assert bot_token["masked_value"] == "***configured***"
    assert startup["webex_token_manager_base_url"] == "http://127.0.0.1:3000"


def test_admin_settings_update_changes_next_runtime_view() -> None:
    response = client.put(
        "/admin/settings",
        json={
            "default_user_email": "youngcle@cisco.com",
            "default_space_id": "space-123",
            "default_space_title": "Ops Space",
            "default_execution_mode": "all-llm",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    runtime = as_mapping(body["runtime"])
    assert runtime["default_space_id"] == "space-123"
    assert runtime["default_execution_mode"] == "all-llm"


def test_admin_devices_endpoint_returns_org_device_list() -> None:
    response = client.get("/admin/devices")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    devices = as_sequence(body["devices"])
    assert len(devices) >= 1


def test_admin_actions_and_stats_endpoints_are_available() -> None:
    actions_response = client.get("/admin/actions")
    assert actions_response.status_code == 200
    actions_payload = cast(object, actions_response.json())
    actions_body = as_mapping(actions_payload)
    actions = as_sequence(actions_body["actions"])
    assert len(actions) >= 1
    action_intents = {
        as_mapping(action)["intent"] for action in actions if isinstance(action, dict)
    }
    assert {"assign_matrix", "unassign_matrix", "swap_matrix"}.issubset(action_intents)

    stats_response = client.get("/admin/stats")
    assert stats_response.status_code == 200
    stats_payload = cast(object, stats_response.json())
    stats_body = as_mapping(stats_payload)
    stats = as_mapping(stats_body["stats"])
    assert "approvals_total" in stats


def test_admin_page_renders_real_html() -> None:
    response = client.get("/admin-page")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Webex Device Assistant Admin" in body
    assert "youngcle@cisco.com" in body
    assert "/admin-page/docs" in body
    assert "/admin-page/static/admin.js" in body


def test_admin_page_docs_renders_manual_summaries() -> None:
    response = client.get("/admin-page/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Webex Device Assistant Manuals" in body
    assert "/admin-page/manuals/ARCHITECTURE.md" in body
    assert "/admin-page/architecture-guide" in body
    assert "/admin-page/manuals/INSTALL.md" in body
    assert "/admin-page/manuals/USER_MANUAL.md" in body
    assert "ARCHITECTURE_CURRENT.md" not in body
    assert "Open the full markdown manuals" in body


def test_admin_page_static_css_asset_is_served() -> None:
    response = client.get("/admin-page/static/admin.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--color-accent" in response.text


@pytest.mark.parametrize(
    ("manual_name", "expected_heading"),
    [
        ("ARCHITECTURE.md", "# Architecture Manual"),
        ("INSTALL.md", "# Install Manual"),
        ("USER_MANUAL.md", "# User Manual"),
        ("MANUAL_KO.md", "# Webex Device Assistant 앱 아키텍처 및 사용 가이드"),
    ],
)
def test_admin_page_manual_routes_serve_top_level_manuals(
    manual_name: str, expected_heading: str
) -> None:
    response = client.get(f"/admin-page/manuals/{manual_name}")
    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert expected_heading in response.text


def test_admin_page_architecture_guide_renders_current_html_manual() -> None:
    response = client.get("/admin-page/architecture-guide")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Device Assistant Guide" in body
    assert "/admin-page/manuals/ARCHITECTURE.md" in body
    assert "Cameras.SpeakerTrack.Set" in body


def test_admin_page_healthz_reports_ready_ui() -> None:
    response = client.get("/admin-page/healthz")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    assert body["ui"] == "ready"
    assert body["page"] == "/admin-page"


def test_admin_policy_endpoints_are_available() -> None:
    response = client.get("/admin/policies")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    policies = as_mapping(body["policies"])
    assert "get_status" in policies


def test_admin_provider_endpoint_does_not_echo_api_key() -> None:
    response = client.put(
        "/admin/providers",
        json={
            "provider": "rule_based",
            "model": "rule-based-default",
            "api_key": "super-secret",
            "enabled": True,
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    provider = as_mapping(body["provider"])
    assert provider["api_key"] is None

    list_response = client.get("/admin/providers")
    assert list_response.status_code == 200
    listed_payload = cast(object, list_response.json())
    listed_body = as_mapping(listed_payload)
    active = as_mapping(listed_body["active"])
    assert active["api_key"] is None


def test_persisted_admin_runtime_state_survives_restart(tmp_path: Path) -> None:
    state_path = tmp_path / "admin-state.json"
    with temporary_env({"ADMIN_STATE_PATH": str(state_path)}):
        first_app = build_app()
        first_client = build_authenticated_client(first_app)

        settings_response = first_client.put(
            "/admin/settings",
            json={
                "default_space_id": "space-789",
                "default_space_title": "Persistent Ops",
                "default_user_email": "ops-admin@example.com",
                "default_execution_mode": "all-llm",
                "selected_provider": "ollama",
                "selected_provider_model": "persisted-model",
                "selected_device_id": "device-7",
                "selected_device_name": "Board Pro 7",
            },
        )
        assert settings_response.status_code == 200

        provider_response = first_client.put(
            "/admin/providers",
            json={
                "provider": "ollama",
                "model": "gemma4:latest",
                "base_url": "http://127.0.0.1:11434/api",
                "api_key": "do-not-persist",
                "temperature": 0.3,
                "max_tokens": 512,
                "enabled": True,
            },
        )
        assert provider_response.status_code == 200

        policy_response = first_client.put(
            "/admin/policies/get_status",
            json={
                "allowed_modes": ["all-llm"],
                "risk_level": "read_only",
                "approval_state": "not_required",
                "reason": "Allow all-llm for restart-survival test.",
            },
        )
        assert policy_response.status_code == 200

        approval_response = first_client.post(
            "/debug/messages",
            json={
                "text": "dial youngcle@cisco.com on Board Pro",
                "session_id": "persisted-approval-case",
            },
        )
        assert approval_response.status_code == 200

        second_app = build_app()
        second_client = build_authenticated_client(second_app)

        persisted_settings_response = second_client.get("/admin/settings")
        assert persisted_settings_response.status_code == 200
        persisted_settings_payload = cast(object, persisted_settings_response.json())
        persisted_settings_body = as_mapping(persisted_settings_payload)
        runtime = as_mapping(persisted_settings_body["runtime"])
        assert runtime["default_space_id"] == "space-789"
        assert runtime["default_space_title"] == "Persistent Ops"
        assert runtime["default_user_email"] == "ops-admin@example.com"
        assert runtime["default_execution_mode"] == "all-llm"
        assert runtime["selected_provider"] == "ollama"
        assert runtime["selected_provider_model"] == "persisted-model"
        assert runtime["selected_device_id"] == "device-7"
        assert runtime["selected_device_name"] == "Board Pro 7"

        persisted_providers_response = second_client.get("/admin/providers")
        assert persisted_providers_response.status_code == 200
        persisted_providers_payload = cast(object, persisted_providers_response.json())
        persisted_providers_body = as_mapping(persisted_providers_payload)
        active = as_mapping(persisted_providers_body["active"])
        assert active["provider"] == "ollama"
        assert active["model"] == "gemma4:latest"
        assert active["base_url"] == "http://127.0.0.1:11434/api"
        assert active["temperature"] == 0.3
        assert active["max_tokens"] == 512
        assert active["api_key"] is None

        persisted_policies_response = second_client.get("/admin/policies")
        assert persisted_policies_response.status_code == 200
        persisted_policies_payload = cast(object, persisted_policies_response.json())
        persisted_policies_body = as_mapping(persisted_policies_payload)
        policies = as_mapping(persisted_policies_body["policies"])
        get_status_policy = as_mapping(policies["get_status"])
        assert get_status_policy["allowed_modes"] == ["all-llm"]
        assert get_status_policy["reason"] == "Allow all-llm for restart-survival test."

        approvals_response = second_client.get("/admin/approvals")
        assert approvals_response.status_code == 200
        approvals_payload = cast(object, approvals_response.json())
        approvals_body = as_mapping(approvals_payload)
        approvals = as_sequence(approvals_body["approvals"])
        persisted_action_approvals = [
            as_mapping(approval)
            for approval in approvals
            if as_mapping(approval)["session_id"] == "persisted-approval-case"
        ]
        assert len(persisted_action_approvals) == 1
        assert persisted_action_approvals[0]["status"] == "pending"

        stats_response = second_client.get("/admin/stats")
        assert stats_response.status_code == 200
        stats_payload = cast(object, stats_response.json())
        stats_body = as_mapping(stats_payload)
        stats = as_mapping(stats_body["stats"])
        approvals_total = stats["approvals_total"]
        approvals_pending = stats["approvals_pending"]
        assert isinstance(approvals_total, int)
        assert approvals_total >= 1
        assert approvals_pending == 1
        audit_total = stats["audit_total"]
        assert isinstance(audit_total, int)
        assert audit_total >= 2
        assert stats["sessions_total"] == 0
        assert stats["processed_webhook_events"] == 0


def test_non_implemented_provider_change_is_rejected_live() -> None:
    response = client.put(
        "/admin/providers",
        json={
            "provider": "openai",
            "model": "gpt-4.1",
            "enabled": True,
        },
    )
    assert response.status_code == 409
