"""Card / selection reply builders extracted from Orchestrator.

These functions intentionally accept the Orchestrator instance as their first
argument so the Orchestrator can keep thin wrapper methods and behavior remains
unchanged. Class attributes such as ``_PRODUCT_CAPABILITIES``,
``_CAPABILITY_ORDER`` and ``_INTENT_CAPABILITIES`` are accessed via the passed
orchestrator instance.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from shared.contracts import (
    DisplayMode,
    InboundUserMessage,
    Intent,
    MessageSource,
    MicrophoneProcessingMode,
    OrganizationDeviceRecord,
    OutboundReply,
    PendingActionProposal,
    WritableCameraMode,
)

if TYPE_CHECKING:  # pragma: no cover
    from assistant_app.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Setting option (boolean / enum) cards
# ---------------------------------------------------------------------------


def setting_option_specs() -> dict[Intent, dict[str, object]]:
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


def build_setting_option_card_pending_action(
    orchestrator: Orchestrator, message: InboundUserMessage
) -> PendingActionProposal | None:
    normalized = message.text.strip().casefold()
    compact = re.sub(r"\s+", "", normalized)
    for intent, spec in setting_option_specs().items():
        keywords = tuple(str(keyword).casefold() for keyword in spec["keywords"])  # type: ignore[index]
        verbs = tuple(str(verb).casefold() for verb in spec["verbs"])  # type: ignore[index]
        if not any(keyword in normalized or re.sub(r"\s+", "", keyword) in compact for keyword in keywords):
            continue
        if not any(verb in normalized or re.sub(r"\s+", "", verb) in compact for verb in verbs):
            continue
        return PendingActionProposal(
            intent=intent,
            summary=str(spec["title"]),
            target_device=orchestrator._extract_trailing_target_device(message.text) or message.target_device,
        )
    return None


async def build_setting_option_selection_reply(
    orchestrator: Orchestrator,
    message: InboundUserMessage,
    pending_action: PendingActionProposal,
) -> OutboundReply:
    spec = setting_option_specs()[pending_action.intent]
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
        device_choices = await load_device_choices_for_intent(orchestrator, pending_action.intent)
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


# ---------------------------------------------------------------------------
# Device capability helpers
# ---------------------------------------------------------------------------


def normalize_capability_product(product: str | None) -> str:
    if not isinstance(product, str):
        return ""
    normalized = product.casefold().replace("cisco ", "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def device_capabilities(
    orchestrator: Orchestrator, device: OrganizationDeviceRecord
) -> set[str]:
    candidates = [device.product, device.display_name]
    for candidate in candidates:
        normalized = normalize_capability_product(candidate)
        if not normalized:
            continue
        if normalized in orchestrator._PRODUCT_CAPABILITIES:
            return set(orchestrator._PRODUCT_CAPABILITIES[normalized])
        for product_name, capabilities in orchestrator._PRODUCT_CAPABILITIES.items():
            if product_name and product_name in normalized:
                return set(capabilities)
    return {capability for capability, _label in orchestrator._CAPABILITY_ORDER}


def capability_labels(
    orchestrator: Orchestrator, capabilities: set[str]
) -> list[str]:
    return [
        label
        for capability, label in orchestrator._CAPABILITY_ORDER
        if capability in capabilities
    ]


def device_supports_intent(
    orchestrator: Orchestrator,
    device: OrganizationDeviceRecord,
    intent: Intent | None,
) -> bool:
    if intent is None:
        return True
    required_capabilities = orchestrator._INTENT_CAPABILITIES.get(intent)
    if not required_capabilities:
        return True
    return bool(device_capabilities(orchestrator, device) & required_capabilities)


async def load_device_choices(orchestrator: Orchestrator) -> list[dict[str, str]]:
    return await load_device_choices_for_intent(orchestrator, None)


async def load_device_choices_for_intent(
    orchestrator: Orchestrator, intent: Intent | None
) -> list[dict[str, str]]:
    if orchestrator.device_lister is None:
        return []
    try:
        devices = await orchestrator.device_lister()
    except Exception:
        return []
    choices: list[dict[str, str]] = []
    for device in devices[:10]:
        if not device_supports_intent(orchestrator, device, intent):
            continue
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
        capabilities = capability_labels(
            orchestrator, device_capabilities(orchestrator, device)
        )
        if capabilities:
            title_parts.append(f"- {', '.join(capabilities)}")
        choices.append({"title": " ".join(title_parts), "value": value})
    return choices


# ---------------------------------------------------------------------------
# Target device selection card
# ---------------------------------------------------------------------------


async def build_target_device_selection_reply(
    orchestrator: Orchestrator,
    message: InboundUserMessage,
    pending_action: PendingActionProposal,
    fallback_text: str,
) -> OutboundReply | None:
    if (
        message.source.value != "webex"
        or message.room_id is None
        or orchestrator.device_lister is None
    ):
        return None

    choices = await load_device_choices_for_intent(orchestrator, pending_action.intent)

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


# ---------------------------------------------------------------------------
# Display mode
# ---------------------------------------------------------------------------


def display_mode_choices() -> list[tuple[str, str, str]]:
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


def build_display_mode_card_pending_action(
    orchestrator: Orchestrator, message: InboundUserMessage
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
    target_device = orchestrator._extract_display_mode_target_device(message)
    return PendingActionProposal(
        intent=Intent.SET_DISPLAY_MODE,
        summary="Select a two-monitor display role mode.",
        target_device=target_device,
    )


def build_display_mode_selection_reply(
    orchestrator: Orchestrator,
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
        for title, value, _description in display_mode_choices()
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
                    for title, _value, description in display_mode_choices()
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


# ---------------------------------------------------------------------------
# Camera mode
# ---------------------------------------------------------------------------


def camera_mode_title(mode: str) -> str:
    aliases: dict[str, str] = {}
    return aliases.get(mode, mode)


def build_camera_mode_card_pending_action(
    orchestrator: Orchestrator, message: InboundUserMessage
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
    if orchestrator._extract_explicit_camera_mode(normalized) is not None:
        return None
    target_device = orchestrator._extract_camera_mode_target_device(message)
    return PendingActionProposal(
        intent=Intent.SET_CAMERA_MODE,
        summary="Select a supported camera mode.",
        target_device=target_device,
    )


async def build_camera_mode_selection_reply(
    orchestrator: Orchestrator,
    message: InboundUserMessage,
    pending_action: PendingActionProposal,
) -> OutboundReply:
    supported_modes: tuple[str, ...] = tuple(mode.value for mode in WritableCameraMode)
    if orchestrator.camera_mode_lister is not None and pending_action.target_device:
        supported_modes = await orchestrator.camera_mode_lister(pending_action.target_device)
    if not supported_modes:
        supported_modes = tuple(mode.value for mode in WritableCameraMode)

    actions = [
        {
            "type": "Action.Submit",
            "title": camera_mode_title(mode),
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


# ---------------------------------------------------------------------------
# Approval card / follow-up question helpers
# ---------------------------------------------------------------------------


def build_approval_reply(
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


def build_follow_up_question(
    orchestrator: Orchestrator, pending_action: PendingActionProposal
) -> str:
    next_missing_field = orchestrator._next_missing_pending_field(pending_action)
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


def build_target_device_follow_up_text(
    orchestrator: Orchestrator,
    message: InboundUserMessage,
    pending_action: PendingActionProposal,
    fallback_text: str,
) -> str:
    if message.source != MessageSource.WEBEX:
        return fallback_text
    if pending_action.intent == Intent.SET_MICROPHONE_MUTE:
        return "어떤 장치를 음소거할까요? 장치 이름을 말씀해주시거나 목록을 확인해주세요."
    if pending_action.intent == Intent.SET_SELFVIEW:
        enabled = orchestrator._get_pending_bool_value(pending_action, "enabled")
        action = "켜드릴까요" if enabled is not False else "꺼드릴까요"
        return f"어떤 장치의 Selfview를 {action}? 장치 이름을 말씀해 주세요."
    if pending_action.intent == Intent.SET_VIDEO_MUTE:
        muted = orchestrator._get_pending_bool_value(pending_action, "muted")
        action = "꺼드릴까요" if muted is True else "켜드릴까요"
        return f"어떤 장치의 비디오를 {action}? 장치 이름을 말씀해 주세요."
    if pending_action.intent == Intent.SET_SPEAKERTRACK:
        enabled = orchestrator._get_pending_bool_value(pending_action, "enabled")
        action = "켜드릴까요" if enabled is not False else "꺼드릴까요"
        return f"어떤 장치의 SpeakerTrack을 {action}? 장치 이름을 말씀해 주세요."
    if pending_action.intent == Intent.SET_STANDBY:
        enabled = orchestrator._get_pending_bool_value(pending_action, "enabled")
        action = "켜드릴까요" if enabled is not False else "꺼드릴까요"
        return f"어떤 장치의 스탠바이를 {action}? 장치 이름을 말씀해 주세요."
    if pending_action.intent == Intent.SET_PRESENTATION:
        enabled = orchestrator._get_pending_bool_value(pending_action, "enabled")
        action = "시작할까요" if enabled is not False else "중지할까요"
        return f"어떤 장치의 프레젠테이션 공유를 {action}? 장치 이름을 말씀해 주세요."
    if pending_action.intent == Intent.SET_VOLUME:
        return "어떤 장치의 볼륨을 올릴까요?"
    return fallback_text
