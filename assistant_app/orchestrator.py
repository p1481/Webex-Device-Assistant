from __future__ import annotations

from collections.abc import Awaitable, Callable

from assistant_app.approval_manager import ApprovalManager
from assistant_app.memory_store import InMemorySessionStore
from assistant_app.mode_router import ModeRouter
from assistant_app.orchestration import (
    card_builders,
    formatters,
    pending_state,
    text_extractors,
)
from assistant_app.policy_evaluator import PolicyEvaluator
from assistant_app.providers.base import LLMProvider
from shared.contracts import (
    ActionProposal,
    ApprovalRequest,
    ApprovalState,
    ApprovalStatus,
    ExecutionResult,
    ExecutionStatus,
    InboundUserMessage,
    Intent,
    OrganizationDeviceRecord,
    OutboundReply,
    PendingActionProposal,
    WritableCameraMode,
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
        return pending_state.reset_session(self, message, reply_text)

    async def _handle_pending_follow_up(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        return await pending_state.handle_pending_follow_up(
            self, message, pending_action
        )

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
        return await pending_state.resume_pending_action_selection(
            self,
            pending_action_id,
            field_name,
            selected_value,
            user_id,
            room_id,
            person_email,
            cancel=cancel,
            setting_field_name=setting_field_name,
            setting_value=setting_value,
        )

    async def _build_pending_reply(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        return await pending_state.build_pending_reply(self, message, pending_action)

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
        return pending_state.apply_pending_setting_selection(
            self, pending_action, setting_field_name, setting_value
        )


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
        return pending_state.next_missing_pending_field(self, pending_action)

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
        return pending_state.get_pending_bool_value(self, pending_action, field_name)

    def _intent_needs_setting_option_selection(self, intent: Intent) -> bool:
        return pending_state.intent_needs_setting_option_selection(self, intent)

    def _get_proposal_setting_field_and_value(
        self, proposal: ActionProposal
    ) -> tuple[str, str] | None:
        return pending_state.get_proposal_setting_field_and_value(self, proposal)

    def _clear_proposal_target_setting_value(
        self, pending_action: PendingActionProposal
    ) -> bool:
        return pending_state.clear_proposal_target_setting_value(self, pending_action)

    def _pending_action_needs_target_device(
        self, pending_action: PendingActionProposal
    ) -> bool:
        return pending_state.pending_action_needs_target_device(self, pending_action)

    def _collect_pending_follow_up(
        self,
        pending_action: PendingActionProposal,
        text: str,
    ) -> PendingActionProposal:
        return pending_state.collect_pending_follow_up(self, pending_action, text)

    def _build_action_proposal_from_pending(
        self, pending_action: PendingActionProposal
    ) -> ActionProposal | None:
        return pending_state.build_action_proposal_from_pending(self, pending_action)

    def _build_missing_target_pending_action(
        self, proposal: ActionProposal | None
    ) -> PendingActionProposal | None:
        return pending_state.build_missing_target_pending_action(self, proposal)

    def _proposal_has_missing_target_device(self, proposal: ActionProposal) -> bool:
        return pending_state.proposal_has_missing_target_device(self, proposal)

    def _get_action_payload(self, proposal: ActionProposal) -> object | None:
        return pending_state.get_action_payload(proposal)

    def _with_target_device(
        self, proposal: ActionProposal, target_device: str
    ) -> ActionProposal:
        return pending_state.with_target_device(proposal, target_device)

    def _resolve_pending_target_device_response(
        self,
        intent: Intent,
        text: str,
        trailing_target_device: str | None,
    ) -> str | None:
        return pending_state.resolve_pending_target_device_response(
            self, intent, text, trailing_target_device
        )

    def _looks_like_pending_intent_follow_up(self, intent: Intent, text: str) -> bool:
        return pending_state.looks_like_pending_intent_follow_up(intent, text)

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
