"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

from typing import cast

from assistant_app.main import app
from tests._helpers import (
    as_mapping,
    as_sequence,
    build_authenticated_client,
)

client = build_authenticated_client(app)


def test_set_camera_mode_executes_without_approval() -> None:
    response = client.post(
        "/debug/messages",
        json={
            "text": "set camera mode to frames on Board Pro",
            "session_id": "camera-mode-direct-case",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Approval required" not in text
    assert "Mock camera mode set to Frames" in text


def test_join_obtp_creates_approval_reply() -> None:
    response = client.post(
        "/debug/messages",
        json={
            "text": "join obtp on Board Pro",
            "session_id": "join-obtp-approval-case",
        },
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


def test_set_volume_executes_without_approval() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "set volume to 35 on Board Pro", "session_id": "volume-direct-case"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Approval required" not in text
    assert "Mock volume set to 35" in text


def test_debug_approval_executes_pending_action() -> None:
    request_response = client.post(
        "/debug/messages",
        json={
            "text": "dial youngcle@cisco.com on Board Pro",
            "session_id": "approval-exec-case",
        },
    )
    assert request_response.status_code == 200
    request_payload = cast(object, request_response.json())
    request_body = as_mapping(request_payload)
    request_reply = as_mapping(request_body["reply"])
    request_text = request_reply["text"]
    assert isinstance(request_text, str)
    assert "Approval required" in request_text

    approvals_response = client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "approval-exec-case"
    )
    request_id = as_mapping(pending)["request_id"]
    assert isinstance(request_id, str)

    approve_response = client.post(f"/debug/approvals/{request_id}?approved=true")
    assert approve_response.status_code == 200
    approve_payload = cast(object, approve_response.json())
    approve_body = as_mapping(approve_payload)
    approval = as_mapping(approve_body["approval"])
    reply = as_mapping(approve_body["reply"])
    text = reply["text"]

    assert approval["status"] == "executed"
    assert isinstance(text, str)
    assert "Mock dial requested" in text


def test_debug_approval_endpoint_resolves_request() -> None:
    approval_response = client.post(
        "/debug/messages",
        json={
            "text": "dial youngcle@cisco.com on Board Pro",
            "session_id": "resolve-approval-case",
        },
    )
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

    decision_response = client.post(f"/debug/approvals/{request_id}?approved=true")
    assert decision_response.status_code == 200
    decision_payload = cast(object, decision_response.json())
    decision_body = as_mapping(decision_payload)
    approval = as_mapping(decision_body["approval"])
    assert approval["status"] == "executed"
