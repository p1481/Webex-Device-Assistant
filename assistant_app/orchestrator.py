from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from assistant_app.memory_store import InMemorySessionStore
from assistant_app.mode_router import ModeRouter
from assistant_app.policy_evaluator import PolicyEvaluator
from assistant_app.approval_manager import ApprovalManager
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
    MessageSource,
    OrganizationDeviceRecord,
    OutboundReply,
    PendingActionProposal,
    MicrophoneProcessingMode,
    get_action_payload_field,
    intent_requires_target_device,
    SetVolumeParams,
    DialParams,
    WebexJoinParams,
    DisplayMode,
    SetDisplayModeParams,
    WritableCameraMode,
    SetCameraModeParams,
    SetMicrophoneMuteParams,
    SetMicrophoneModeParams,
    SetVideoMuteParams,
    SetSelfviewParams,
    SetSpeakerTrackParams,
    SetStandbyParams,
    SetPresentationParams,
)


class Orchestrator:
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

        if not isinstance(selected_value, str) or not selected_value.strip():
            fallback_text = self._build_follow_up_question(pending_action)
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
        return {
            Intent.SET_MICROPHONE_MUTE: {
                "title": "마이크 음소거 설정",
                "prompt": "마이크 음소거 상태를 선택해주세요.",
                "field": "muted",
                "choices": [("음소거", "true"), ("음소거 해제", "false")],
                "keywords": ("마이크", "mic", "microphone", "음소거", "뮤트"),
                "verbs": ("설정", "변경", "선택", "set", "change"),
            },
            Intent.SET_VIDEO_MUTE: {
                "title": "비디오 음소거 설정",
                "prompt": "비디오 음소거 상태를 선택해주세요.",
                "field": "muted",
                "choices": [("비디오 끄기", "true"), ("비디오 켜기", "false")],
                "keywords": ("비디오", "video mute", "camera off", "camera on"),
                "verbs": ("설정", "변경", "선택", "set", "change"),
            },
            Intent.SET_SELFVIEW: {
                "title": "셀프뷰 설정",
                "prompt": "셀프뷰 상태를 선택해주세요.",
                "field": "enabled",
                "choices": [("켜기", "true"), ("끄기", "false")],
                "keywords": ("selfview", "self view", "셀프뷰"),
                "verbs": ("설정", "변경", "선택", "set", "change"),
            },
            Intent.SET_SPEAKERTRACK: {
                "title": "SpeakerTrack 설정",
                "prompt": "SpeakerTrack 상태를 선택해주세요.",
                "field": "enabled",
                "choices": [("켜기", "true"), ("끄기", "false")],
                "keywords": ("speakertrack", "speaker track", "스피커트랙"),
                "verbs": ("설정", "변경", "선택", "set", "change"),
            },
            Intent.SET_STANDBY: {
                "title": "스탠바이 설정",
                "prompt": "스탠바이 상태를 선택해주세요.",
                "field": "enabled",
                "choices": [("켜기", "true"), ("끄기", "false")],
                "keywords": ("standby", "스탠바이"),
                "verbs": ("설정", "변경", "선택", "set", "change"),
            },
            Intent.SET_PRESENTATION: {
                "title": "프레젠테이션 설정",
                "prompt": "프레젠테이션 공유 상태를 선택해주세요.",
                "field": "enabled",
                "choices": [("시작", "true"), ("중지", "false")],
                "keywords": ("presentation", "share", "프레젠테이션", "공유"),
                "verbs": ("설정", "변경", "선택", "set", "change"),
            },
            Intent.SET_MICROPHONE_MODE: {
                "title": "마이크 모드 설정",
                "prompt": "마이크 처리 모드를 선택해주세요.",
                "field": "mode",
                "choices": [
                    ("Normal", MicrophoneProcessingMode.NORMAL.value),
                    ("Noise Reduction", MicrophoneProcessingMode.NOISE_REDUCTION.value),
                    ("Voice Optimized", MicrophoneProcessingMode.VOICE_OPTIMIZED.value),
                    ("Music Mode", MicrophoneProcessingMode.MUSIC_MODE.value),
                ],
                "keywords": ("microphone mode", "mic mode", "마이크 모드"),
                "verbs": ("설정", "변경", "선택", "set", "change"),
            },
        }

    def _build_setting_option_card_pending_action(
        self, message: InboundUserMessage
    ) -> PendingActionProposal | None:
        normalized = message.text.strip().casefold()
        compact = re.sub(r"\s+", "", normalized)
        for intent, spec in self._setting_option_specs().items():
            keywords = tuple(str(keyword).casefold() for keyword in spec["keywords"])  # type: ignore[index]
            verbs = tuple(str(verb).casefold() for verb in spec["verbs"])  # type: ignore[index]
            if not any(keyword in normalized or re.sub(r"\s+", "", keyword) in compact for keyword in keywords):
                continue
            if not any(verb in normalized or re.sub(r"\s+", "", verb) in compact for verb in verbs):
                continue
            return PendingActionProposal(
                intent=intent,
                summary=str(spec["title"]),
                target_device=self._extract_trailing_target_device(message.text) or message.target_device,
            )
        return None

    async def _build_setting_option_selection_reply(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        spec = self._setting_option_specs()[pending_action.intent]
        title = str(spec["title"])
        prompt = str(spec["prompt"])
        setting_field = str(spec["field"])
        choices = [
            {"title": title, "value": value}
            for title, value in spec["choices"]  # type: ignore[index]
        ]
        body: list[dict[str, object]] = [
            {"type": "TextBlock", "weight": "Bolder", "text": title},
            {"type": "TextBlock", "wrap": True, "text": prompt},
            {
                "type": "Input.ChoiceSet",
                "id": "settingValue",
                "style": "expanded",
                "isRequired": True,
                "choices": choices,
            },
        ]
        if pending_action.target_device:
            body.append(
                {
                    "type": "TextBlock",
                    "wrap": True,
                    "text": f"대상 장치: {pending_action.target_device}",
                }
            )
        else:
            device_choices = await self._load_device_choices()
            if device_choices:
                body.append(
                    {
                        "type": "Input.ChoiceSet",
                        "id": "selectedValue",
                        "style": "compact",
                        "isRequired": True,
                        "placeholder": "장치를 선택하세요",
                        "choices": device_choices,
                    }
                )
            else:
                body.append(
                    {
                        "type": "Input.ChoiceSet",
                        "id": "selectedValue",
                        "style": "compact",
                        "isRequired": True,
                        "placeholder": "장치 이름을 입력하세요",
                        "choices": [],
                    }
                )
        card: dict[str, object] = {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.0",
                "body": body,
                "actions": [
                    {
                        "type": "Action.Submit",
                        "title": "Apply",
                        "data": {
                            "kind": "entity_selection",
                            "pendingActionId": pending_action.pending_action_id,
                            "fieldName": "setting_value",
                            "settingFieldName": setting_field,
                            "selectionDecision": "submit",
                        },
                    },
                    {
                        "type": "Action.Submit",
                        "title": "Cancel",
                        "data": {
                            "kind": "entity_selection",
                            "pendingActionId": pending_action.pending_action_id,
                            "fieldName": "setting_value",
                            "selectionDecision": "cancel",
                        },
                    },
                ],
            },
        }
        return OutboundReply(
            text=prompt,
            markdown=f"**{title}**\n\n{prompt}",
            room_id=message.room_id,
            attachments=[card],
        )

    async def _load_device_choices(self) -> list[dict[str, str]]:
        if self.device_lister is None:
            return []
        try:
            devices = await self.device_lister()
        except Exception:
            return []
        choices: list[dict[str, str]] = []
        for device in devices[:10]:
            value = device.display_name.strip()
            if not value:
                continue
            title_parts = [value]
            subtitle_parts = [
                part
                for part in (device.product, device.place)
                if isinstance(part, str) and part
            ]
            if subtitle_parts:
                title_parts.append(f"({' / '.join(subtitle_parts)})")
            choices.append({"title": " ".join(title_parts), "value": value})
        return choices

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
        if (
            message.source.value != "webex"
            or message.room_id is None
            or self.device_lister is None
        ):
            return None

        choices = await self._load_device_choices()

        if not choices:
            return None

        card: dict[str, object] = {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.0",
                "body": [
                    {
                        "type": "TextBlock",
                        "weight": "Bolder",
                        "text": "Select a device",
                    },
                    {"type": "TextBlock", "wrap": True, "text": fallback_text},
                    {
                        "type": "Input.ChoiceSet",
                        "id": "selectedValue",
                        "style": "compact",
                        "isRequired": True,
                        "placeholder": "장치를 선택하세요",
                        "choices": choices,
                    },
                ],
                "actions": [
                    {
                        "type": "Action.Submit",
                        "title": "Continue",
                        "data": {
                            "kind": "entity_selection",
                            "pendingActionId": pending_action.pending_action_id,
                            "fieldName": "target_device",
                            "selectionDecision": "submit",
                        },
                    },
                    {
                        "type": "Action.Submit",
                        "title": "Cancel",
                        "data": {
                            "kind": "entity_selection",
                            "pendingActionId": pending_action.pending_action_id,
                            "fieldName": "target_device",
                            "selectionDecision": "cancel",
                        },
                    },
                ],
            },
        }
        return OutboundReply(
            text=fallback_text,
            markdown=f"**Select a device**\n\n{fallback_text}",
            room_id=message.room_id,
            attachments=[card],
        )

    def _display_mode_choices(self) -> list[tuple[str, str, str]]:
        return [
            (
                "왼쪽영상, 오른쪽영상",
                DisplayMode.LEFT_VIDEO_RIGHT_VIDEO.value,
                "Connector[1]: First, Connector[2]: Second",
            ),
            (
                "왼쪽영상, 오른쪽프리젠테이션",
                DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION.value,
                "Connector[1]: First, Connector[2]: PresentationOnly",
            ),
            (
                "왼쪽프리젠테이션, 오른쪽영상",
                DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO.value,
                "Connector[1]: PresentationOnly, Connector[2]: First",
            ),
            (
                "양쪽모두 프리젠테이션",
                DisplayMode.BOTH_PRESENTATION.value,
                "Connector[1]: PresentationOnly, Connector[2]: PresentationOnly",
            ),
        ]

    def _build_display_mode_card_pending_action(
        self, message: InboundUserMessage
    ) -> PendingActionProposal | None:
        normalized = message.text.strip().lower()
        compact = re.sub(r"\s+", "", normalized)
        if not (
            "디스플레이모드" in compact
            or "displaymode" in compact
            or "display mode" in normalized
        ):
            return None
        if not any(keyword in compact for keyword in ("설정", "변경", "선택", "set")):
            return None
        target_device = self._extract_display_mode_target_device(message)
        return PendingActionProposal(
            intent=Intent.SET_DISPLAY_MODE,
            summary="Select a two-monitor display role mode.",
            target_device=target_device,
        )

    def _extract_display_mode_target_device(self, message: InboundUserMessage) -> str | None:
        trailing_target = self._extract_trailing_target_device(message.text)
        if trailing_target:
            return trailing_target
        lowered = message.text.lower()
        markers = ["디스플레이모드", "디스플레이 모드", "display mode", "displaymode"]
        marker_positions = [
            lowered.find(marker) for marker in markers if lowered.find(marker) > 0
        ]
        if marker_positions:
            candidate = message.text[: min(marker_positions)].strip(" ,:：-–—")
            if candidate:
                return candidate
        return message.target_device

    def _build_display_mode_selection_reply(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        actions = [
            {
                "type": "Action.Submit",
                "title": title,
                "data": {
                    "kind": "entity_selection",
                    "pendingActionId": pending_action.pending_action_id,
                    "fieldName": "display_mode",
                    "selectedValue": value,
                    "selectionDecision": "submit",
                },
            }
            for title, value, _description in self._display_mode_choices()
        ]
        actions.append(
            {
                "type": "Action.Submit",
                "title": "Cancel",
                "data": {
                    "kind": "entity_selection",
                    "pendingActionId": pending_action.pending_action_id,
                    "fieldName": "display_mode",
                    "selectionDecision": "cancel",
                },
            }
        )
        target_text = (
            f"대상 장치: {pending_action.target_device}"
            if pending_action.target_device
            else "대상 장치는 선택 후 물어볼게요."
        )
        card: dict[str, object] = {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.0",
                "body": [
                    {
                        "type": "TextBlock",
                        "weight": "Bolder",
                        "text": "디스플레이 모드 선택",
                    },
                    {"type": "TextBlock", "wrap": True, "text": target_text},
                    *[
                        {
                            "type": "TextBlock",
                            "wrap": True,
                            "text": f"{title}: {description}",
                        }
                        for title, _value, description in self._display_mode_choices()
                    ],
                ],
                "actions": actions,
            },
        }
        text = "디스플레이 모드를 선택해주세요."
        return OutboundReply(
            text=text,
            markdown="**디스플레이 모드 선택**\n\n" + target_text,
            room_id=message.room_id,
            attachments=[card],
        )

    def _camera_mode_title(self, mode: str) -> str:
        aliases = {}
        return aliases.get(mode, mode)

    def _build_camera_mode_card_pending_action(
        self, message: InboundUserMessage
    ) -> PendingActionProposal | None:
        normalized = message.text.strip().lower()
        compact = re.sub(r"\s+", "", normalized)
        if not (
            "카메라모드" in compact
            or "cameramode" in compact
            or "camera mode" in normalized
        ):
            return None
        if not any(keyword in compact for keyword in ("변경", "설정", "선택", "set")):
            return None
        if self._extract_explicit_camera_mode(normalized) is not None:
            return None
        target_device = self._extract_camera_mode_target_device(message)
        return PendingActionProposal(
            intent=Intent.SET_CAMERA_MODE,
            summary="Select a supported camera mode.",
            target_device=target_device,
        )

    def _extract_explicit_camera_mode(self, normalized_text: str) -> WritableCameraMode | None:
        compact = re.sub(r"[\s_-]+", "", normalized_text.casefold())
        mode_phrases: tuple[tuple[WritableCameraMode, tuple[str, ...]], ...] = (
            (WritableCameraMode.MANUAL, ("manual", "수동")),
            (WritableCameraMode.DYNAMIC, ("dynamic", "동적")),
            (
                WritableCameraMode.BEST_OVERVIEW,
                ("best overview", "best_overview", "bestoverview", "overview"),
            ),
            (
                WritableCameraMode.CLOSEUP,
                ("closeup", "close up", "speaker closeup", "speaker close up"),
            ),
            (WritableCameraMode.FRAMES, ("frames", "frame")),
            (
                WritableCameraMode.GROUP_AND_SPEAKER,
                (
                    "group and speaker",
                    "group_and_speaker",
                    "groupandspeaker",
                    "group speaker",
                ),
            ),
        )
        for mode, phrases in mode_phrases:
            for phrase in phrases:
                if phrase in normalized_text or re.sub(r"[\s_-]+", "", phrase) in compact:
                    return mode
        return None

    def _extract_camera_mode_target_device(self, message: InboundUserMessage) -> str | None:
        trailing_target = self._extract_trailing_target_device(message.text)
        if trailing_target:
            return trailing_target
        lowered = message.text.lower()
        markers = ["카메라모드", "카메라 모드", "camera mode", "cameramode"]
        marker_positions = [
            lowered.find(marker) for marker in markers if lowered.find(marker) > 0
        ]
        if marker_positions:
            candidate = message.text[: min(marker_positions)].strip(" ,:：-–—")
            if candidate:
                return candidate
        return message.target_device

    async def _build_camera_mode_selection_reply(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
    ) -> OutboundReply:
        supported_modes: tuple[str, ...] = tuple(mode.value for mode in WritableCameraMode)
        if self.camera_mode_lister is not None and pending_action.target_device:
            supported_modes = await self.camera_mode_lister(pending_action.target_device)
        if not supported_modes:
            supported_modes = tuple(mode.value for mode in WritableCameraMode)

        actions = [
            {
                "type": "Action.Submit",
                "title": self._camera_mode_title(mode),
                "data": {
                    "kind": "entity_selection",
                    "pendingActionId": pending_action.pending_action_id,
                    "fieldName": "camera_mode",
                    "selectedValue": mode,
                    "selectionDecision": "submit",
                },
            }
            for mode in supported_modes
        ]
        actions.append(
            {
                "type": "Action.Submit",
                "title": "Cancel",
                "data": {
                    "kind": "entity_selection",
                    "pendingActionId": pending_action.pending_action_id,
                    "fieldName": "camera_mode",
                    "selectionDecision": "cancel",
                },
            }
        )
        target_text = (
            f"대상 장치: {pending_action.target_device}"
            if pending_action.target_device
            else "대상 장치는 선택 후 물어볼게요."
        )
        card: dict[str, object] = {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.0",
                "body": [
                    {
                        "type": "TextBlock",
                        "weight": "Bolder",
                        "text": "카메라 모드 선택",
                    },
                    {"type": "TextBlock", "wrap": True, "text": target_text},
                    {
                        "type": "TextBlock",
                        "wrap": True,
                        "text": "xCommand Cameras SpeakerTrack Set 지원 Behavior",
                    },
                ],
                "actions": actions,
            },
        }
        return OutboundReply(
            text="카메라 모드를 선택해주세요.",
            markdown="**카메라 모드 선택**\n\n" + target_text,
            room_id=message.room_id,
            attachments=[card],
        )

    def _is_reset_message(self, text: str) -> bool:
        return text.strip().lower() in {
            "/reset",
            "/clear-context",
            "reset context",
            "clear context",
        }

    def _next_missing_pending_field(
        self, pending_action: PendingActionProposal
    ) -> str | None:
        if (
            pending_action.action_proposal is not None
            and self._proposal_has_missing_target_device(pending_action.action_proposal)
        ):
            return "target_device"

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
        next_missing_field = self._next_missing_pending_field(pending_action)
        questions = {
            "meeting_identifier": "What Webex meeting ID or address should I join?",
            "address": "What address should I dial?",
            "level": "What volume level should I set (0-100)?",
            "display_mode": "어떤 디스플레이 모드로 설정할까요?",
            "camera_mode": "어떤 카메라 모드로 설정할까요?",
            "target_device": "Which device should I use?",
        }
        if next_missing_field is None:
            return "What should I do next?"
        return questions.get(next_missing_field, "What should I do next?")

    def _build_target_device_follow_up_text(
        self,
        message: InboundUserMessage,
        pending_action: PendingActionProposal,
        fallback_text: str,
    ) -> str:
        if message.source != MessageSource.WEBEX:
            return fallback_text
        if pending_action.intent == Intent.SET_MICROPHONE_MUTE:
            return "어떤 장치를 음소거할까요? 장치 이름을 말씀해주시거나 목록을 확인해주세요."
        if pending_action.intent == Intent.SET_SELFVIEW:
            enabled = self._get_pending_bool_value(pending_action, "enabled")
            action = "켜드릴까요" if enabled is not False else "꺼드릴까요"
            return f"어떤 장치의 Selfview를 {action}? 장치 이름을 말씀해 주세요."
        if pending_action.intent == Intent.SET_VIDEO_MUTE:
            muted = self._get_pending_bool_value(pending_action, "muted")
            action = "꺼드릴까요" if muted is True else "켜드릴까요"
            return f"어떤 장치의 비디오를 {action}? 장치 이름을 말씀해 주세요."
        if pending_action.intent == Intent.SET_SPEAKERTRACK:
            enabled = self._get_pending_bool_value(pending_action, "enabled")
            action = "켜드릴까요" if enabled is not False else "꺼드릴까요"
            return f"어떤 장치의 SpeakerTrack을 {action}? 장치 이름을 말씀해 주세요."
        if pending_action.intent == Intent.SET_STANDBY:
            enabled = self._get_pending_bool_value(pending_action, "enabled")
            action = "켜드릴까요" if enabled is not False else "꺼드릴까요"
            return f"어떤 장치의 스탠바이를 {action}? 장치 이름을 말씀해 주세요."
        if pending_action.intent == Intent.SET_PRESENTATION:
            enabled = self._get_pending_bool_value(pending_action, "enabled")
            action = "시작할까요" if enabled is not False else "중지할까요"
            return f"어떤 장치의 프레젠테이션 공유를 {action}? 장치 이름을 말씀해 주세요."
        if pending_action.intent == Intent.SET_VOLUME:
            return "어떤 장치의 볼륨을 올릴까요?"
        return fallback_text

    def _get_pending_bool_value(
        self, pending_action: PendingActionProposal, field_name: str
    ) -> bool | None:
        if pending_action.action_proposal is None:
            return None
        payload = self._get_action_payload(pending_action.action_proposal)
        value = getattr(payload, field_name, None) if payload is not None else None
        return value if isinstance(value, bool) else None

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
        match = re.search(
            r"(?:webex join|join webex)(?:\s+meeting)?\s+(https?://\S+|[A-Za-z0-9@._:/-]+)",
            text,
            re.IGNORECASE,
        )
        if match is not None:
            return match.group(1).strip().rstrip("?.!")

        candidate = self._strip_trailing_target_clause(text)
        digit_match = re.fullmatch(r"(?:\d[\s-]*){9,14}", candidate.strip())
        if digit_match is not None:
            return re.sub(r"\D+", "", candidate)
        candidate = re.sub(
            r"^(?:meeting(?:\s+id)?\s+)",
            "",
            candidate,
            flags=re.IGNORECASE,
        ).strip()
        if not candidate:
            return None
        if re.fullmatch(r"https?://\S+|[A-Za-z0-9@._:/-]+", candidate) is None:
            return None
        return candidate.rstrip("?.!")

    def _extract_follow_up_dial_address(self, text: str) -> str | None:
        match = re.search(
            r"(?:dial|call|join sip|sip|전화(?:해줘)?|통화(?:해줘)?)\s+(?:to\s+|로\s+|으로\s+)?([A-Za-z0-9@._:+-]+)",
            text,
            re.IGNORECASE,
        )
        if match is not None:
            return match.group(1).strip().rstrip("?.!")

        fallback_match = re.search(r"([A-Za-z0-9._+-]+@[A-Za-z0-9.-]+)", text)
        if fallback_match is not None:
            return fallback_match.group(1).strip().rstrip("?.!")

        candidate = self._strip_trailing_target_clause(text)
        candidate = re.sub(r"^(?:to\s+)", "", candidate, flags=re.IGNORECASE).strip()
        if not candidate:
            return None
        if re.fullmatch(r"[A-Za-z0-9@._:+-]+", candidate) is None:
            return None
        return candidate.rstrip("?.!")

    def _extract_follow_up_volume_level(self, text: str) -> int | None:
        match = re.search(r"(?:set volume|volume)\s+(?:to\s+)?(\d{1,3})", text)
        if match is None:
            match = re.search(r"\b(\d{1,3})\b", text)
        if match is None:
            return None
        level = int(match.group(1))
        return level if 0 <= level <= 100 else None

    def _extract_trailing_target_device(self, text: str) -> str | None:
        match = re.search(
            r"\b(?:on|for|of)\s+([A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)\s*[?.!]*$",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return None
        return match.group(1).strip().rstrip("?.!")

    def _strip_trailing_target_clause(self, text: str) -> str:
        match = re.search(
            r"^(.*?)(?:\s+\b(?:on|for|of)\s+[A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)\s*[?.!]*$",
            text,
            re.IGNORECASE,
        )
        if match is None:
            return text.strip().rstrip("?.!")
        return match.group(1).strip().rstrip("?.!")

    def _extract_direct_target_device_response(self, text: str) -> str | None:
        candidate = re.sub(r"^(?:on|for|of)\s+", "", text.strip(), flags=re.IGNORECASE)
        normalized = candidate.rstrip("?.!")
        return normalized or None

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
        try:
            rendered = await self.provider.render_execution_reply(
                execution_result,
                policy_reason,
                canonical_text,
            )
        except Exception:
            return None
        if not isinstance(rendered, str):
            return None
        normalized = rendered.strip()
        if not normalized or normalized == canonical_text:
            return None
        return normalized

    def _format_execution_result(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
    ) -> str:
        if (
            execution_result.status == ExecutionStatus.SUCCESS
            and execution_result.device_status is not None
        ):
            status = execution_result.device_status
            metadata_parts = [f"online={status.online}"]
            for label, value in (
                ("display_name", status.display_name),
                ("product", status.product),
                ("product_platform", status.product_platform),
                ("place", status.place),
                ("software_version", status.software_version),
                ("software_display_name", status.software_display_name),
                ("serial_number", status.serial_number),
                ("connection_status", status.connection_status),
                ("system_state", status.system_state),
                ("active_interface", status.active_interface),
                ("ipv4_address", status.ipv4_address),
                ("wifi_status", status.wifi_status),
                ("volume", status.volume),
                ("volume_muted", status.volume_muted),
                ("microphones_muted", status.microphones_muted),
                ("call_active", status.call_active),
                ("active_call_count", status.active_call_count),
                ("presentation_active", status.presentation_active),
                ("presentation_mode", status.presentation_mode),
                ("selfview_mode", status.selfview_mode),
                ("selfview_fullscreen", status.selfview_fullscreen),
                ("speakertrack_state", status.speakertrack_state),
                ("presentertrack_status", status.presentertrack_status),
                ("standby_state", status.standby_state),
            ):
                if value is not None:
                    metadata_parts.append(f"{label}={value}")
            return (
                f"{execution_result.message} "
                f"{', '.join(metadata_parts)}. Policy: {policy_reason}"
            )

        if (
            execution_result.status == ExecutionStatus.SUCCESS
            and execution_result.camera_mode_status is not None
        ):
            camera_mode_status = execution_result.camera_mode_status
            camera_metadata_parts: list[str] = []
            if camera_mode_status.display_name is not None:
                camera_metadata_parts.append(
                    f"display_name={camera_mode_status.display_name}"
                )
            if camera_mode_status.device_id is not None:
                camera_metadata_parts.append(
                    f"device_id={camera_mode_status.device_id}"
                )
            camera_metadata_parts.append(
                f"current_mode={camera_mode_status.current_mode}"
            )
            camera_metadata_parts.append(
                f"effective_mode={camera_mode_status.effective_mode}"
            )
            camera_metadata_parts.append(
                "available_modes=" + ",".join(camera_mode_status.available_modes)
                if camera_mode_status.available_modes
                else "available_modes="
            )
            if camera_mode_status.detail is not None:
                camera_metadata_parts.append(f"detail={camera_mode_status.detail}")
            return (
                f"{execution_result.message} "
                f"{', '.join(camera_metadata_parts)}. Policy: {policy_reason}"
            )

        if (
            execution_result.status == ExecutionStatus.SUCCESS
            and execution_result.room_booking_status is not None
        ):
            booking_status = execution_result.room_booking_status
            lines: list[str] = [execution_result.message]
            current_parts: list[str] = []
            if booking_status.is_booked_now is True:
                current_parts.append("Booked now")
            elif booking_status.is_booked_now is False:
                current_parts.append("Available now")
            if booking_status.current_booking_id is not None:
                current_parts.append(
                    f"current booking ID {booking_status.current_booking_id}"
                )
            if current_parts:
                lines.append("Current: " + ", ".join(current_parts) + ".")

            next_parts: list[str] = []
            if booking_status.next_meeting_title is not None:
                next_parts.append(booking_status.next_meeting_title)
            if booking_status.next_meeting_start_time is not None:
                next_parts.append(f"starts {booking_status.next_meeting_start_time}")
            if booking_status.next_meeting_end_time is not None:
                next_parts.append(f"ends {booking_status.next_meeting_end_time}")
            if booking_status.next_booking_id is not None:
                next_parts.append(f"booking ID {booking_status.next_booking_id}")
            if next_parts:
                lines.append("Next: " + ", ".join(next_parts) + ".")

            obtp_parts: list[str] = []
            if booking_status.obtp_available is True:
                obtp_parts.append("OBTP available")
            elif booking_status.obtp_available is False:
                obtp_parts.append("OBTP not available")
            if booking_status.obtp_join_method is not None:
                obtp_parts.append(f"join method {booking_status.obtp_join_method}")
            if obtp_parts:
                lines.append("Join: " + ", ".join(obtp_parts) + ".")

            if booking_status.availability_status is not None:
                availability_line = (
                    f"Availability: {booking_status.availability_status}"
                )
                if booking_status.availability_timestamp is not None:
                    availability_line += f" at {booking_status.availability_timestamp}"
                lines.append(availability_line + ".")

            return " ".join(lines) + f" Policy: {policy_reason}"

        if (
            execution_result.status == ExecutionStatus.SUCCESS
            and execution_result.environment_info_status is not None
        ):
            environment_info = execution_result.environment_info_status
            metadata_parts: list[str] = []
            if environment_info.display_name is not None:
                metadata_parts.append(f"display_name={environment_info.display_name}")
            if environment_info.device_id is not None:
                metadata_parts.append(f"device_id={environment_info.device_id}")
            metadata_parts.append(
                f"temperature_celsius={environment_info.temperature_celsius}"
            )
            metadata_parts.append(
                f"relative_humidity_percent={environment_info.relative_humidity_percent}"
            )
            metadata_parts.append(
                f"ambient_noise_db={environment_info.ambient_noise_db}"
            )
            metadata_parts.append(f"people_count={environment_info.people_count}")
            metadata_parts.append(
                f"air_quality_index={environment_info.air_quality_index}"
            )
            if environment_info.detail is not None:
                metadata_parts.append(f"detail={environment_info.detail}")
            return (
                f"{execution_result.message} "
                f"{', '.join(metadata_parts)}. Policy: {policy_reason}"
            )

        if (
            execution_result.status == ExecutionStatus.SUCCESS
            and execution_result.intent == Intent.LIST_DEVICES
            and execution_result.devices is not None
        ):
            return self._format_device_list(execution_result.devices, policy_reason)

        if execution_result.status == ExecutionStatus.BLOCKED:
            return f"Blocked: {execution_result.message}"

        if execution_result.status == ExecutionStatus.UNSUPPORTED:
            return f"Not enabled yet: {execution_result.message}"

        if execution_result.status == ExecutionStatus.SUCCESS:
            return f"{execution_result.message} Policy: {policy_reason}"

        if (
            execution_result.status == ExecutionStatus.ERROR
            and execution_result.failed_target_device is not None
            and execution_result.resolution_error is not None
        ):
            return self._format_device_resolution_failure(
                execution_result, policy_reason
            )

        return f"Execution failed: {execution_result.message}"

    def _format_device_list(
        self, devices: list[OrganizationDeviceRecord], policy_reason: str
    ) -> str:
        if not devices:
            return f"**디바이스 목록**\n조건에 맞는 디바이스가 없습니다. Policy: {policy_reason}"

        lines = [f"**디바이스 목록** ({len(devices)}대)"]
        for device in devices[:10]:
            status = (
                "online"
                if device.online
                else "offline"
                if device.online is False
                else "unknown"
            )
            product = f" ({device.product})" if device.product else ""
            place = f" [{device.place}]" if device.place else ""
            connection = (
                f", connection={device.connection_status}"
                if device.connection_status is not None
                else ""
            )
            lines.append(
                f"- {device.display_name}{product} - {status}{place}{connection}"
            )
        return "\n".join(lines) + f"\n\nPolicy: {policy_reason}"

    def _build_approval_reply(
        self,
        request_id: str,
        title: str,
        prompt: str,
        room_id: str | None,
    ) -> OutboundReply:
        card: dict[str, object] = {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.0",
                "body": [
                    {"type": "TextBlock", "weight": "Bolder", "text": title},
                    {"type": "TextBlock", "wrap": True, "text": prompt},
                ],
                "actions": [
                    {
                        "type": "Action.Submit",
                        "title": "Approve",
                        "data": {"requestId": request_id, "decision": "approve"},
                    },
                    {
                        "type": "Action.Submit",
                        "title": "Reject",
                        "data": {"requestId": request_id, "decision": "reject"},
                    },
                ],
            },
        }
        return OutboundReply(
            text=f"Approval required: {title}",
            markdown=f"**Approval required**\n\n{prompt}",
            room_id=room_id,
            attachments=[card],
        )

    def _format_device_resolution_failure(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
    ) -> str:
        target_device = execution_result.failed_target_device or "requested device"
        if execution_result.resolution_error == "ambiguous":
            title = f"'{target_device}'에 해당하는 디바이스가 여러 대입니다."
        else:
            title = f"'{target_device}'와 일치하는 디바이스를 찾지 못했습니다."

        candidate_devices = execution_result.candidate_devices or []
        if not candidate_devices:
            return f"{title} Policy: {policy_reason}"

        lines = [title, "다음 디바이스 중 하나로 다시 요청해 주세요:"]
        for device in candidate_devices[:10]:
            status = (
                "online"
                if device.online
                else "offline"
                if device.online is False
                else "unknown"
            )
            product = f" ({device.product})" if device.product else ""
            lines.append(f"- {device.display_name}{product} - {status}")
        return "\n".join(lines) + f"\n\nPolicy: {policy_reason}"
