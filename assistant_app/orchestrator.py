from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from assistant_app.approval_manager import ApprovalManager
from assistant_app.memory_store import InMemorySessionStore
from assistant_app.mode_router import ModeRouter
from assistant_app.orchestration import card_builders, formatters, text_extractors
from assistant_app.policy_evaluator import PolicyEvaluator
from assistant_app.providers.base import LLMProvider
from shared.contracts import (
    ActionProposal,
    ApprovalRequest,
    ApprovalState,
    ApprovalStatus,
    DialParams,
    DisplayMode,
    ExecutionResult,
    ExecutionStatus,
    InboundUserMessage,
    Intent,
    MessageSource,
    MicrophoneProcessingMode,
    OrganizationDeviceRecord,
    OutboundReply,
    PendingActionProposal,
    SetCameraModeParams,
    SetDisplayModeParams,
    SetMicrophoneModeParams,
    SetMicrophoneMuteParams,
    SetPresentationParams,
    SetSelfviewParams,
    SetSpeakerTrackParams,
    SetStandbyParams,
    SetVideoMuteParams,
    SetVolumeParams,
    WebexJoinParams,
    WritableCameraMode,
    get_action_payload_field,
    intent_requires_target_device,
)


class Orchestrator:
    _CAPABILITY_ORDER: tuple[tuple[str, str], ...] = (
        ("audio", "오디오"),
        ("camera", "카메라"),
        ("display", "디스플레이"),
        ("layout", "레이아웃"),
        ("meeting", "미팅"),
        ("presentation", "프레젠테이션"),
        ("selfview", "셀프뷰"),
        ("standby", "스탠바이"),
        ("speakertrack", "SpeakerTrack"),
        ("environment", "환경 센서"),
    )

    _PRODUCT_CAPABILITIES: dict[str, set[str]] = {
        "room bar": {
            "audio",
            "camera",
            "display",
            "layout",
            "meeting",
            "presentation",
            "selfview",
            "standby",
            "speakertrack",
            "environment",
        },
        "cisco room bar": {
            "audio",
            "camera",
            "display",
            "layout",
            "meeting",
            "presentation",
            "selfview",
            "standby",
            "speakertrack",
            "environment",
        },
        "room bar pro": {
            "audio",
            "camera",
            "display",
            "layout",
            "meeting",
            "presentation",
            "selfview",
            "standby",
            "speakertrack",
            "environment",
        },
        "cisco room bar pro": {
            "audio",
            "camera",
            "display",
            "layout",
            "meeting",
            "presentation",
            "selfview",
            "standby",
            "speakertrack",
            "environment",
        },
        "board pro": {
            "audio",
            "camera",
            "display",
            "layout",
            "meeting",
            "presentation",
            "selfview",
            "standby",
            "speakertrack",
            "environment",
        },
        "cisco board pro": {
            "audio",
            "camera",
            "display",
            "layout",
            "meeting",
            "presentation",
            "selfview",
            "standby",
            "speakertrack",
            "environment",
        },
        "board pro 55": {
            "audio",
            "camera",
            "display",
            "layout",
            "meeting",
            "presentation",
            "selfview",
            "standby",
            "speakertrack",
            "environment",
        },
        "board pro 75": {
            "audio",
            "camera",
            "display",
            "layout",
            "meeting",
            "presentation",
            "selfview",
            "standby",
            "speakertrack",
            "environment",
        },
        "room navigator": set(),
        "cisco room navigator": set(),
        "navigator": set(),
    }

    _INTENT_CAPABILITIES: dict[Intent, set[str]] = {
        Intent.GET_STATUS: {"audio", "camera", "display", "meeting", "presentation", "selfview", "standby"},
        Intent.GET_ENVIRONMENT_INFO: {"environment"},
        Intent.GET_CAMERA_MODE: {"camera"},
        Intent.GET_ROOM_BOOKING: {"meeting"},
        Intent.WEBEX_JOIN: {"meeting"},
        Intent.JOIN_OBTP: {"meeting"},
        Intent.DIAL: {"meeting"},
        Intent.HANG_UP: {"meeting"},
        Intent.SEND_DTMF: {"meeting"},
        Intent.SET_MICROPHONE_MUTE: {"audio"},
        Intent.SET_MICROPHONE_MODE: {"audio"},
        Intent.SET_VOLUME: {"audio"},
        Intent.SET_VIDEO_MUTE: {"camera"},
        Intent.SET_SELFVIEW: {"selfview"},
        Intent.SET_CAMERA_MODE: {"camera"},
        Intent.SET_LAYOUT: {"layout"},
        Intent.SET_PRESENTATION: {"presentation"},
        Intent.SWITCH_INPUT_SOURCE: {"presentation", "display"},
        Intent.ASSIGN_MATRIX: {"display"},
        Intent.UNASSIGN_MATRIX: {"display"},
        Intent.SWAP_MATRIX: {"display"},
        Intent.SET_DISPLAY_MODE: {"display"},
        Intent.SET_DISPLAY_ROLE: {"display"},
        Intent.ACTIVATE_CAMERA_PRESET: {"camera"},
        Intent.ADJUST_CAMERA_POSITION: {"camera"},
        Intent.SET_SPEAKERTRACK: {"speakertrack", "camera"},
        Intent.SET_STANDBY: {"standby"},
        Intent.REBOOT: {"standby"},
        Intent.FACTORY_RESET: {"standby"},
    }

    def __init__(
        self,
        provider: LLMProvider,
        memory_store: InMemorySessionStore,
        policy_evaluator: PolicyEvaluator,
        mode_router: ModeRouter,
        approval_manager: ApprovalManager,
        device_lister: Callable[[], Awaitable[list[OrganizationDeviceRecord]]]
        | None = None,
        camera_mode_lister: Callable[[str], Awaitable[tuple[str, ...]]] | None = None,
    ) -> None:
        self.provider: LLMProvider = provider
        self.memory_store: InMemorySessionStore = memory_store
        self.policy_evaluator: PolicyEvaluator = policy_evaluator
        self.mode_router: ModeRouter = mode_router
        self.approval_manager: ApprovalManager = approval_manager
        self.device_lister: (
            Callable[[], Awaitable[list[OrganizationDeviceRecord]]] | None
        ) = device_lister
        self.camera_mode_lister: Callable[[str], Awaitable[tuple[str, ...]]] | None = (
            camera_mode_lister
        )

    async def handle_message(self, message: InboundUserMessage) -> OutboundReply:
        session = self.memory_store.append_user_turn(message.session_id, message.text)
        pending_action = self.memory_store.get_pending_action(
            message.session_id, message.user_id
        )

        if self._is_reset_message(message.text):
            return self._reset_session(message)

        if pending_action is not None:
            return await self._handle_pending_follow_up(message, pending_action)

        setting_option_pending_action = self._build_setting_option_card_pending_action(message)
        if setting_option_pending_action is not None:
            _ = self.memory_store.set_pending_action(
                message.session_id,
                message.user_id,
                setting_option_pending_action,
            )
            reply = await self._build_setting_option_selection_reply(
                message,
                setting_option_pending_action,
            )
            _ = self.memory_store.append_assistant_turn(
                message.session_id,
                reply.text,
                setting_option_pending_action.intent,
            )
            return reply

        display_mode_pending_action = self._build_display_mode_card_pending_action(message)
        if display_mode_pending_action is not None:
            _ = self.memory_store.set_pending_action(
                message.session_id,
                message.user_id,
                display_mode_pending_action,
            )
            reply = self._build_display_mode_selection_reply(
                message,
                display_mode_pending_action,
            )
            _ = self.memory_store.append_assistant_turn(
                message.session_id,
                reply.text,
                display_mode_pending_action.intent,
            )
            return reply

        camera_mode_pending_action = self._build_camera_mode_card_pending_action(message)
        if camera_mode_pending_action is not None:
            _ = self.memory_store.set_pending_action(
                message.session_id,
                message.user_id,
                camera_mode_pending_action,
            )
            reply = await self._build_camera_mode_selection_reply(
                message,
                camera_mode_pending_action,
            )
            _ = self.memory_store.append_assistant_turn(
                message.session_id,
                reply.text,
                camera_mode_pending_action.intent,
            )
            return reply

        decision = await self.provider.analyze_message(message, session)

        proposal = decision.action_proposal
        if proposal is not None and proposal.intent == Intent.RESET_CONTEXT:
            return self._reset_session(
                message,
                decision.reply_text or "Session context cleared.",
            )

        if decision.pending_action is not None:
            _ = self.memory_store.set_pending_action(
                message.session_id,
                message.user_id,
                decision.pending_action,
            )
            reply = await self._build_pending_reply(message, decision.pending_action)
            _ = self.memory_store.append_assistant_turn(
                message.session_id,
                reply.text,
                decision.pending_action.intent,
            )
            return reply

        missing_target_pending_action = self._build_missing_target_pending_action(
            proposal
        )
        if missing_target_pending_action is not None:
            _ = self.memory_store.set_pending_action(
                message.session_id,
                message.user_id,
                missing_target_pending_action,
            )
            reply = await self._build_pending_reply(
                message, missing_target_pending_action
            )
            _ = self.memory_store.append_assistant_turn(
                message.session_id,
                reply.text,
                missing_target_pending_action.intent,
            )
            return reply

        if proposal is None:
            reply_text = decision.reply_text or "I couldn't determine the next action."
            _ = self.memory_store.append_assistant_turn(message.session_id, reply_text)
            return OutboundReply(text=reply_text, room_id=message.room_id)

        if (
            proposal.intent == Intent.CHAT
            and proposal.summary == "Start admin login approval."
        ):
            approval_request = self.approval_manager.create_admin_auth_request(message)
            reply = self._build_approval_reply(
                approval_request.request_id,
                approval_request.title,
                approval_request.prompt,
                message.room_id,
            )
            _ = self.memory_store.append_assistant_turn(
                message.session_id,
                reply.text,
                Intent.CHAT,
            )
            return reply

        return await self._execute_proposal(message, proposal)

    async def _execute_proposal(
        self,
        message: InboundUserMessage,
        proposal: ActionProposal,
    ) -> OutboundReply:
        policy_decision = self.policy_evaluator.evaluate(
            proposal, message.preferred_mode
        )
        if policy_decision.requires_approval:
            execution_request = self.mode_router.build_request(
                message,
                proposal,
                policy_decision,
            )
            approval_request = self.approval_manager.create_action_approval(
                message,
                execution_request,
                f"Approve {proposal.intent.value} for {execution_request.target_device or 'the selected device'}.",
            )
            reply = self._build_approval_reply(
                approval_request.request_id,
                approval_request.title,
                approval_request.prompt,
                message.room_id,
            )
            _ = self.memory_store.append_assistant_turn(
                message.session_id,
                reply.text,
                proposal.intent,
            )
            return reply

        execution_result = await self.mode_router.execute(
            message, proposal, policy_decision
        )
        reply_text = self._format_execution_result(
            execution_result, policy_decision.reason
        )
        reply_markdown = await self._render_execution_markdown(
            execution_result,
            policy_decision.reason,
            reply_text,
        )
        _ = self.memory_store.append_assistant_turn(
            message.session_id, reply_text, proposal.intent
        )
        return OutboundReply(
            text=reply_text,
            markdown=reply_markdown,
            room_id=message.room_id,
        )

    def _reset_session(
        self,
        message: InboundUserMessage,
        reply_text: str = "I cleared the session context. Ask for a device status whenever you're ready.",
    ) -> OutboundReply:
        self.memory_store.reset(message.session_id, message.user_id)
        _ = self.memory_store.append_assistant_turn(
            message.session_id, reply_text, Intent.RESET_CONTEXT
        )
        return OutboundReply(text=reply_text, room_id=message.room_id)

    async def _handle_pending_follow_up(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        updated_pending_action = self._collect_pending_follow_up(
            pending_action, message.text
        )
        next_missing_field = self._next_missing_pending_field(updated_pending_action)
        if next_missing_field is not None:
            _ = self.memory_store.set_pending_action(
                message.session_id,
                message.user_id,
                updated_pending_action,
            )
            reply = await self._build_pending_reply(message, updated_pending_action)
            _ = self.memory_store.append_assistant_turn(
                message.session_id,
                reply.text,
                updated_pending_action.intent,
            )
            return reply

        _ = self.memory_store.clear_pending_action(message.session_id, message.user_id)
        proposal = self._build_action_proposal_from_pending(updated_pending_action)
        if proposal is None:
            reply_text = "I couldn't determine the next action."
            _ = self.memory_store.append_assistant_turn(message.session_id, reply_text)
            return OutboundReply(text=reply_text, room_id=message.room_id)
        return await self._execute_proposal(message, proposal)

    async def resume_pending_action_selection(
        self,
        pending_action_id: str,
        field_name: str,
        selected_value: str | None,
        user_id: str,
        room_id: str | None,
        person_email: str | None = None,
        *,
        cancel: bool = False,
        setting_field_name: str | None = None,
        setting_value: str | None = None,
    ) -> tuple[OutboundReply, bool]:
        pending_lookup = self.memory_store.get_pending_action_by_id(pending_action_id)
        if pending_lookup is None:
            return (
                OutboundReply(
                    text="That selection request is no longer active.",
                    room_id=room_id,
                ),
                True,
            )

        session_id, pending_user_id, pending_action = pending_lookup
        if pending_user_id != user_id:
            return (
                OutboundReply(
                    text="This selection card belongs to another user.",
                    room_id=room_id,
                ),
                False,
            )

        if field_name not in {"target_device", "display_mode", "camera_mode", "setting_value"}:
            reply = OutboundReply(
                text="That selection request is no longer valid.",
                room_id=room_id,
            )
            _ = self.memory_store.clear_pending_action(session_id, pending_user_id)
            _ = self.memory_store.append_assistant_turn(
                session_id,
                reply.text,
                pending_action.intent,
            )
            return reply, True

        if cancel:
            _ = self.memory_store.clear_pending_action(session_id, pending_user_id)
            reply = OutboundReply(
                text="Okay, I cancelled that request.",
                room_id=room_id,
            )
            _ = self.memory_store.append_assistant_turn(
                session_id,
                reply.text,
                pending_action.intent,
            )
            return reply, True

        if (
            field_name == "setting_value"
            and (not isinstance(setting_value, str) or not setting_value.strip())
            and isinstance(selected_value, str)
            and selected_value.strip()
        ):
            setting_value = selected_value.strip()
            selected_value = pending_action.target_device

        if (
            field_name == "setting_value"
            and isinstance(setting_value, str)
            and setting_value.strip()
            and (
                not isinstance(selected_value, str) or not selected_value.strip()
            )
        ):
            selected_value = pending_action.target_device

        if not isinstance(selected_value, str) or not selected_value.strip():
            fallback_text = self._build_follow_up_question(pending_action)
            if field_name == "setting_value":
                reply = await self._build_setting_option_selection_reply(
                    InboundUserMessage(
                        session_id=session_id,
                        user_id=user_id,
                        text="",
                        source=MessageSource.WEBEX,
                        room_id=room_id,
                        person_email=person_email,
                    ),
                    pending_action,
                )
            else:
                reply = OutboundReply(text=fallback_text, room_id=room_id)
            _ = self.memory_store.append_assistant_turn(
                session_id,
                reply.text,
                pending_action.intent,
            )
            return reply, False

        updated_pending_action = pending_action.model_copy(deep=True)
        if field_name == "setting_value":
            if isinstance(selected_value, str) and selected_value.strip():
                updated_pending_action.target_device = selected_value.strip()
            if setting_field_name is None and setting_value is None:
                proposal = updated_pending_action.action_proposal
                if proposal is not None:
                    proposal_setting = self._get_proposal_setting_field_and_value(
                        proposal
                    )
                    if proposal_setting is not None:
                        setting_field_name, setting_value = proposal_setting
                        updated_pending_action.action_proposal = None
            if not self._apply_pending_setting_selection(
                updated_pending_action,
                setting_field_name,
                setting_value,
            ):
                reply = OutboundReply(
                    text="That setting selection is no longer valid.",
                    room_id=room_id,
                )
                _ = self.memory_store.append_assistant_turn(
                    session_id,
                    reply.text,
                    pending_action.intent,
                )
                return reply, False
        elif field_name == "display_mode":
            try:
                updated_pending_action.display_mode = DisplayMode(selected_value.strip())
            except ValueError:
                reply = OutboundReply(
                    text="That display mode selection is no longer valid.",
                    room_id=room_id,
                )
                _ = self.memory_store.append_assistant_turn(
                    session_id,
                    reply.text,
                    pending_action.intent,
                )
                return reply, False
        elif field_name == "camera_mode":
            try:
                updated_pending_action.camera_mode = WritableCameraMode(
                    selected_value.strip()
                )
            except ValueError:
                reply = OutboundReply(
                    text="That camera mode selection is no longer valid.",
                    room_id=room_id,
                )
                _ = self.memory_store.append_assistant_turn(
                    session_id,
                    reply.text,
                    pending_action.intent,
                )
                return reply, False
        else:
            updated_pending_action.target_device = selected_value.strip()
            if updated_pending_action.action_proposal is not None:
                updated_pending_action.action_proposal = self._with_target_device(
                    updated_pending_action.action_proposal,
                    updated_pending_action.target_device,
                )
            if self._intent_needs_setting_option_selection(updated_pending_action.intent):
                _ = self._clear_proposal_target_setting_value(updated_pending_action)

        synthetic_message = InboundUserMessage(
            session_id=session_id,
            user_id=user_id,
            text=selected_value.strip(),
            source=MessageSource.WEBEX,
            room_id=room_id,
            person_email=person_email,
        )

        next_missing_field = self._next_missing_pending_field(updated_pending_action)
        if next_missing_field is not None:
            _ = self.memory_store.set_pending_action(
                session_id,
                pending_user_id,
                updated_pending_action,
            )
            reply = await self._build_pending_reply(
                synthetic_message,
                updated_pending_action,
            )
            _ = self.memory_store.append_assistant_turn(
                session_id,
                reply.text,
                updated_pending_action.intent,
            )
            return reply, True

        _ = self.memory_store.clear_pending_action(session_id, pending_user_id)
        proposal = self._build_action_proposal_from_pending(updated_pending_action)
        if proposal is None:
            reply = OutboundReply(
                text="I couldn't determine the next action.",
                room_id=room_id,
            )
            _ = self.memory_store.append_assistant_turn(session_id, reply.text)
            return reply, True

        return await self._execute_proposal(synthetic_message, proposal), True

    async def _build_pending_reply(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        next_missing_field = self._next_missing_pending_field(pending_action)
        fallback_text = self._build_follow_up_question(pending_action)
        if next_missing_field == "setting_value":
            return await self._build_setting_option_selection_reply(
                message,
                pending_action,
            )

        if (
            message.source == MessageSource.WEBEX
            and self._pending_action_needs_target_device(pending_action)
        ):
            fallback_text = self._build_target_device_follow_up_text(
                message,
                pending_action,
                fallback_text,
            )
            card_reply = await self._build_target_device_selection_reply(
                message,
                pending_action,
                fallback_text,
            )
            if card_reply is not None:
                return card_reply

        if next_missing_field != "target_device":
            return OutboundReply(text=fallback_text, room_id=message.room_id)
        return OutboundReply(text=fallback_text, room_id=message.room_id)

    def _setting_option_specs(self) -> dict[Intent, dict[str, object]]:
        return card_builders.setting_option_specs()

    def _build_setting_option_card_pending_action(
        self, message: InboundUserMessage
    ) -> PendingActionProposal | None:
        return card_builders.build_setting_option_card_pending_action(self, message)

    async def _build_setting_option_selection_reply(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        return await card_builders.build_setting_option_selection_reply(
            self, message, pending_action
        )

    async def _load_device_choices(self) -> list[dict[str, str]]:
        return await card_builders.load_device_choices(self)

    def _normalize_capability_product(self, product: str | None) -> str:
        return card_builders.normalize_capability_product(product)

    def _device_capabilities(self, device: OrganizationDeviceRecord) -> set[str]:
        return card_builders.device_capabilities(self, device)

    def _capability_labels(self, capabilities: set[str]) -> list[str]:
        return card_builders.capability_labels(self, capabilities)

    def _device_supports_intent(
        self, device: OrganizationDeviceRecord, intent: Intent | None
    ) -> bool:
        return card_builders.device_supports_intent(self, device, intent)

    async def _load_device_choices_for_intent(
        self, intent: Intent | None
    ) -> list[dict[str, str]]:
        return await card_builders.load_device_choices_for_intent(self, intent)

    def _apply_pending_setting_selection(
        self,
        pending_action: PendingActionProposal,
        setting_field_name: str | None,
        setting_value: str | None,
    ) -> bool:
        if not isinstance(setting_field_name, str) or not isinstance(setting_value, str):
            return False
        normalized_value = setting_value.strip()
        bool_value: bool | None
        if normalized_value.casefold() == "true":
            bool_value = True
        elif normalized_value.casefold() == "false":
            bool_value = False
        else:
            bool_value = None
        try:
            if pending_action.intent == Intent.SET_MICROPHONE_MUTE and setting_field_name == "muted" and bool_value is not None:
                pending_action.action_proposal = ActionProposal(
                    intent=Intent.SET_MICROPHONE_MUTE,
                    summary=pending_action.summary,
                    confidence=pending_action.confidence,
                    set_microphone_mute=SetMicrophoneMuteParams(
                        target_device=pending_action.target_device or "",
                        muted=bool_value,
                    ),
                )
                return True
            if pending_action.intent == Intent.SET_VIDEO_MUTE and setting_field_name == "muted" and bool_value is not None:
                pending_action.action_proposal = ActionProposal(
                    intent=Intent.SET_VIDEO_MUTE,
                    summary=pending_action.summary,
                    confidence=pending_action.confidence,
                    set_video_mute=SetVideoMuteParams(
                        target_device=pending_action.target_device or "",
                        muted=bool_value,
                    ),
                )
                return True
            if pending_action.intent == Intent.SET_SELFVIEW and setting_field_name == "enabled" and bool_value is not None:
                pending_action.action_proposal = ActionProposal(
                    intent=Intent.SET_SELFVIEW,
                    summary=pending_action.summary,
                    confidence=pending_action.confidence,
                    set_selfview=SetSelfviewParams(
                        target_device=pending_action.target_device or "",
                        enabled=bool_value,
                    ),
                )
                return True
            if pending_action.intent == Intent.SET_SPEAKERTRACK and setting_field_name == "enabled" and bool_value is not None:
                pending_action.action_proposal = ActionProposal(
                    intent=Intent.SET_SPEAKERTRACK,
                    summary=pending_action.summary,
                    confidence=pending_action.confidence,
                    set_speakertrack=SetSpeakerTrackParams(
                        target_device=pending_action.target_device or "",
                        enabled=bool_value,
                    ),
                )
                return True
            if pending_action.intent == Intent.SET_STANDBY and setting_field_name == "enabled" and bool_value is not None:
                pending_action.action_proposal = ActionProposal(
                    intent=Intent.SET_STANDBY,
                    summary=pending_action.summary,
                    confidence=pending_action.confidence,
                    set_standby=SetStandbyParams(
                        target_device=pending_action.target_device or "",
                        enabled=bool_value,
                    ),
                )
                return True
            if pending_action.intent == Intent.SET_PRESENTATION and setting_field_name == "enabled" and bool_value is not None:
                pending_action.action_proposal = ActionProposal(
                    intent=Intent.SET_PRESENTATION,
                    summary=pending_action.summary,
                    confidence=pending_action.confidence,
                    set_presentation=SetPresentationParams(
                        target_device=pending_action.target_device or "",
                        enabled=bool_value,
                    ),
                )
                return True
            if pending_action.intent == Intent.SET_MICROPHONE_MODE and setting_field_name == "mode":
                pending_action.action_proposal = ActionProposal(
                    intent=Intent.SET_MICROPHONE_MODE,
                    summary=pending_action.summary,
                    confidence=pending_action.confidence,
                    set_microphone_mode=SetMicrophoneModeParams(
                        target_device=pending_action.target_device or "",
                        mode=MicrophoneProcessingMode(normalized_value),
                    ),
                )
                return True
        except ValueError:
            return False
        return False

    async def _build_target_device_selection_reply(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
        fallback_text: str,
    ) -> OutboundReply | None:
        return await card_builders.build_target_device_selection_reply(
            self, message, pending_action, fallback_text
        )

    def _display_mode_choices(self) -> list[tuple[str, str, str]]:
        return card_builders.display_mode_choices()

    def _build_display_mode_card_pending_action(
        self, message: InboundUserMessage
    ) -> PendingActionProposal | None:
        return card_builders.build_display_mode_card_pending_action(self, message)

    def _extract_display_mode_target_device(self, message: InboundUserMessage) -> str | None:
        return text_extractors.extract_display_mode_target_device(message)

    def _build_display_mode_selection_reply(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        return card_builders.build_display_mode_selection_reply(
            self, message, pending_action
        )

    def _camera_mode_title(self, mode: str) -> str:
        return card_builders.camera_mode_title(mode)

    def _build_camera_mode_card_pending_action(
        self, message: InboundUserMessage
    ) -> PendingActionProposal | None:
        return card_builders.build_camera_mode_card_pending_action(self, message)

    def _extract_explicit_camera_mode(self, normalized_text: str) -> WritableCameraMode | None:
        return text_extractors.extract_explicit_camera_mode(normalized_text)

    def _extract_camera_mode_target_device(self, message: InboundUserMessage) -> str | None:
        return text_extractors.extract_camera_mode_target_device(message)

    async def _build_camera_mode_selection_reply(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        return await card_builders.build_camera_mode_selection_reply(
            self, message, pending_action
        )

    def _is_reset_message(self, text: str) -> bool:
        return text_extractors.is_reset_message(text)

    def _next_missing_pending_field(
        self, pending_action: PendingActionProposal
    ) -> str | None:
        if pending_action.action_proposal is not None:
            if self._proposal_has_missing_target_device(
                pending_action.action_proposal
            ):
                return "target_device"
            if (
                self._intent_needs_setting_option_selection(pending_action.intent)
                and self._get_proposal_setting_field_and_value(
                    pending_action.action_proposal
                ) is None
            ):
                return "setting_value"

        if pending_action.intent == Intent.WEBEX_JOIN:
            if pending_action.meeting_identifier is None:
                return "meeting_identifier"
            if pending_action.target_device is None:
                return "target_device"
        elif pending_action.intent == Intent.DIAL:
            if pending_action.address is None:
                return "address"
            if pending_action.target_device is None:
                return "target_device"
        elif pending_action.intent == Intent.SET_VOLUME:
            if pending_action.level is None:
                return "level"
            if pending_action.target_device is None:
                return "target_device"
        elif pending_action.intent == Intent.SET_DISPLAY_MODE:
            if pending_action.display_mode is None:
                return "display_mode"
            if pending_action.target_device is None:
                return "target_device"
        elif pending_action.intent == Intent.SET_CAMERA_MODE:
            if pending_action.camera_mode is None:
                return "camera_mode"
            if pending_action.target_device is None:
                return "target_device"
        return None

    def _build_follow_up_question(self, pending_action: PendingActionProposal) -> str:
        return card_builders.build_follow_up_question(self, pending_action)

    def _build_target_device_follow_up_text(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
        fallback_text: str,
    ) -> str:
        return card_builders.build_target_device_follow_up_text(
            self, message, pending_action, fallback_text
        )

    def _get_pending_bool_value(
        self, pending_action: PendingActionProposal, field_name: str
    ) -> bool | None:
        if pending_action.action_proposal is None:
            return None
        payload = self._get_action_payload(pending_action.action_proposal)
        value = getattr(payload, field_name, None) if payload is not None else None
        return value if isinstance(value, bool) else None

    def _intent_needs_setting_option_selection(self, intent: Intent) -> bool:
        return intent in self._setting_option_specs()

    def _get_proposal_setting_field_and_value(
        self, proposal: ActionProposal
    ) -> tuple[str, str] | None:
        payload = self._get_action_payload(proposal)
        if payload is None:
            return None
        spec = self._setting_option_specs().get(proposal.intent)
        if spec is None:
            return None
        field_name = str(spec["field"])
        raw_value = getattr(payload, field_name, None)
        if isinstance(raw_value, bool):
            return field_name, "true" if raw_value else "false"
        if isinstance(raw_value, MicrophoneProcessingMode):
            return field_name, raw_value.value
        if isinstance(raw_value, str):
            return field_name, raw_value
        return None

    def _clear_proposal_target_setting_value(
        self, pending_action: PendingActionProposal
    ) -> bool:
        proposal = pending_action.action_proposal
        if proposal is None:
            return False
        payload = self._get_action_payload(proposal)
        spec = self._setting_option_specs().get(proposal.intent)
        if payload is None or spec is None:
            return False
        field_name = str(spec["field"])
        if not hasattr(payload, field_name):
            return False
        try:
            setattr(payload, field_name, None)
        except Exception:
            return False
        return True

    def _pending_action_needs_target_device(
        self, pending_action: PendingActionProposal
    ) -> bool:
        if pending_action.action_proposal is not None:
            return self._proposal_has_missing_target_device(
                pending_action.action_proposal
            )
        return pending_action.target_device is None and intent_requires_target_device(
            pending_action.intent
        )

    def _collect_pending_follow_up(
        self,
        pending_action: PendingActionProposal,
        text: str,
    ) -> PendingActionProposal:
        updated_pending_action = pending_action.model_copy(deep=True)
        trailing_target_device = self._extract_trailing_target_device(text)

        if (
            updated_pending_action.action_proposal is not None
            and self._proposal_has_missing_target_device(
                updated_pending_action.action_proposal
            )
        ):
            target_device = self._resolve_pending_target_device_response(
                updated_pending_action.intent,
                text,
                trailing_target_device,
            )
            if target_device is not None:
                updated_pending_action.target_device = target_device
                updated_pending_action.action_proposal = self._with_target_device(
                    updated_pending_action.action_proposal,
                    target_device,
                )
            return updated_pending_action

        if updated_pending_action.intent == Intent.WEBEX_JOIN:
            meeting_identifier_was_missing = (
                updated_pending_action.meeting_identifier is None
            )
            if updated_pending_action.meeting_identifier is None:
                updated_pending_action.meeting_identifier = (
                    self._extract_follow_up_webex_meeting_identifier(text)
                )
            if updated_pending_action.target_device is None:
                if trailing_target_device is not None:
                    updated_pending_action.target_device = trailing_target_device
                elif not meeting_identifier_was_missing:
                    updated_pending_action.target_device = (
                        self._resolve_pending_target_device_response(
                            updated_pending_action.intent,
                            text,
                            trailing_target_device,
                        )
                    )
            return updated_pending_action

        if updated_pending_action.intent == Intent.DIAL:
            address_was_missing = updated_pending_action.address is None
            if updated_pending_action.address is None:
                updated_pending_action.address = self._extract_follow_up_dial_address(
                    text
                )
            if updated_pending_action.target_device is None:
                if trailing_target_device is not None:
                    updated_pending_action.target_device = trailing_target_device
                elif not address_was_missing:
                    updated_pending_action.target_device = (
                        self._resolve_pending_target_device_response(
                            updated_pending_action.intent,
                            text,
                            trailing_target_device,
                        )
                    )
            return updated_pending_action

        if updated_pending_action.intent == Intent.SET_VOLUME:
            level_was_missing = updated_pending_action.level is None
            if updated_pending_action.level is None:
                updated_pending_action.level = self._extract_follow_up_volume_level(
                    text
                )
            if updated_pending_action.target_device is None:
                if trailing_target_device is not None:
                    updated_pending_action.target_device = trailing_target_device
                elif not level_was_missing:
                    updated_pending_action.target_device = (
                        self._resolve_pending_target_device_response(
                            updated_pending_action.intent,
                            text,
                            trailing_target_device,
                        )
                    )
            return updated_pending_action

        return updated_pending_action

    def _build_action_proposal_from_pending(
        self, pending_action: PendingActionProposal
    ) -> ActionProposal | None:
        if pending_action.action_proposal is not None:
            return (
                pending_action.action_proposal
                if not self._proposal_has_missing_target_device(
                    pending_action.action_proposal
                )
                else None
            )

        if (
            pending_action.intent == Intent.WEBEX_JOIN
            and pending_action.meeting_identifier is not None
            and pending_action.target_device is not None
        ):
            return ActionProposal(
                intent=Intent.WEBEX_JOIN,
                summary=pending_action.summary,
                confidence=pending_action.confidence,
                webex_join=WebexJoinParams(
                    target_device=pending_action.target_device,
                    meeting_identifier=pending_action.meeting_identifier,
                ),
            )

        if (
            pending_action.intent == Intent.DIAL
            and pending_action.address is not None
            and pending_action.target_device is not None
        ):
            return ActionProposal(
                intent=Intent.DIAL,
                summary=pending_action.summary,
                confidence=pending_action.confidence,
                dial=DialParams(
                    target_device=pending_action.target_device,
                    address=pending_action.address,
                ),
            )

        if (
            pending_action.intent == Intent.SET_VOLUME
            and pending_action.level is not None
            and pending_action.target_device is not None
        ):
            return ActionProposal(
                intent=Intent.SET_VOLUME,
                summary=pending_action.summary,
                confidence=pending_action.confidence,
                set_volume=SetVolumeParams(
                    target_device=pending_action.target_device,
                    level=pending_action.level,
                ),
            )

        if (
            pending_action.intent == Intent.SET_DISPLAY_MODE
            and pending_action.display_mode is not None
            and pending_action.target_device is not None
        ):
            return ActionProposal(
                intent=Intent.SET_DISPLAY_MODE,
                summary=pending_action.summary,
                confidence=pending_action.confidence,
                set_display_mode=SetDisplayModeParams(
                    target_device=pending_action.target_device,
                    mode=pending_action.display_mode,
                ),
            )

        if (
            pending_action.intent == Intent.SET_CAMERA_MODE
            and pending_action.camera_mode is not None
            and pending_action.target_device is not None
        ):
            return ActionProposal(
                intent=Intent.SET_CAMERA_MODE,
                summary=pending_action.summary,
                confidence=pending_action.confidence,
                set_camera_mode=SetCameraModeParams(
                    target_device=pending_action.target_device,
                    mode=pending_action.camera_mode,
                ),
            )

        return None

    def _build_missing_target_pending_action(
        self, proposal: ActionProposal | None
    ) -> PendingActionProposal | None:
        if proposal is None or not self._proposal_has_missing_target_device(proposal):
            return None
        return PendingActionProposal(
            intent=proposal.intent,
            summary=proposal.summary,
            confidence=proposal.confidence,
            action_proposal=proposal.model_copy(deep=True),
        )

    def _proposal_has_missing_target_device(self, proposal: ActionProposal) -> bool:
        if not intent_requires_target_device(proposal.intent):
            return False
        payload = self._get_action_payload(proposal)
        if payload is None:
            return False
        target_device = getattr(payload, "target_device", None)
        return not isinstance(target_device, str) or not target_device.strip()

    def _get_action_payload(self, proposal: ActionProposal) -> object | None:
        payload_name = get_action_payload_field(proposal.intent)
        if payload_name == "get_status":
            return proposal.get_status
        if payload_name == "get_environment_info":
            return proposal.get_environment_info
        if payload_name == "get_camera_mode":
            return proposal.get_camera_mode
        if payload_name == "get_room_booking":
            return proposal.get_room_booking
        if payload_name == "list_devices":
            return proposal.list_devices
        if payload_name == "webex_join":
            return proposal.webex_join
        if payload_name == "join_obtp":
            return proposal.join_obtp
        if payload_name == "dial":
            return proposal.dial
        if payload_name == "hang_up":
            return proposal.hang_up
        if payload_name == "send_dtmf":
            return proposal.send_dtmf
        if payload_name == "set_microphone_mute":
            return proposal.set_microphone_mute
        if payload_name == "set_microphone_mode":
            return proposal.set_microphone_mode
        if payload_name == "set_volume":
            return proposal.set_volume
        if payload_name == "set_video_mute":
            return proposal.set_video_mute
        if payload_name == "set_selfview":
            return proposal.set_selfview
        if payload_name == "set_camera_mode":
            return proposal.set_camera_mode
        if payload_name == "set_layout":
            return proposal.set_layout
        if payload_name == "set_presentation":
            return proposal.set_presentation
        if payload_name == "switch_input_source":
            return proposal.switch_input_source
        if payload_name == "assign_matrix":
            return proposal.assign_matrix
        if payload_name == "unassign_matrix":
            return proposal.unassign_matrix
        if payload_name == "swap_matrix":
            return proposal.swap_matrix
        if payload_name == "set_display_mode":
            return proposal.set_display_mode
        if payload_name == "set_display_role":
            return proposal.set_display_role
        if payload_name == "activate_camera_preset":
            return proposal.activate_camera_preset
        if payload_name == "adjust_camera_position":
            return proposal.adjust_camera_position
        if payload_name == "set_speakertrack":
            return proposal.set_speakertrack
        if payload_name == "set_standby":
            return proposal.set_standby
        if payload_name == "reboot":
            return proposal.reboot
        if payload_name == "factory_reset":
            return proposal.factory_reset
        return None

    def _with_target_device(
        self, proposal: ActionProposal, target_device: str
    ) -> ActionProposal:
        payload_name = get_action_payload_field(proposal.intent)
        if payload_name == "get_status" and proposal.get_status is not None:
            return proposal.model_copy(
                update={
                    "get_status": proposal.get_status.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if (
            payload_name == "get_environment_info"
            and proposal.get_environment_info is not None
        ):
            return proposal.model_copy(
                update={
                    "get_environment_info": proposal.get_environment_info.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "get_camera_mode" and proposal.get_camera_mode is not None:
            return proposal.model_copy(
                update={
                    "get_camera_mode": proposal.get_camera_mode.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "get_room_booking" and proposal.get_room_booking is not None:
            return proposal.model_copy(
                update={
                    "get_room_booking": proposal.get_room_booking.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "webex_join" and proposal.webex_join is not None:
            return proposal.model_copy(
                update={
                    "webex_join": proposal.webex_join.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "join_obtp" and proposal.join_obtp is not None:
            return proposal.model_copy(
                update={
                    "join_obtp": proposal.join_obtp.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "dial" and proposal.dial is not None:
            return proposal.model_copy(
                update={
                    "dial": proposal.dial.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "hang_up" and proposal.hang_up is not None:
            return proposal.model_copy(
                update={
                    "hang_up": proposal.hang_up.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "send_dtmf" and proposal.send_dtmf is not None:
            return proposal.model_copy(
                update={
                    "send_dtmf": proposal.send_dtmf.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if (
            payload_name == "set_microphone_mute"
            and proposal.set_microphone_mute is not None
        ):
            return proposal.model_copy(
                update={
                    "set_microphone_mute": proposal.set_microphone_mute.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if (
            payload_name == "set_microphone_mode"
            and proposal.set_microphone_mode is not None
        ):
            return proposal.model_copy(
                update={
                    "set_microphone_mode": proposal.set_microphone_mode.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_volume" and proposal.set_volume is not None:
            return proposal.model_copy(
                update={
                    "set_volume": proposal.set_volume.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_video_mute" and proposal.set_video_mute is not None:
            return proposal.model_copy(
                update={
                    "set_video_mute": proposal.set_video_mute.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_selfview" and proposal.set_selfview is not None:
            return proposal.model_copy(
                update={
                    "set_selfview": proposal.set_selfview.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_camera_mode" and proposal.set_camera_mode is not None:
            return proposal.model_copy(
                update={
                    "set_camera_mode": proposal.set_camera_mode.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_layout" and proposal.set_layout is not None:
            return proposal.model_copy(
                update={
                    "set_layout": proposal.set_layout.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_presentation" and proposal.set_presentation is not None:
            return proposal.model_copy(
                update={
                    "set_presentation": proposal.set_presentation.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if (
            payload_name == "switch_input_source"
            and proposal.switch_input_source is not None
        ):
            return proposal.model_copy(
                update={
                    "switch_input_source": proposal.switch_input_source.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "assign_matrix" and proposal.assign_matrix is not None:
            return proposal.model_copy(
                update={
                    "assign_matrix": proposal.assign_matrix.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "unassign_matrix" and proposal.unassign_matrix is not None:
            return proposal.model_copy(
                update={
                    "unassign_matrix": proposal.unassign_matrix.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "swap_matrix" and proposal.swap_matrix is not None:
            return proposal.model_copy(
                update={
                    "swap_matrix": proposal.swap_matrix.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_display_mode" and proposal.set_display_mode is not None:
            return proposal.model_copy(
                update={
                    "set_display_mode": proposal.set_display_mode.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_display_role" and proposal.set_display_role is not None:
            return proposal.model_copy(
                update={
                    "set_display_role": proposal.set_display_role.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if (
            payload_name == "activate_camera_preset"
            and proposal.activate_camera_preset is not None
        ):
            return proposal.model_copy(
                update={
                    "activate_camera_preset": proposal.activate_camera_preset.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if (
            payload_name == "adjust_camera_position"
            and proposal.adjust_camera_position is not None
        ):
            return proposal.model_copy(
                update={
                    "adjust_camera_position": proposal.adjust_camera_position.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_speakertrack" and proposal.set_speakertrack is not None:
            return proposal.model_copy(
                update={
                    "set_speakertrack": proposal.set_speakertrack.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "set_standby" and proposal.set_standby is not None:
            return proposal.model_copy(
                update={
                    "set_standby": proposal.set_standby.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "reboot" and proposal.reboot is not None:
            return proposal.model_copy(
                update={
                    "reboot": proposal.reboot.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        if payload_name == "factory_reset" and proposal.factory_reset is not None:
            return proposal.model_copy(
                update={
                    "factory_reset": proposal.factory_reset.model_copy(
                        update={"target_device": target_device}
                    )
                }
            )
        return proposal

    def _extract_follow_up_webex_meeting_identifier(self, text: str) -> str | None:
        return text_extractors.extract_follow_up_webex_meeting_identifier(text)

    def _extract_follow_up_dial_address(self, text: str) -> str | None:
        return text_extractors.extract_follow_up_dial_address(text)

    def _extract_follow_up_volume_level(self, text: str) -> int | None:
        return text_extractors.extract_follow_up_volume_level(text)

    def _extract_trailing_target_device(self, text: str) -> str | None:
        return text_extractors.extract_trailing_target_device(text)

    def _strip_trailing_target_clause(self, text: str) -> str:
        return text_extractors.strip_trailing_target_clause(text)

    def _extract_direct_target_device_response(self, text: str) -> str | None:
        return text_extractors.extract_direct_target_device_response(text)

    def _resolve_pending_target_device_response(
        self,
        intent: Intent,
        text: str,
        trailing_target_device: str | None,
    ) -> str | None:
        if trailing_target_device is not None:
            return trailing_target_device
        if self._looks_like_pending_intent_follow_up(intent, text):
            return None
        return self._extract_direct_target_device_response(text)

    def _looks_like_pending_intent_follow_up(self, intent: Intent, text: str) -> bool:
        lowered = text.strip().lower()
        if not lowered:
            return False
        intent_keywords: dict[Intent, tuple[str, ...]] = {
            Intent.GET_STATUS: ("status", "상태"),
            Intent.GET_ENVIRONMENT_INFO: (
                "environment",
                "temperature",
                "humidity",
                "air quality",
                "환경",
                "온도",
                "습도",
            ),
            Intent.GET_CAMERA_MODE: (
                "camera mode",
                "camera framing",
                "frames",
                "speaker closeup",
                "best overview",
                "카메라",
            ),
            Intent.GET_ROOM_BOOKING: ("booking", "obtp", "예약"),
            Intent.WEBEX_JOIN: ("webex", "join", "meeting", "미팅"),
            Intent.JOIN_OBTP: ("obtp", "join", "meeting", "미팅"),
            Intent.DIAL: ("dial", "call", "sip", "전화", "통화"),
            Intent.HANG_UP: ("hang up", "hangup", "disconnect"),
            Intent.SEND_DTMF: ("dtmf", "tone", "digits"),
            Intent.SET_MICROPHONE_MUTE: (
                "mute",
                "unmute",
                "mic",
                "microphone",
                "마이크",
                "음소거",
                "뮤트",
                "언뮤트",
            ),
            Intent.SET_MICROPHONE_MODE: ("microphone mode", "mic mode"),
            Intent.SET_VOLUME: ("volume", "볼륨"),
            Intent.SET_VIDEO_MUTE: (
                "video mute",
                "mute video",
                "camera off",
                "camera on",
                "stop video",
                "start video",
                "비디오",
                "카메라",
            ),
            Intent.SET_SELFVIEW: ("selfview", "self view"),
            Intent.SET_CAMERA_MODE: (
                "camera mode",
                "frames",
                "speaker closeup",
                "best overview",
                "카메라",
            ),
            Intent.SET_LAYOUT: ("layout",),
            Intent.SET_PRESENTATION: ("presentation", "share", "공유"),
            Intent.SWITCH_INPUT_SOURCE: ("input source", "source input", "source"),
            Intent.ASSIGN_MATRIX: ("matrix", "output"),
            Intent.UNASSIGN_MATRIX: ("matrix", "output"),
            Intent.SWAP_MATRIX: ("matrix", "swap", "output"),
            Intent.SET_DISPLAY_MODE: (
                "display mode",
                "single",
                "dual",
                "triple",
            ),
            Intent.SET_DISPLAY_ROLE: (
                "display role",
                "presentation-only",
                "recorder",
                "connector",
            ),
            Intent.ACTIVATE_CAMERA_PRESET: ("camera preset", "preset"),
            Intent.ADJUST_CAMERA_POSITION: ("camera", "pan", "tilt", "zoom"),
            Intent.SET_SPEAKERTRACK: ("speakertrack", "speaker track"),
            Intent.SET_STANDBY: ("standby",),
            Intent.REBOOT: ("reboot", "restart", "재시작"),
            Intent.FACTORY_RESET: ("factory reset", "reset"),
        }
        keywords = intent_keywords.get(intent)
        return keywords is not None and any(keyword in lowered for keyword in keywords)

    async def execute_approved_request(
        self, approval_request: ApprovalRequest
    ) -> OutboundReply:
        execution_request = approval_request.execution_request
        if execution_request is None:
            return OutboundReply(
                text="Approval recorded. No executable action was attached to this request.",
                room_id=approval_request.room_id,
            )
        if approval_request.status != ApprovalStatus.APPROVED:
            return OutboundReply(
                text="Approval was not granted, so no action was applied.",
                room_id=approval_request.room_id,
            )

        executable_request = execution_request.model_copy(
            update={
                "approval_state": ApprovalState.APPROVED,
                "approval_request_id": approval_request.request_id,
            }
        )
        execution_result = await self.mode_router.execute_request(executable_request)
        reply_text = self._format_execution_result(
            execution_result,
            execution_request.reason,
        )
        reply_markdown = await self._render_execution_markdown(
            execution_result,
            execution_request.reason,
            reply_text,
        )
        if execution_result.status == ExecutionStatus.SUCCESS:
            _ = self.approval_manager.state_store.mark_approval_executed(
                approval_request.request_id
            )
        _ = self.memory_store.append_assistant_turn(
            approval_request.session_id,
            reply_text,
            execution_request.intent,
        )
        return OutboundReply(
            text=reply_text,
            markdown=reply_markdown,
            room_id=approval_request.room_id,
        )

    async def _render_execution_markdown(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
        canonical_text: str,
    ) -> str | None:
        return await formatters.render_execution_markdown(
            self.provider, execution_result, policy_reason, canonical_text
        )

    def _format_execution_result(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
    ) -> str:
        return formatters.format_execution_result(
            execution_result,
            policy_reason,
            device_capabilities=self._device_capabilities,
            capability_labels=self._capability_labels,
        )

    def _format_device_status_detail(
        self,
        status: object,
        message: str,
        policy_reason: str,
    ) -> str:
        return formatters.format_device_status_detail(status, message, policy_reason)

    def _format_device_list(
        self, devices: list[OrganizationDeviceRecord], policy_reason: str
    ) -> str:
        return formatters.format_device_list(
            devices,
            policy_reason,
            device_capabilities=self._device_capabilities,
            capability_labels=self._capability_labels,
        )

    def _build_approval_reply(
        self,
        request_id: str,
        title: str,
        prompt: str,
        room_id: str | None,
    ) -> OutboundReply:
        return card_builders.build_approval_reply(request_id, title, prompt, room_id)

    def _format_device_resolution_failure(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
    ) -> str:
        return formatters.format_device_resolution_failure(execution_result, policy_reason)
