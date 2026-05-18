"""Pending action state machine and proposal mutation helpers.

Extracted from ``assistant_app/orchestrator.py`` as part of the Phase 2.3
refactor. Each function accepts the orchestrator instance as its first
argument so behavior matches the original methods exactly. The Orchestrator
class keeps thin wrapper methods that delegate here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import (
    ActionProposal,
    DialParams,
    DisplayMode,
    InboundUserMessage,
    Intent,
    MessageSource,
    MicrophoneProcessingMode,
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

if TYPE_CHECKING:  # pragma: no cover
    from assistant_app.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Session reset
# ---------------------------------------------------------------------------


def reset_session(
    orchestrator: Orchestrator,
    message: InboundUserMessage,
    reply_text: str = "I cleared the session context. Ask for a device status whenever you're ready.",
) -> OutboundReply:
    orchestrator.memory_store.reset(message.session_id, message.user_id)
    _ = orchestrator.memory_store.append_assistant_turn(
        message.session_id, reply_text, Intent.RESET_CONTEXT
    )
    return OutboundReply(text=reply_text, room_id=message.room_id)


# ---------------------------------------------------------------------------
# Pending follow-up entry points
# ---------------------------------------------------------------------------


async def handle_pending_follow_up(
    orchestrator: Orchestrator,
    message: InboundUserMessage,
    pending_action: PendingActionProposal,
) -> OutboundReply:
    updated_pending_action = collect_pending_follow_up(orchestrator, pending_action, message.text)
    next_missing_field = next_missing_pending_field(orchestrator, updated_pending_action)
    if next_missing_field is not None:
        _ = orchestrator.memory_store.set_pending_action(
            message.session_id,
            message.user_id,
            updated_pending_action,
        )
        reply = await build_pending_reply(orchestrator, message, updated_pending_action)
        _ = orchestrator.memory_store.append_assistant_turn(
            message.session_id,
            reply.text,
            updated_pending_action.intent,
        )
        return reply

    _ = orchestrator.memory_store.clear_pending_action(message.session_id, message.user_id)
    proposal = build_action_proposal_from_pending(orchestrator, updated_pending_action)
    if proposal is None:
        reply_text = "I couldn't determine the next action."
        _ = orchestrator.memory_store.append_assistant_turn(message.session_id, reply_text)
        return OutboundReply(text=reply_text, room_id=message.room_id)
    return await orchestrator._execute_proposal(message, proposal)


async def resume_pending_action_selection(
    orchestrator: Orchestrator,
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
    pending_lookup = orchestrator.memory_store.get_pending_action_by_id(pending_action_id)
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
        _ = orchestrator.memory_store.clear_pending_action(session_id, pending_user_id)
        _ = orchestrator.memory_store.append_assistant_turn(
            session_id,
            reply.text,
            pending_action.intent,
        )
        return reply, True

    if cancel:
        _ = orchestrator.memory_store.clear_pending_action(session_id, pending_user_id)
        reply = OutboundReply(
            text="Okay, I cancelled that request.",
            room_id=room_id,
        )
        _ = orchestrator.memory_store.append_assistant_turn(
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
        and (not isinstance(selected_value, str) or not selected_value.strip())
    ):
        selected_value = pending_action.target_device

    if not isinstance(selected_value, str) or not selected_value.strip():
        fallback_text = orchestrator._build_follow_up_question(pending_action)
        if field_name == "setting_value":
            reply = await orchestrator._build_setting_option_selection_reply(
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
        _ = orchestrator.memory_store.append_assistant_turn(
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
                proposal_setting = get_proposal_setting_field_and_value(orchestrator, proposal)
                if proposal_setting is not None:
                    setting_field_name, setting_value = proposal_setting
                    updated_pending_action.action_proposal = None
        if not apply_pending_setting_selection(
            orchestrator,
            updated_pending_action,
            setting_field_name,
            setting_value,
        ):
            reply = OutboundReply(
                text="That setting selection is no longer valid.",
                room_id=room_id,
            )
            _ = orchestrator.memory_store.append_assistant_turn(
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
            _ = orchestrator.memory_store.append_assistant_turn(
                session_id,
                reply.text,
                pending_action.intent,
            )
            return reply, False
    elif field_name == "camera_mode":
        try:
            updated_pending_action.camera_mode = WritableCameraMode(selected_value.strip())
        except ValueError:
            reply = OutboundReply(
                text="That camera mode selection is no longer valid.",
                room_id=room_id,
            )
            _ = orchestrator.memory_store.append_assistant_turn(
                session_id,
                reply.text,
                pending_action.intent,
            )
            return reply, False
    else:
        updated_pending_action.target_device = selected_value.strip()
        if updated_pending_action.action_proposal is not None:
            updated_pending_action.action_proposal = with_target_device(
                updated_pending_action.action_proposal,
                updated_pending_action.target_device,
            )
        if intent_needs_setting_option_selection(orchestrator, updated_pending_action.intent):
            # Only clear the setting value when none was extracted yet — otherwise
            # the user's original intent ("셀프뷰 켜줘") already pinned enabled=True
            # and wiping it would force a redundant ON/OFF follow-up card.
            existing_proposal = updated_pending_action.action_proposal
            already_has_value = (
                existing_proposal is not None
                and get_proposal_setting_field_and_value(orchestrator, existing_proposal)
                is not None
            )
            if not already_has_value:
                _ = clear_proposal_target_setting_value(orchestrator, updated_pending_action)

    synthetic_message = InboundUserMessage(
        session_id=session_id,
        user_id=user_id,
        text=selected_value.strip(),
        source=MessageSource.WEBEX,
        room_id=room_id,
        person_email=person_email,
    )

    next_missing_field = next_missing_pending_field(orchestrator, updated_pending_action)
    if next_missing_field is not None:
        _ = orchestrator.memory_store.set_pending_action(
            session_id,
            pending_user_id,
            updated_pending_action,
        )
        reply = await build_pending_reply(
            orchestrator,
            synthetic_message,
            updated_pending_action,
        )
        _ = orchestrator.memory_store.append_assistant_turn(
            session_id,
            reply.text,
            updated_pending_action.intent,
        )
        return reply, True

    _ = orchestrator.memory_store.clear_pending_action(session_id, pending_user_id)
    proposal = build_action_proposal_from_pending(orchestrator, updated_pending_action)
    if proposal is None:
        reply = OutboundReply(
            text="I couldn't determine the next action.",
            room_id=room_id,
        )
        _ = orchestrator.memory_store.append_assistant_turn(session_id, reply.text)
        return reply, True

    return await orchestrator._execute_proposal(synthetic_message, proposal), True


async def build_pending_reply(
    orchestrator: Orchestrator,
    message: InboundUserMessage,
    pending_action: PendingActionProposal,
) -> OutboundReply:
    next_missing_field = next_missing_pending_field(orchestrator, pending_action)
    fallback_text = orchestrator._build_follow_up_question(pending_action)
    if next_missing_field == "setting_value":
        return await orchestrator._build_setting_option_selection_reply(
            message,
            pending_action,
        )

    if message.source == MessageSource.WEBEX and pending_action_needs_target_device(
        orchestrator, pending_action
    ):
        fallback_text = orchestrator._build_target_device_follow_up_text(
            message,
            pending_action,
            fallback_text,
        )
        card_reply = await orchestrator._build_target_device_selection_reply(
            message,
            pending_action,
            fallback_text,
        )
        if card_reply is not None:
            return card_reply

    if next_missing_field != "target_device":
        return OutboundReply(text=fallback_text, room_id=message.room_id)
    return OutboundReply(text=fallback_text, room_id=message.room_id)


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------


def next_missing_pending_field(
    orchestrator: Orchestrator, pending_action: PendingActionProposal
) -> str | None:
    if pending_action.action_proposal is not None:
        if proposal_has_missing_target_device(orchestrator, pending_action.action_proposal):
            return "target_device"
        if (
            intent_needs_setting_option_selection(orchestrator, pending_action.intent)
            and get_proposal_setting_field_and_value(orchestrator, pending_action.action_proposal)
            is None
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


def collect_pending_follow_up(
    orchestrator: Orchestrator,
    pending_action: PendingActionProposal,
    text: str,
) -> PendingActionProposal:
    updated_pending_action = pending_action.model_copy(deep=True)
    trailing_target_device = orchestrator._extract_trailing_target_device(text)

    if updated_pending_action.action_proposal is not None and proposal_has_missing_target_device(
        orchestrator, updated_pending_action.action_proposal
    ):
        target_device = resolve_pending_target_device_response(
            orchestrator,
            updated_pending_action.intent,
            text,
            trailing_target_device,
        )
        if target_device is not None:
            updated_pending_action.target_device = target_device
            updated_pending_action.action_proposal = with_target_device(
                updated_pending_action.action_proposal,
                target_device,
            )
        return updated_pending_action

    if updated_pending_action.intent == Intent.WEBEX_JOIN:
        meeting_identifier_was_missing = updated_pending_action.meeting_identifier is None
        if updated_pending_action.meeting_identifier is None:
            updated_pending_action.meeting_identifier = (
                orchestrator._extract_follow_up_webex_meeting_identifier(text)
            )
        if updated_pending_action.target_device is None:
            if trailing_target_device is not None:
                updated_pending_action.target_device = trailing_target_device
            elif not meeting_identifier_was_missing:
                updated_pending_action.target_device = resolve_pending_target_device_response(
                    orchestrator,
                    updated_pending_action.intent,
                    text,
                    trailing_target_device,
                )
        return updated_pending_action

    if updated_pending_action.intent == Intent.DIAL:
        address_was_missing = updated_pending_action.address is None
        if updated_pending_action.address is None:
            updated_pending_action.address = orchestrator._extract_follow_up_dial_address(text)
        if updated_pending_action.target_device is None:
            if trailing_target_device is not None:
                updated_pending_action.target_device = trailing_target_device
            elif not address_was_missing:
                updated_pending_action.target_device = resolve_pending_target_device_response(
                    orchestrator,
                    updated_pending_action.intent,
                    text,
                    trailing_target_device,
                )
        return updated_pending_action

    if updated_pending_action.intent == Intent.SET_VOLUME:
        level_was_missing = updated_pending_action.level is None
        if updated_pending_action.level is None:
            updated_pending_action.level = orchestrator._extract_follow_up_volume_level(text)
        if updated_pending_action.target_device is None:
            if trailing_target_device is not None:
                updated_pending_action.target_device = trailing_target_device
            elif not level_was_missing:
                updated_pending_action.target_device = resolve_pending_target_device_response(
                    orchestrator,
                    updated_pending_action.intent,
                    text,
                    trailing_target_device,
                )
        return updated_pending_action

    return updated_pending_action


def pending_action_needs_target_device(
    orchestrator: Orchestrator, pending_action: PendingActionProposal
) -> bool:
    if pending_action.action_proposal is not None:
        return proposal_has_missing_target_device(orchestrator, pending_action.action_proposal)
    return pending_action.target_device is None and intent_requires_target_device(
        pending_action.intent
    )


def get_pending_bool_value(
    orchestrator: Orchestrator,
    pending_action: PendingActionProposal,
    field_name: str,
) -> bool | None:
    if pending_action.action_proposal is None:
        return None
    payload = get_action_payload(pending_action.action_proposal)
    value = getattr(payload, field_name, None) if payload is not None else None
    return value if isinstance(value, bool) else None


def intent_needs_setting_option_selection(orchestrator: Orchestrator, intent: Intent) -> bool:
    return intent in orchestrator._setting_option_specs()


def resolve_pending_target_device_response(
    orchestrator: Orchestrator,
    intent: Intent,
    text: str,
    trailing_target_device: str | None,
) -> str | None:
    if trailing_target_device is not None:
        return trailing_target_device
    if looks_like_pending_intent_follow_up(intent, text):
        return None
    return orchestrator._extract_direct_target_device_response(text)


def looks_like_pending_intent_follow_up(intent: Intent, text: str) -> bool:
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


# ---------------------------------------------------------------------------
# Proposal builders & mutation
# ---------------------------------------------------------------------------


def apply_pending_setting_selection(
    orchestrator: Orchestrator,
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
        if (
            pending_action.intent == Intent.SET_MICROPHONE_MUTE
            and setting_field_name == "muted"
            and bool_value is not None
        ):
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
        if (
            pending_action.intent == Intent.SET_VIDEO_MUTE
            and setting_field_name == "muted"
            and bool_value is not None
        ):
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
        if (
            pending_action.intent == Intent.SET_SELFVIEW
            and setting_field_name == "enabled"
            and bool_value is not None
        ):
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
        if (
            pending_action.intent == Intent.SET_SPEAKERTRACK
            and setting_field_name == "enabled"
            and bool_value is not None
        ):
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
        if (
            pending_action.intent == Intent.SET_STANDBY
            and setting_field_name == "enabled"
            and bool_value is not None
        ):
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
        if (
            pending_action.intent == Intent.SET_PRESENTATION
            and setting_field_name == "enabled"
            and bool_value is not None
        ):
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


def build_action_proposal_from_pending(
    orchestrator: Orchestrator, pending_action: PendingActionProposal
) -> ActionProposal | None:
    if pending_action.action_proposal is not None:
        return (
            pending_action.action_proposal
            if not proposal_has_missing_target_device(orchestrator, pending_action.action_proposal)
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


def build_missing_target_pending_action(
    orchestrator: Orchestrator, proposal: ActionProposal | None
) -> PendingActionProposal | None:
    if proposal is None or not proposal_has_missing_target_device(orchestrator, proposal):
        return None
    return PendingActionProposal(
        intent=proposal.intent,
        summary=proposal.summary,
        confidence=proposal.confidence,
        action_proposal=proposal.model_copy(deep=True),
    )


def proposal_has_missing_target_device(
    orchestrator: Orchestrator, proposal: ActionProposal
) -> bool:
    if not intent_requires_target_device(proposal.intent):
        return False
    payload = get_action_payload(proposal)
    if payload is None:
        return False
    target_device = getattr(payload, "target_device", None)
    return not isinstance(target_device, str) or not target_device.strip()


def get_proposal_setting_field_and_value(
    orchestrator: Orchestrator, proposal: ActionProposal
) -> tuple[str, str] | None:
    payload = get_action_payload(proposal)
    if payload is None:
        return None
    spec = orchestrator._setting_option_specs().get(proposal.intent)
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


def clear_proposal_target_setting_value(
    orchestrator: Orchestrator, pending_action: PendingActionProposal
) -> bool:
    proposal = pending_action.action_proposal
    if proposal is None:
        return False
    payload = get_action_payload(proposal)
    spec = orchestrator._setting_option_specs().get(proposal.intent)
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


# ---------------------------------------------------------------------------
# Action proposal payload accessors (pure functions — no orchestrator needed)
# ---------------------------------------------------------------------------


def get_action_payload(proposal: ActionProposal) -> object | None:
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


def with_target_device(proposal: ActionProposal, target_device: str) -> ActionProposal:
    payload_name = get_action_payload_field(proposal.intent)
    if payload_name == "get_status" and proposal.get_status is not None:
        return proposal.model_copy(
            update={
                "get_status": proposal.get_status.model_copy(
                    update={"target_device": target_device}
                )
            }
        )
    if payload_name == "get_environment_info" and proposal.get_environment_info is not None:
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
                "join_obtp": proposal.join_obtp.model_copy(update={"target_device": target_device})
            }
        )
    if payload_name == "dial" and proposal.dial is not None:
        return proposal.model_copy(
            update={"dial": proposal.dial.model_copy(update={"target_device": target_device})}
        )
    if payload_name == "hang_up" and proposal.hang_up is not None:
        return proposal.model_copy(
            update={"hang_up": proposal.hang_up.model_copy(update={"target_device": target_device})}
        )
    if payload_name == "send_dtmf" and proposal.send_dtmf is not None:
        return proposal.model_copy(
            update={
                "send_dtmf": proposal.send_dtmf.model_copy(update={"target_device": target_device})
            }
        )
    if payload_name == "set_microphone_mute" and proposal.set_microphone_mute is not None:
        return proposal.model_copy(
            update={
                "set_microphone_mute": proposal.set_microphone_mute.model_copy(
                    update={"target_device": target_device}
                )
            }
        )
    if payload_name == "set_microphone_mode" and proposal.set_microphone_mode is not None:
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
    if payload_name == "switch_input_source" and proposal.switch_input_source is not None:
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
    if payload_name == "activate_camera_preset" and proposal.activate_camera_preset is not None:
        return proposal.model_copy(
            update={
                "activate_camera_preset": proposal.activate_camera_preset.model_copy(
                    update={"target_device": target_device}
                )
            }
        )
    if payload_name == "adjust_camera_position" and proposal.adjust_camera_position is not None:
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
            update={"reboot": proposal.reboot.model_copy(update={"target_device": target_device})}
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
