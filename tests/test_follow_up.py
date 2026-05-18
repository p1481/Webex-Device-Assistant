"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

import asyncio
from typing import cast

from assistant_app.main import app
from shared.contracts import (
    InboundUserMessage,
    MessageSource,
)
from tests._helpers import (
    as_mapping,
    as_sequence,
    build_authenticated_client,
)

client = build_authenticated_client(app)


def test_reset_command_clears_session() -> None:
    response = client.post("/debug/messages", json={"text": "/reset", "session_id": "reset-case"})
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "cleared the session context" in text


def test_matrix_assign_without_target_asks_follow_up_then_resumes() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "matrix assign output HDMI1 mode Replace layout Equal source 3",
            "session_id": "matrix-assign-target-followup",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "Which device should I use?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={"text": "Board Pro", "session_id": "matrix-assign-target-followup"},
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "matrix-assign-target-followup"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    assign_matrix = as_mapping(execution_request["assign_matrix"])

    assert assign_matrix["target_device"] == "Board Pro"
    assert assign_matrix["output"] == "HDMI1"
    assert assign_matrix["mode"] == "Replace"
    assert assign_matrix["layout"] == "Equal"
    assert assign_matrix["source_id"] == "3"


def test_adjust_camera_position_without_target_asks_follow_up_then_resumes() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "camera 2 zoom in",
            "session_id": "camera-position-target-followup",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "Which device should I use?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={"text": "Board Pro", "session_id": "camera-position-target-followup"},
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "camera-position-target-followup"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    adjust_camera_position = as_mapping(execution_request["adjust_camera_position"])

    assert adjust_camera_position["target_device"] == "Board Pro"
    assert adjust_camera_position["camera_id"] == "2"
    assert adjust_camera_position["pan"] is None
    assert adjust_camera_position["tilt"] is None
    assert adjust_camera_position["zoom"] == -700


def test_dial_without_target_asks_follow_up_after_address() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "dial youngcle@cisco.com", "session_id": "dial-followup-case"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]

    assert isinstance(text, str)
    assert text == "Which device should I use?"

    approvals_response = client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(
        as_mapping(approval)["session_id"] == "dial-followup-case" for approval in approvals
    )


def test_set_volume_without_target_asks_follow_up_after_level() -> None:
    scoped_client = build_authenticated_client()

    response = scoped_client.post(
        "/debug/messages",
        json={"text": "set volume to 35", "session_id": "volume-target-followup"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]

    assert isinstance(text, str)
    assert text == "Which device should I use?"

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(
        as_mapping(approval)["session_id"] == "volume-target-followup" for approval in approvals
    )


def test_missing_webex_join_params_ask_follow_up_then_resume() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "followup-webex-join",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "What Webex meeting ID or address should I join?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={"text": "987654321", "session_id": "followup-webex-join"},
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "followup-webex-join"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])

    assert webex_join["meeting_identifier"] == "987654321"
    assert webex_join["target_device"] == "Board Pro"


def test_missing_volume_level_asks_follow_up_then_resume() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "set volume on Board Pro",
            "session_id": "followup-volume",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "What volume level should I set (0-100)?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={"text": "35", "session_id": "followup-volume"},
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" not in second_text
    assert "Mock volume set to 35" in second_text
    assert "Board Pro" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    matching = [
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "followup-volume"
    ]
    assert matching == []


def test_reset_clears_pending_follow_up() -> None:
    scoped_client = build_authenticated_client()

    initial_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "followup-reset",
        },
    )
    assert initial_response.status_code == 200

    reset_response = scoped_client.post(
        "/debug/messages",
        json={"text": "/reset", "session_id": "followup-reset"},
    )
    assert reset_response.status_code == 200
    reset_payload = cast(object, reset_response.json())
    reset_body = as_mapping(reset_payload)
    reset_reply = as_mapping(reset_body["reply"])
    reset_text = reset_reply["text"]

    assert isinstance(reset_text, str)
    assert "cleared the session context" in reset_text

    post_reset_response = scoped_client.post(
        "/debug/messages",
        json={"text": "987654321", "session_id": "followup-reset"},
    )
    assert post_reset_response.status_code == 200
    post_reset_payload = cast(object, post_reset_response.json())
    post_reset_body = as_mapping(post_reset_payload)
    post_reset_reply = as_mapping(post_reset_body["reply"])
    post_reset_text = post_reset_reply["text"]

    assert isinstance(post_reset_text, str)
    assert "Approval required" not in post_reset_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(as_mapping(approval)["session_id"] == "followup-reset" for approval in approvals)


def test_shared_room_follow_up_is_scoped_to_actor() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "shared-room-followup",
            "room_id": "shared-room-followup",
            "user_id": "user-a",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "What Webex meeting ID or address should I join?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "987654321",
            "session_id": "shared-room-followup",
            "room_id": "shared-room-followup",
            "user_id": "user-b",
        },
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" not in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(
        as_mapping(approval)["session_id"] == "shared-room-followup" for approval in approvals
    )

    third_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "987654321",
            "session_id": "shared-room-followup",
            "room_id": "shared-room-followup",
            "user_id": "user-a",
        },
    )
    assert third_response.status_code == 200
    third_payload = cast(object, third_response.json())
    third_body = as_mapping(third_payload)
    third_reply = as_mapping(third_body["reply"])
    third_text = third_reply["text"]

    assert isinstance(third_text, str)
    assert "Approval required" in third_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "shared-room-followup"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])

    assert webex_join["meeting_identifier"] == "987654321"
    assert webex_join["target_device"] == "Board Pro"


def test_shared_room_reset_clears_only_callers_pending_follow_up() -> None:
    scoped_client = build_authenticated_client()

    user_a_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-a",
        },
    )
    assert user_a_response.status_code == 200

    user_b_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "set volume on Desk Pro",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-b",
        },
    )
    assert user_b_response.status_code == 200

    reset_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "/reset",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-b",
        },
    )
    assert reset_response.status_code == 200
    reset_payload = cast(object, reset_response.json())
    reset_body = as_mapping(reset_payload)
    reset_reply = as_mapping(reset_body["reply"])
    reset_text = reset_reply["text"]

    assert isinstance(reset_text, str)
    assert "cleared the session context" in reset_text

    post_reset_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "35",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-b",
        },
    )
    assert post_reset_response.status_code == 200
    post_reset_payload = cast(object, post_reset_response.json())
    post_reset_body = as_mapping(post_reset_payload)
    post_reset_reply = as_mapping(post_reset_body["reply"])
    post_reset_text = post_reset_reply["text"]

    assert isinstance(post_reset_text, str)
    assert "Approval required" not in post_reset_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(
        as_mapping(approval)["session_id"] == "shared-room-reset" for approval in approvals
    )

    resumed_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "987654321",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-a",
        },
    )
    assert resumed_response.status_code == 200
    resumed_payload = cast(object, resumed_response.json())
    resumed_body = as_mapping(resumed_payload)
    resumed_reply = as_mapping(resumed_body["reply"])
    resumed_text = resumed_reply["text"]

    assert isinstance(resumed_text, str)
    assert "Approval required" in resumed_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "shared-room-reset"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])

    assert webex_join["meeting_identifier"] == "987654321"
    assert webex_join["target_device"] == "Board Pro"


def test_blank_target_get_status_asks_follow_up_then_resumes() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        DeviceStatusSnapshot,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        GetStatusParams,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        PolicyDecision,
        ProviderSettings,
        SessionContext,
    )

    class BlankTargetGetStatusProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_STATUS,
                    summary="Get the current device status.",
                    get_status=GetStatusParams(
                        target_device="",
                        include_metrics=True,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class RecordingModeRouter:
        def __init__(self) -> None:
            self.executed_proposals: list[ActionProposal] = []

        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> object:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("build_request should not be called")

        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = policy_decision
            assert proposal.get_status is not None
            self.executed_proposals.append(proposal)
            return ExecutionResult(
                request_id="req-get-status-followup",
                intent=Intent.GET_STATUS,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message=f"Collected status from {proposal.get_status.target_device} via all-LLM mode.",
                device_status=DeviceStatusSnapshot(
                    target_device=proposal.get_status.target_device,
                    source="mock",
                    display_name=proposal.get_status.target_device,
                    online=True,
                ),
            )

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    router = RecordingModeRouter()
    orchestrator = Orchestrator(
        BlankTargetGetStatusProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, router)),
        approval_manager,
    )

    first_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="generic-target-followup-status",
                user_id="debug-user",
                text="status please",
                source=MessageSource.DEBUG,
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert first_reply.text == "Which device should I use?"
    pending_action = memory_store.get_pending_action("generic-target-followup-status", "debug-user")
    assert pending_action is not None
    assert pending_action.action_proposal is not None
    assert pending_action.action_proposal.get_status is not None
    assert pending_action.action_proposal.get_status.include_metrics is True
    assert pending_action.action_proposal.get_status.target_device == ""

    second_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="generic-target-followup-status",
                user_id="debug-user",
                text="Board Pro",
                source=MessageSource.DEBUG,
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert "Collected status from Board Pro" in second_reply.text
    assert len(router.executed_proposals) == 1
    resumed_proposal = router.executed_proposals[0]
    assert resumed_proposal.get_status is not None
    assert resumed_proposal.get_status.target_device == "Board Pro"
    assert resumed_proposal.get_status.include_metrics is True
    assert memory_store.get_pending_action("generic-target-followup-status", "debug-user") is None


def test_blank_target_reboot_asks_follow_up_then_resumes() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ApprovalState,
        ExecutionMode,
        ExecutionRequest,
        ExecutionResult,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        PolicyDecision,
        ProviderSettings,
        RebootParams,
        SessionContext,
    )

    class BlankTargetRebootProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.REBOOT,
                    summary="Reboot the target device.",
                    reboot=RebootParams(target_device=""),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class ApprovalRecordingModeRouter:
        def __init__(self) -> None:
            self.built_requests: list[ExecutionRequest] = []

        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionRequest:
            _ = message
            assert proposal.reboot is not None
            execution_request = ExecutionRequest(
                session_id=message.session_id,
                requested_by=message.user_id,
                intent=proposal.intent,
                execution_mode=policy_decision.selected_mode,
                approval_state=policy_decision.approval_state,
                target_device=proposal.reboot.target_device,
                reason=policy_decision.reason,
                reboot=proposal.reboot,
            )
            self.built_requests.append(execution_request)
            return execution_request

        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("execute should not be called for approval-required reboot")

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

    memory_store = InMemorySessionStore()
    state_store = InMemoryStateStore()
    approval_manager = ApprovalManager(memory_store, state_store)
    router = ApprovalRecordingModeRouter()
    orchestrator = Orchestrator(
        BlankTargetRebootProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM, state_store=state_store),
        cast(ModeRouter, cast(object, router)),
        approval_manager,
    )

    first_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="generic-target-followup-reboot",
                user_id="debug-user",
                text="reboot it",
                source=MessageSource.DEBUG,
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert first_reply.text == "Which device should I use?"
    pending_action = memory_store.get_pending_action("generic-target-followup-reboot", "debug-user")
    assert pending_action is not None
    assert pending_action.action_proposal is not None
    assert pending_action.action_proposal.reboot is not None
    assert pending_action.action_proposal.reboot.target_device == ""

    second_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="generic-target-followup-reboot",
                user_id="debug-user",
                text="Home Office",
                source=MessageSource.DEBUG,
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert "Approval required" in second_reply.text
    assert len(router.built_requests) == 1
    execution_request = router.built_requests[0]
    assert execution_request.reboot is not None
    assert execution_request.reboot.target_device == "Home Office"
    assert execution_request.target_device == "Home Office"
    assert execution_request.execution_mode == ExecutionMode.SEPARATED
    assert execution_request.approval_state == ApprovalState.REQUIRED
    approvals = state_store.list_approval_requests()
    matching = [
        approval
        for approval in approvals
        if approval.session_id == "generic-target-followup-reboot"
    ]
    assert len(matching) == 1
    assert matching[0].execution_request is not None
    assert matching[0].execution_request.reboot is not None
    assert matching[0].execution_request.reboot.target_device == "Home Office"
    assert memory_store.get_pending_action("generic-target-followup-reboot", "debug-user") is None


def test_webex_blank_target_get_status_returns_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        ExecutionResult,
        GetStatusParams,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        PolicyDecision,
        ProviderSettings,
        SessionContext,
    )

    class BlankTargetGetStatusProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_STATUS,
                    summary="Get the current device status.",
                    get_status=GetStatusParams(target_device="", include_metrics=True),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class UnusedModeRouter:
        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> object:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("build_request should not be called")

        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(
                device_id="device-1",
                webex_device_id="webex-device-1",
                display_name="Board Pro",
                product="Cisco Board Pro",
                place="HQ 7F",
                device_type="roomdesk",
                permissions=["xapi"],
                online=True,
            ),
            OrganizationDeviceRecord(
                device_id="device-2",
                webex_device_id="webex-device-2",
                display_name="Desk Pro",
                product="Cisco Desk Pro",
                place="Home Office",
                device_type="roomdesk",
                permissions=["xapi"],
                online=True,
            ),
        ]

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetGetStatusProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card",
                user_id="person-1",
                text="status please",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "Which device should I use?"
    assert reply.markdown == "**Select a device**\n\nWhich device should I use?"
    attachments = reply.attachments
    assert len(attachments) == 1
    content = as_mapping(as_mapping(attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_set = as_mapping(body[2])
    choices = as_sequence(choice_set["choices"])
    assert [as_mapping(choice)["value"] for choice in choices] == [
        "Board Pro",
        "Desk Pro",
    ]
    actions = as_sequence(content["actions"])
    continue_action = as_mapping(actions[0])
    cancel_action = as_mapping(actions[1])
    continue_data = as_mapping(continue_action["data"])
    cancel_data = as_mapping(cancel_action["data"])
    assert continue_data["kind"] == "entity_selection"
    assert continue_data["fieldName"] == "target_device"
    assert continue_data["selectionDecision"] == "submit"
    assert cancel_data["selectionDecision"] == "cancel"
    pending_action = memory_store.get_pending_action("webex-selection-card", "person-1")
    assert pending_action is not None
    assert continue_data["pendingActionId"] == pending_action.pending_action_id


def test_webex_missing_target_for_mute_returns_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
        SetMicrophoneMuteParams,
    )

    class BlankTargetMuteProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_MICROPHONE_MUTE,
                    summary="Mute the microphones.",
                    set_microphone_mute=SetMicrophoneMuteParams(
                        target_device="",
                        muted=True,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetMuteProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-mute",
                user_id="person-1",
                text="뮤트해줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "어떤 장치를 음소거할까요? 장치 이름을 말씀해주시거나 목록을 확인해주세요."
    assert len(reply.attachments) == 1
    content = as_mapping(as_mapping(reply.attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_set = as_mapping(body[2])
    choices = as_sequence(choice_set["choices"])
    assert [as_mapping(choice)["value"] for choice in choices] == [
        "Codec Pro G2",
        "Home Office",
    ]


def test_webex_follow_up_mic_mute_repeats_selection_card_when_target_still_missing() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
        SetMicrophoneMuteParams,
    )

    class BlankTargetMuteProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_MICROPHONE_MUTE,
                    summary="Mute the microphones.",
                    set_microphone_mute=SetMicrophoneMuteParams(
                        target_device="",
                        muted=True,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetMuteProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-mute-follow-up",
                user_id="person-1",
                text="음소거 해줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    follow_up_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-mute-follow-up",
                user_id="person-1",
                text="마이크 음소거",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert (
        follow_up_reply.text
        == "어떤 장치를 음소거할까요? 장치 이름을 말씀해주시거나 목록을 확인해주세요."
    )
    assert len(follow_up_reply.attachments) == 1
    content = as_mapping(as_mapping(follow_up_reply.attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_set = as_mapping(body[2])
    choices = as_sequence(choice_set["choices"])
    assert [as_mapping(choice)["value"] for choice in choices] == [
        "Codec Pro G2",
        "Home Office",
    ]


def test_webex_follow_up_status_repeats_selection_card_when_target_still_missing() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        GetStatusParams,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
    )

    class BlankTargetGetStatusProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_STATUS,
                    summary="Get the current device status.",
                    get_status=GetStatusParams(target_device="", include_metrics=True),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Board Pro"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Desk Pro"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetGetStatusProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-status-follow-up",
                user_id="person-1",
                text="status please",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    follow_up_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-status-follow-up",
                user_id="person-1",
                text="status",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert follow_up_reply.text == "Which device should I use?"
    assert len(follow_up_reply.attachments) == 1


def test_webex_missing_target_for_volume_returns_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
        SetVolumeParams,
    )

    class BlankTargetVolumeProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_VOLUME,
                    summary="Increase the volume.",
                    set_volume=SetVolumeParams(
                        target_device="",
                        level=65,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetVolumeProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume",
                user_id="person-1",
                text="볼륨 올려줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "어떤 장치의 볼륨을 올릴까요?"
    assert len(reply.attachments) == 1


def test_webex_follow_up_volume_repeats_selection_card_when_target_still_missing() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
        SetVolumeParams,
    )

    class BlankTargetVolumeProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_VOLUME,
                    summary="Increase the volume.",
                    set_volume=SetVolumeParams(
                        target_device="",
                        level=65,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetVolumeProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume-follow-up",
                user_id="person-1",
                text="볼륨 올려줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    follow_up_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume-follow-up",
                user_id="person-1",
                text="볼륨 올려줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert follow_up_reply.text == "어떤 장치의 볼륨을 올릴까요?"
    assert len(follow_up_reply.attachments) == 1


def test_webex_follow_up_reboot_repeats_selection_card_when_target_still_missing() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        RebootParams,
        SessionContext,
    )

    class BlankTargetRebootProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.REBOOT,
                    summary="Reboot the target device.",
                    reboot=RebootParams(target_device=""),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Board Pro"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetRebootProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-reboot-follow-up",
                user_id="person-1",
                text="reboot it",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    follow_up_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-reboot-follow-up",
                user_id="person-1",
                text="reboot",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert follow_up_reply.text == "Which device should I use?"
    assert len(follow_up_reply.attachments) == 1


def test_webex_missing_volume_target_and_level_prefers_selection_card_first() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        PendingActionProposal,
        ProviderSettings,
        SessionContext,
    )

    class MissingVolumeFieldsProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                pending_action=PendingActionProposal(
                    intent=Intent.SET_VOLUME,
                    summary="Set device volume.",
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        MissingVolumeFieldsProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume-first",
                user_id="person-1",
                text="볼륨 높여줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "어떤 장치의 볼륨을 올릴까요?"
    assert len(reply.attachments) == 1


def test_resume_pending_action_selection_rejects_other_user() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        ExecutionResult,
        GetStatusParams,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
    )

    class PassiveProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: object
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("analyze_message should not be called")

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class UnusedModeRouter:
        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> object:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    pending_action = memory_store.set_pending_action(
        "selection-auth-session",
        "owner-user",
        PendingActionProposal(
            intent=Intent.GET_STATUS,
            summary="Get the current device status.",
            action_proposal=ActionProposal(
                intent=Intent.GET_STATUS,
                summary="Get the current device status.",
                get_status=GetStatusParams(target_device="", include_metrics=True),
            ),
        ),
    )
    orchestrator = Orchestrator(
        PassiveProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    reply, resolved = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action_id=pending_action.pending_action_id,
            field_name="target_device",
            selected_value="Board Pro",
            user_id="different-user",
            room_id="room-1",
        )
    )

    assert resolved is False
    assert reply.text == "This selection card belongs to another user."
    assert memory_store.get_pending_action("selection-auth-session", "owner-user") is not None


def test_resume_pending_action_selection_cancel_clears_pending_state() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        ExecutionResult,
        GetStatusParams,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
    )

    class PassiveProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: object
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("analyze_message should not be called")

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class UnusedModeRouter:
        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> object:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    pending_action = memory_store.set_pending_action(
        "selection-cancel-session",
        "owner-user",
        PendingActionProposal(
            intent=Intent.GET_STATUS,
            summary="Get the current device status.",
            action_proposal=ActionProposal(
                intent=Intent.GET_STATUS,
                summary="Get the current device status.",
                get_status=GetStatusParams(target_device="", include_metrics=True),
            ),
        ),
    )
    orchestrator = Orchestrator(
        PassiveProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    reply, resolved = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action_id=pending_action.pending_action_id,
            field_name="target_device",
            selected_value=None,
            user_id="owner-user",
            room_id="room-1",
            cancel=True,
        )
    )

    assert resolved is True
    assert reply.text == "Okay, I cancelled that request."
    assert memory_store.get_pending_action("selection-cancel-session", "owner-user") is None


def test_webex_turn_on_selfview_without_target_returns_device_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        OrganizationDeviceRecord,
    )

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Board Pro"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Room Bar"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called while target is missing")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called while target is missing")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called while target is missing")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selfview-selection-card",
                user_id="person-1",
                text="turn on Selfview",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "어떤 장치의 Selfview를 켜드릴까요? 장치 이름을 말씀해 주세요."
    assert len(reply.attachments) == 1
    content = as_mapping(as_mapping(reply.attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_set = as_mapping(body[2])
    assert choice_set["id"] == "selectedValue"
    assert [as_mapping(choice)["value"] for choice in as_sequence(choice_set["choices"])] == [
        "Board Pro",
        "Room Bar",
    ]


def test_webex_korean_selfview_and_video_without_target_return_device_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        OrganizationDeviceRecord,
    )

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Board Pro"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Room Bar"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called while target is missing")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called while target is missing")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called while target is missing")

    cases = [
        ("셀프뷰 켜줘", "어떤 장치의 Selfview를 켜드릴까요? 장치 이름을 말씀해 주세요."),
        ("비디오 켜줘", "어떤 장치의 비디오를 켜드릴까요? 장치 이름을 말씀해 주세요."),
    ]

    for text, expected_reply in cases:
        memory_store = InMemorySessionStore()
        approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
        orchestrator = Orchestrator(
            RuleBasedProvider(default_target_device=""),
            memory_store,
            PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
            cast(ModeRouter, cast(object, UnusedModeRouter())),
            approval_manager,
            device_lister=list_devices,
        )

        reply = asyncio.run(
            orchestrator.handle_message(
                InboundUserMessage(
                    session_id=f"webex-korean-toggle-selection-card-{text}",
                    user_id="person-1",
                    text=text,
                    source=MessageSource.WEBEX,
                    room_id="room-1",
                    preferred_mode=ExecutionMode.ALL_LLM,
                )
            )
        )

        assert reply.text == expected_reply
        assert len(reply.attachments) == 1
        content = as_mapping(as_mapping(reply.attachments[0])["content"])
        body = as_sequence(content["body"])
        choice_set = as_mapping(body[2])
        assert choice_set["id"] == "selectedValue"
        assert choice_set["placeholder"] == "장치를 선택하세요"
        assert [as_mapping(choice)["value"] for choice in as_sequence(choice_set["choices"])] == [
            "Board Pro",
            "Room Bar",
        ]


def test_missing_webex_join_accepts_https_meet_url_follow_up_then_resume() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "followup-webex-join-url",
        },
    )
    assert first_response.status_code == 200
    first_reply = as_mapping(as_mapping(cast(object, first_response.json()))["reply"])
    assert first_reply["text"] == "What Webex meeting ID or address should I join?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "https://acecloud.webex.com/meet/youngcle",
            "session_id": "followup-webex-join-url",
        },
    )
    assert second_response.status_code == 200
    second_reply = as_mapping(as_mapping(cast(object, second_response.json()))["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals = as_sequence(as_mapping(cast(object, approvals_response.json()))["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "followup-webex-join-url"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])

    assert webex_join["meeting_identifier"] == "https://acecloud.webex.com/meet/youngcle"
    assert webex_join["target_device"] == "Board Pro"


def test_missing_webex_join_accepts_spaced_number_follow_up_then_uses_default_webex_device() -> (
    None
):
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "Join meeting",
            "session_id": "followup-webex-join-spaced-number-default",
            "source": "webex",
            "room_id": "debug-room",
            "target_device": "Room Bar",
        },
    )
    assert first_response.status_code == 200
    first_reply = as_mapping(as_mapping(cast(object, first_response.json()))["reply"])
    assert first_reply["text"] == "What Webex meeting ID or address should I join?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "2571 017 7729",
            "session_id": "followup-webex-join-spaced-number-default",
            "source": "webex",
            "room_id": "debug-room",
            "target_device": "Room Bar",
        },
    )
    assert second_response.status_code == 200
    second_reply = as_mapping(as_mapping(cast(object, second_response.json()))["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert (
        "Approval required" in second_text
        or "Webex join requested for 25710177729 on Room Bar" in second_text
    )

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals = as_sequence(as_mapping(cast(object, approvals_response.json()))["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "followup-webex-join-spaced-number-default"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])
    assert webex_join["meeting_identifier"] == "25710177729"
    assert webex_join["target_device"] == "Room Bar"
