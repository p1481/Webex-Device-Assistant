"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

import asyncio
import json
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


def test_webex_volume_card_selection_then_asks_for_level() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
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

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume-next-field",
                user_id="person-1",
                text="볼륨 높여줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    pending_action = memory_store.get_pending_action(
        "webex-selection-card-volume-next-field", "person-1"
    )
    assert pending_action is not None

    selection_reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action_id=pending_action.pending_action_id,
            field_name="target_device",
            user_id="person-1",
            selected_value="Codec Pro G2",
            room_id="room-1",
        )
    )

    assert handled is True
    assert selection_reply.text == "What volume level should I set (0-100)?"
    assert len(selection_reply.attachments) == 0


def test_setting_option_request_returns_toggle_selection_card_with_device_dropdown() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("setting option card request should not use provider")

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

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called before card selection")

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(
                device_id="device-1",
                display_name="Board Pro",
                product="Board Pro",
                place="HQ",
            ),
            OrganizationDeviceRecord(
                device_id="device-2",
                display_name="Room Bar",
                product="Room Bar",
                place="Home",
            ),
        ]

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="setting-option-card",
                user_id="person-1",
                text="마이크 음소거 설정",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "마이크 음소거 상태를 선택해주세요."
    attachments = reply.attachments
    assert len(attachments) == 1
    content = as_mapping(as_mapping(attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_sets = [
        as_mapping(item) for item in body if as_mapping(item).get("type") == "Input.ChoiceSet"
    ]
    assert [choice_set["id"] for choice_set in choice_sets] == [
        "settingValue",
        "selectedValue",
    ]
    assert choice_sets[0]["style"] == "expanded"
    assert [as_mapping(choice)["value"] for choice in as_sequence(choice_sets[0]["choices"])] == [
        "true",
        "false",
    ]
    assert choice_sets[1]["style"] == "compact"
    assert [as_mapping(choice)["value"] for choice in as_sequence(choice_sets[1]["choices"])] == [
        "Board Pro",
        "Room Bar",
    ]
    actions = as_sequence(content["actions"])
    assert [as_mapping(action)["title"] for action in actions] == ["Apply", "Cancel"]

    pending_action = memory_store.get_pending_action("setting-option-card", "person-1")
    assert pending_action is not None
    assert pending_action.intent.value == "set_microphone_mute"
    submit_data = as_mapping(as_mapping(actions[0])["data"])
    assert submit_data["kind"] == "entity_selection"
    assert submit_data["pendingActionId"] == pending_action.pending_action_id
    assert submit_data["fieldName"] == "setting_value"
    assert submit_data["settingFieldName"] == "muted"


def test_setting_card_submission_applies_value_and_device_selection() -> None:
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
        ExecutionResult,
        ExecutionStatus,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
        RiskLevel,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("submission should resume an existing pending action")

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

    class CapturingModeRouter:
        def __init__(self) -> None:
            self.proposal: object | None = None

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("approval should not be required in this test")

        async def execute(
            self, message: InboundUserMessage, proposal: object, policy_decision: object
        ) -> ExecutionResult:
            _ = message
            _ = policy_decision
            self.proposal = proposal
            return ExecutionResult(
                request_id="setting-submit-result",
                intent=Intent.SET_MICROPHONE_MUTE,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Muted Board Pro.",
            )

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    mode_router = CapturingModeRouter()
    pending_action = PendingActionProposal(
        intent=Intent.SET_MICROPHONE_MUTE,
        summary="Change microphone mute state.",
    )
    memory_store.set_pending_action("setting-submit", "person-1", pending_action)

    class NoApprovalPolicyEvaluator(PolicyEvaluator):
        def evaluate(self, proposal: object, preferred_mode: object = None) -> PolicyDecision:
            _ = proposal
            _ = preferred_mode
            return PolicyDecision(
                selected_mode=ExecutionMode.ALL_LLM,
                allowed_modes=[ExecutionMode.ALL_LLM],
                risk_level=RiskLevel.LOW,
                approval_state=ApprovalState.NOT_REQUIRED,
                reason="Test bypasses approval to verify setting-card submission.",
            )

    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        NoApprovalPolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, mode_router)),
        approval_manager,
    )

    reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action.pending_action_id,
            "setting_value",
            "Board Pro",
            "person-1",
            "room-1",
            setting_field_name="muted",
            setting_value="true",
        )
    )

    assert handled is True
    assert reply.text == (
        "Muted Board Pro. Policy: Test bypasses approval to verify setting-card submission."
    )
    assert isinstance(mode_router.proposal, ActionProposal)
    proposal = mode_router.proposal
    assert proposal.intent == Intent.SET_MICROPHONE_MUTE
    assert proposal.set_microphone_mute is not None
    assert proposal.set_microphone_mute.target_device == "Board Pro"
    assert proposal.set_microphone_mute.muted is True
    assert memory_store.get_pending_action("setting-submit", "person-1") is None


def test_camera_mode_request_returns_supported_mode_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        OrchestrationDecision,
        ProviderSettings,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("camera mode card request should not use provider")

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

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called before card selection")

    async def list_camera_modes(target_device: str) -> tuple[str, ...]:
        assert target_device == "Room Bar"
        return ("Manual", "Dynamic", "BestOverview", "Closeup", "Frames", "GroupAndSpeaker")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        camera_mode_lister=list_camera_modes,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="camera-mode-card",
                user_id="person-1",
                text="Room Bar 카메라 모드 변경",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "카메라 모드를 선택해주세요."
    assert reply.markdown == "**카메라 모드 선택**\n\n대상 장치: Room Bar"
    attachments = reply.attachments
    assert len(attachments) == 1
    content = as_mapping(as_mapping(attachments[0])["content"])
    actions = as_sequence(content["actions"])
    assert [as_mapping(action)["title"] for action in actions] == [
        "Manual",
        "Dynamic",
        "BestOverview",
        "Closeup",
        "Frames",
        "GroupAndSpeaker",
        "Cancel",
    ]
    assert [
        as_mapping(as_mapping(action)["data"]).get("selectedValue") for action in actions[:6]
    ] == ["Manual", "Dynamic", "BestOverview", "Closeup", "Frames", "GroupAndSpeaker"]
    for action in actions[:6]:
        data = as_mapping(as_mapping(action)["data"])
        assert data["kind"] == "entity_selection"
        assert data["fieldName"] == "camera_mode"
        assert data["selectionDecision"] == "submit"

    pending_action = memory_store.get_pending_action("camera-mode-card", "person-1")
    assert pending_action is not None
    assert pending_action.intent.value == "set_camera_mode"
    assert (
        as_mapping(as_mapping(actions[0])["data"])["pendingActionId"]
        == pending_action.pending_action_id
    )


def test_selfview_request_prompts_device_first_then_filtered_capability_options() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        OrganizationDeviceRecord,
    )

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(
                device_id="device-room-bar",
                display_name="Room Bar",
                product="Cisco Room Bar",
                place="HQ 7F",
                online=True,
            ),
            OrganizationDeviceRecord(
                device_id="device-navigator",
                display_name="Navigator",
                product="Cisco Room Navigator",
                place="HQ 7F",
                online=True,
            ),
        ]

    class CapturingModeRouter:
        def __init__(self) -> None:
            self.execute_request_calls: list[object] = []

        async def execute(self, *args: object, **kwargs: object) -> object:
            from shared.contracts import ExecutionResult, ExecutionStatus, Intent

            self.execute_request_calls.append((args, kwargs))
            return ExecutionResult(
                request_id="req-selfview-cap-test",
                intent=Intent.SET_SELFVIEW,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Enabled selfview on Room Bar.",
            )

        async def execute_request(self, execution_request: object) -> object:
            from shared.contracts import ExecutionResult, ExecutionStatus, Intent

            self.execute_request_calls.append(execution_request)
            return ExecutionResult(
                request_id="req-selfview-cap-test",
                intent=Intent.SET_SELFVIEW,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Enabled selfview on Room Bar.",
            )

        def build_request(self, *args: object, **kwargs: object) -> object:
            return object()

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    captured_router = CapturingModeRouter()
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, captured_router)),
        approval_manager,
        device_lister=list_devices,
    )

    first_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="capability-selfview-device-first",
                user_id="person-1",
                text="turn on Selfview",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert len(first_reply.attachments) == 1
    content = as_mapping(as_mapping(first_reply.attachments[0])["content"])
    body = as_sequence(content["body"])
    device_choice_set = as_mapping(body[2])
    assert device_choice_set["id"] == "selectedValue"
    assert [
        as_mapping(choice)["value"] for choice in as_sequence(device_choice_set["choices"])
    ] == ["Room Bar"]
    assert "Navigator" not in json.dumps(content, ensure_ascii=False)

    pending_action = memory_store.get_pending_action("capability-selfview-device-first", "person-1")
    assert pending_action is not None

    second_reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action.pending_action_id,
            "target_device",
            "Room Bar",
            "person-1",
            "room-1",
        )
    )

    assert handled is True
    # With enabled=True already extracted from "turn on Selfview", the device
    # selection should execute immediately — no second ON/OFF card.
    assert second_reply.attachments == []
    assert "Enabled selfview on Room Bar" in second_reply.text
    assert len(captured_router.execute_request_calls) == 1


def test_device_list_formats_workspace_name_with_model_and_capabilities() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import ExecutionMode, OrganizationDeviceRecord

    memory_store = InMemorySessionStore()
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, object())),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    rendered = orchestrator._format_device_list(
        [
            OrganizationDeviceRecord(
                device_id="device-room-bar",
                display_name="Executive Room",
                product="Cisco Room Bar",
                place="HQ 7F",
                online=True,
                connection_status="connected",
                software_version="RoomOS 11.20",
            ),
            OrganizationDeviceRecord(
                device_id="device-navigator",
                display_name="Touch Panel",
                product="Cisco Room Navigator",
                online=False,
                connection_status="disconnected",
            ),
        ],
        "allowed",
    )

    assert "Executive Room (Cisco Room Bar)" in rendered
    assert (
        "지원 기능: 오디오, 카메라, 디스플레이, 레이아웃, 미팅, 프레젠테이션, 셀프뷰, 스탠바이"
        in rendered
    )
    assert "Touch Panel (Cisco Room Navigator)" in rendered
    assert "지원 기능:" not in rendered.split("Touch Panel (Cisco Room Navigator)", 1)[1]
    assert "software=RoomOS 11.20" in rendered


def test_status_response_is_detailed_korean_sections() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        DeviceStatusSnapshot,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        Intent,
    )

    memory_store = InMemorySessionStore()
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, object())),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    rendered = orchestrator._format_execution_result(
        ExecutionResult(
            request_id="req-detailed-status",
            intent=Intent.GET_STATUS,
            execution_mode=ExecutionMode.ALL_LLM,
            status=ExecutionStatus.SUCCESS,
            message="Status for Executive Room.",
            device_status=DeviceStatusSnapshot(
                target_device="Executive Room",
                source="webex",
                device_id="device-room-bar",
                display_name="Executive Room",
                product="Cisco Room Bar",
                place="HQ 7F",
                software_version="RoomOS 11.20",
                serial_number="SERIAL1",
                online=True,
                connection_status="connected",
                system_state="Initialized",
                active_interface="Ethernet",
                ipv4_address="192.0.2.10",
                volume=55,
                volume_muted=False,
                microphones_muted=True,
                call_active=False,
                active_call_count=0,
                presentation_active=True,
                selfview_mode="On",
                speakertrack_state="Active",
                standby_state="Off",
            ),
        ),
        "allowed",
    )

    assert "**상태 상세**" in rendered
    assert "장치: Executive Room (Cisco Room Bar)" in rendered
    assert "연결: online=True, connection=connected, system=Initialized" in rendered
    assert "네트워크: interface=Ethernet, ipv4=192.0.2.10" in rendered
    assert "오디오: volume=55, muted=False, microphones_muted=True" in rendered
    assert "통화/공유: call_active=False, active_call_count=0, presentation_active=True" in rendered
    assert "카메라/화면: selfview=On, speakertrack=Active" in rendered


def test_korean_selfview_keyword_starts_device_then_option_flow() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        OrganizationDeviceRecord,
    )

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(
                device_id="device-room-bar",
                display_name="Room Bar",
                product="Cisco Room Bar",
                place="HQ 7F",
                online=True,
            )
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called before device and option selection")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError(
                "execute_request should not be called before device and option selection"
            )

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError(
                "build_request should not be called before device and option selection"
            )

    memory_store = InMemorySessionStore()
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        ApprovalManager(memory_store, InMemoryStateStore()),
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="korean-selfview-keyword-flow",
                user_id="person-1",
                text="셀프뷰",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text != "What should I do next?"
    assert len(reply.attachments) == 1
    content = as_mapping(as_mapping(reply.attachments[0])["content"])
    assert "장치" in json.dumps(content, ensure_ascii=False)
    assert "Room Bar" in json.dumps(content, ensure_ascii=False)


def test_setting_option_card_submit_uses_selected_value_as_setting_not_target() -> None:
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
        ExecutionResult,
        ExecutionStatus,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
        RiskLevel,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("submission should resume pending action")

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

    class CapturingModeRouter:
        def __init__(self) -> None:
            self.proposal: ActionProposal | None = None

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("approval should not be required")

        async def execute(
            self, message: InboundUserMessage, proposal: ActionProposal, policy_decision: object
        ) -> ExecutionResult:
            _ = message
            _ = policy_decision
            self.proposal = proposal
            return ExecutionResult(
                request_id="setting-selected-value-result",
                intent=Intent.SET_SELFVIEW,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Selfview enabled on Room Bar.",
            )

    class NoApprovalPolicyEvaluator(PolicyEvaluator):
        def evaluate(self, proposal: object, preferred_mode: object = None) -> PolicyDecision:
            _ = proposal
            _ = preferred_mode
            return PolicyDecision(
                selected_mode=ExecutionMode.ALL_LLM,
                allowed_modes=[ExecutionMode.ALL_LLM],
                risk_level=RiskLevel.LOW,
                approval_state=ApprovalState.NOT_REQUIRED,
                reason="Test bypasses approval.",
            )

    memory_store = InMemorySessionStore()
    pending_action = PendingActionProposal(
        intent=Intent.SET_SELFVIEW,
        summary="Selfview setting.",
        target_device="Room Bar",
    )
    memory_store.set_pending_action("setting-selected-value", "person-1", pending_action)
    mode_router = CapturingModeRouter()
    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        NoApprovalPolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, mode_router)),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action.pending_action_id,
            "setting_value",
            "true",
            "person-1",
            "room-1",
            setting_field_name="enabled",
        )
    )

    assert handled is True
    assert "Selfview enabled on Room Bar" in reply.text
    assert mode_router.proposal is not None
    assert mode_router.proposal.set_selfview is not None
    assert mode_router.proposal.set_selfview.target_device == "Room Bar"
    assert mode_router.proposal.set_selfview.enabled is True


def test_setting_option_card_submit_uses_setting_value_when_selected_value_missing() -> None:
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
        ExecutionResult,
        ExecutionStatus,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
        RiskLevel,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("submission should resume pending action")

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

    class CapturingModeRouter:
        def __init__(self) -> None:
            self.proposal: ActionProposal | None = None

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("approval should not be required")

        async def execute(
            self, message: InboundUserMessage, proposal: ActionProposal, policy_decision: object
        ) -> ExecutionResult:
            _ = message
            _ = policy_decision
            self.proposal = proposal
            return ExecutionResult(
                request_id="setting-value-only-result",
                intent=Intent.SET_MICROPHONE_MUTE,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Microphones muted on Room Bar.",
            )

    class NoApprovalPolicyEvaluator(PolicyEvaluator):
        def evaluate(self, proposal: object, preferred_mode: object = None) -> PolicyDecision:
            _ = proposal
            _ = preferred_mode
            return PolicyDecision(
                selected_mode=ExecutionMode.ALL_LLM,
                allowed_modes=[ExecutionMode.ALL_LLM],
                risk_level=RiskLevel.LOW,
                approval_state=ApprovalState.NOT_REQUIRED,
                reason="Test bypasses approval.",
            )

    memory_store = InMemorySessionStore()
    pending_action = PendingActionProposal(
        intent=Intent.SET_MICROPHONE_MUTE,
        summary="Microphone mute setting.",
        target_device="Room Bar",
    )
    memory_store.set_pending_action("setting-value-only", "person-1", pending_action)
    mode_router = CapturingModeRouter()
    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        NoApprovalPolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, mode_router)),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action.pending_action_id,
            "setting_value",
            None,
            "person-1",
            "room-1",
            setting_field_name="muted",
            setting_value="true",
        )
    )

    assert handled is True
    assert reply.attachments == []
    assert "Microphones muted on Room Bar" in reply.text
    assert mode_router.proposal is not None
    assert mode_router.proposal.set_microphone_mute is not None
    assert mode_router.proposal.set_microphone_mute.target_device == "Room Bar"
    assert mode_router.proposal.set_microphone_mute.muted is True
    assert memory_store.get_pending_action("setting-value-only", "person-1") is None
