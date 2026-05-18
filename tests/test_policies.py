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


def test_webex_join_approval_flow_uses_policy_reason() -> None:
    scoped_client = build_authenticated_client()

    request_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join 987654321 on Board Pro",
            "session_id": "webex-approval-reason",
        },
    )
    assert request_response.status_code == 200

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "webex-approval-reason"
    )
    pending_approval = as_mapping(pending)
    execution_request = as_mapping(pending_approval["execution_request"])
    request_id = pending_approval["request_id"]

    assert execution_request["reason"] == (
        "Meeting joins are mutating actions and should require explicit approval."
    )
    assert isinstance(request_id, str)

    approve_response = scoped_client.post(f"/debug/approvals/{request_id}?approved=true")
    assert approve_response.status_code == 200
    approve_payload = cast(object, approve_response.json())
    approve_body = as_mapping(approve_payload)
    reply = as_mapping(approve_body["reply"])
    text = reply["text"]

    assert isinstance(text, str)
    assert (
        "Policy: Meeting joins are mutating actions and should require explicit approval." in text
    )


def test_join_obtp_approval_flow_uses_policy_reason() -> None:
    scoped_client = build_authenticated_client()

    request_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "join obtp on Board Pro",
            "session_id": "join-obtp-approval-reason",
        },
    )
    assert request_response.status_code == 200

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "join-obtp-approval-reason"
    )
    pending_approval = as_mapping(pending)
    execution_request = as_mapping(pending_approval["execution_request"])
    request_id = pending_approval["request_id"]

    assert execution_request["reason"] == (
        "Scheduled meeting joins are mutating actions and should require explicit approval."
    )
    assert isinstance(request_id, str)

    approve_response = scoped_client.post(f"/debug/approvals/{request_id}?approved=true")
    assert approve_response.status_code == 200
    approve_payload = cast(object, approve_response.json())
    approve_body = as_mapping(approve_payload)
    reply = as_mapping(approve_body["reply"])
    text = reply["text"]

    assert isinstance(text, str)
    assert (
        "Policy: Scheduled meeting joins are mutating actions and should require explicit approval."
        in text
    )


def test_environment_info_policy_defaults_to_no_approval() -> None:
    scoped_client = build_authenticated_client()

    policies_response = scoped_client.get("/admin/policies")
    assert policies_response.status_code == 200
    policies_payload = cast(object, policies_response.json())
    policies_body = as_mapping(policies_payload)
    policies = as_mapping(policies_body["policies"])

    environment_policy = as_mapping(policies["get_environment_info"])
    assert environment_policy["allowed_modes"] == ["separated", "all-llm"]
    assert environment_policy["approval_state"] == "not_required"
    assert environment_policy["risk_level"] == "read_only"


def test_room_booking_policy_defaults_to_no_approval() -> None:
    scoped_client = build_authenticated_client()

    policies_response = scoped_client.get("/admin/policies")
    assert policies_response.status_code == 200
    policies_payload = cast(object, policies_response.json())
    policies_body = as_mapping(policies_payload)
    policies = as_mapping(policies_body["policies"])

    booking_policy = as_mapping(policies["get_room_booking"])
    assert booking_policy["allowed_modes"] == ["separated", "all-llm"]
    assert booking_policy["approval_state"] == "not_required"
    assert booking_policy["risk_level"] == "read_only"


def test_join_obtp_policy_defaults_to_approval_required() -> None:
    scoped_client = build_authenticated_client()

    policies_response = scoped_client.get("/admin/policies")
    assert policies_response.status_code == 200
    policies_payload = cast(object, policies_response.json())
    policies_body = as_mapping(policies_payload)
    policies = as_mapping(policies_body["policies"])

    join_policy = as_mapping(policies["join_obtp"])
    assert join_policy["allowed_modes"] == ["separated", "all-llm"]
    assert join_policy["approval_state"] == "required"
    assert join_policy["risk_level"] == "low"


def test_action_registry_lists_environment_info_as_approval_free() -> None:
    scoped_client = build_authenticated_client()

    registry_response = scoped_client.get("/admin/actions")
    assert registry_response.status_code == 200
    registry_payload = cast(object, registry_response.json())
    registry_body = as_mapping(registry_payload)
    actions = as_sequence(registry_body["actions"])
    environment_action = next(
        action for action in actions if as_mapping(action)["intent"] == "get_environment_info"
    )
    environment_mapping = as_mapping(environment_action)

    assert environment_mapping["approval_required_by_default"] is False
    assert environment_mapping["supported_modes"] == ["separated", "all-llm"]


def test_action_registry_lists_room_booking_and_join_obtp_defaults() -> None:
    scoped_client = build_authenticated_client()

    registry_response = scoped_client.get("/admin/actions")
    assert registry_response.status_code == 200
    registry_payload = cast(object, registry_response.json())
    registry_body = as_mapping(registry_payload)
    actions = as_sequence(registry_body["actions"])
    booking_action = next(
        action for action in actions if as_mapping(action)["intent"] == "get_room_booking"
    )
    join_action = next(action for action in actions if as_mapping(action)["intent"] == "join_obtp")

    booking_mapping = as_mapping(booking_action)
    join_mapping = as_mapping(join_action)

    assert booking_mapping["approval_required_by_default"] is False
    assert booking_mapping["supported_modes"] == ["separated", "all-llm"]
    assert join_mapping["approval_required_by_default"] is True
    assert join_mapping["supported_modes"] == ["separated", "all-llm"]
