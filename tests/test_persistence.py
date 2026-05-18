"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

from assistant_app.main import app, build_app
from assistant_app.state_store import FileBackedStateStore
from tests._helpers import (
    as_mapping,
    as_sequence,
    build_authenticated_client,
    temporary_env,
)

client = build_authenticated_client(app)


def test_persisted_approval_can_be_resolved_after_restart(tmp_path: Path) -> None:
    state_path = tmp_path / "approval-state.json"
    with temporary_env({"ADMIN_STATE_PATH": str(state_path)}):
        first_app = build_app()
        first_client = TestClient(first_app)

        approval_response = first_client.post(
            "/debug/messages",
            json={
                "text": "dial youngcle@cisco.com on Board Pro",
                "session_id": "restart-approval-case",
            },
        )
        assert approval_response.status_code == 200
        approval_payload = cast(object, approval_response.json())
        approval_body = as_mapping(approval_payload)
        reply = as_mapping(approval_body["reply"])
        attachments = as_sequence(reply["attachments"])
        first_attachment = as_mapping(attachments[0])
        content = as_mapping(first_attachment["content"])
        actions = as_sequence(content["actions"])
        first_action = as_mapping(actions[0])
        data = as_mapping(first_action["data"])
        request_id = data["requestId"]
        assert isinstance(request_id, str)

        second_app = build_app()
        second_client = build_authenticated_client(second_app)

        decision_response = second_client.post(f"/debug/approvals/{request_id}?approved=true")
        assert decision_response.status_code == 200
        decision_payload = cast(object, decision_response.json())
        decision_body = as_mapping(decision_payload)
        approval = as_mapping(decision_body["approval"])
        assert approval["status"] == "executed"

        approvals_response = second_client.get("/admin/approvals")
        assert approvals_response.status_code == 200
        approvals_payload = cast(object, approvals_response.json())
        approvals_body = as_mapping(approvals_payload)
        approvals = as_sequence(approvals_body["approvals"])
        resolved = as_mapping(approvals[0])
        assert resolved["request_id"] == request_id
        assert resolved["status"] == "executed"


def test_file_backed_state_store_persists_processed_webhook_event_ids(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "webhook-dedupe-state.json"
    first_store = FileBackedStateStore(state_path)

    assert not first_store.has_processed_webhook_event("message-1")

    first_store.mark_processed_webhook_event("message-1")

    assert first_store.has_processed_webhook_event("message-1")
    assert first_store.get_stats().processed_webhook_events == 1

    restarted_store = FileBackedStateStore(state_path)

    assert restarted_store.has_processed_webhook_event("message-1")
    assert restarted_store.get_stats().processed_webhook_events == 1


def test_in_memory_state_store_defaults_to_ollama_provider_settings() -> None:
    from assistant_app.ollama_support import DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_MODEL
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import ProviderKind

    settings = InMemoryStateStore().get_provider_settings()

    assert settings.provider == ProviderKind.OLLAMA
    assert settings.model == DEFAULT_OLLAMA_MODEL
    assert settings.base_url == DEFAULT_OLLAMA_BASE_URL
