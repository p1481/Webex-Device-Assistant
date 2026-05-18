"""Pure normalizer helpers extracted from ``OllamaProvider``.

These functions handle:
- Action payload shape normalization (flat -> nested intent payload).
- Display mode / camera mode / layout alias resolution.
- Target device disambiguation against fallback rule-based provider.
- Webex meeting identifier sanitation and base64 decoding.

The original methods on :class:`OllamaProvider` remain as thin wrappers that
delegate here so existing call sites and tests keep working.
"""

from __future__ import annotations

from base64 import b64decode
from typing import TYPE_CHECKING

from shared.contracts import (
    DisplayMode,
    InboundUserMessage,
    Intent,
    WritableCameraMode,
)

if TYPE_CHECKING:
    from assistant_app.providers.rule_based import RuleBasedProvider


CAMERA_MODE_LAYOUT_ALIASES: dict[str, WritableCameraMode] = {
    "manual": WritableCameraMode.MANUAL,
    "dynamic": WritableCameraMode.DYNAMIC,
    "best overview": WritableCameraMode.BEST_OVERVIEW,
    "best_overview": WritableCameraMode.BEST_OVERVIEW,
    "bestoverview": WritableCameraMode.BEST_OVERVIEW,
    "overview": WritableCameraMode.BEST_OVERVIEW,
    "closeup": WritableCameraMode.CLOSEUP,
    "close up": WritableCameraMode.CLOSEUP,
    "speaker closeup": WritableCameraMode.CLOSEUP,
    "speaker close up": WritableCameraMode.CLOSEUP,
    "frames": WritableCameraMode.FRAMES,
    "frame": WritableCameraMode.FRAMES,
    "group and speaker": WritableCameraMode.GROUP_AND_SPEAKER,
    "group_and_speaker": WritableCameraMode.GROUP_AND_SPEAKER,
    "groupandspeaker": WritableCameraMode.GROUP_AND_SPEAKER,
    "group speaker": WritableCameraMode.GROUP_AND_SPEAKER,
}


_INTENT_KEY_MAP: dict[str, str | None] = {
    Intent.GET_STATUS.value: "get_status",
    Intent.GET_ENVIRONMENT_INFO.value: "get_environment_info",
    Intent.GET_CAMERA_MODE.value: "get_camera_mode",
    Intent.GET_ROOM_BOOKING.value: "get_room_booking",
    Intent.LIST_DEVICES.value: "list_devices",
    Intent.WEBEX_JOIN.value: "webex_join",
    Intent.JOIN_OBTP.value: "join_obtp",
    Intent.DIAL.value: "dial",
    Intent.HANG_UP.value: "hang_up",
    Intent.SEND_DTMF.value: "send_dtmf",
    Intent.SET_MICROPHONE_MUTE.value: "set_microphone_mute",
    Intent.SET_MICROPHONE_MODE.value: "set_microphone_mode",
    Intent.SET_VOLUME.value: "set_volume",
    Intent.SET_VIDEO_MUTE.value: "set_video_mute",
    Intent.SET_SELFVIEW.value: "set_selfview",
    Intent.SET_CAMERA_MODE.value: "set_camera_mode",
    Intent.SET_LAYOUT.value: "set_layout",
    Intent.SET_PRESENTATION.value: "set_presentation",
    Intent.SWITCH_INPUT_SOURCE.value: "switch_input_source",
    Intent.ASSIGN_MATRIX.value: "assign_matrix",
    Intent.UNASSIGN_MATRIX.value: "unassign_matrix",
    Intent.SWAP_MATRIX.value: "swap_matrix",
    Intent.SET_DISPLAY_MODE.value: "set_display_mode",
    Intent.SET_DISPLAY_ROLE.value: "set_display_role",
    Intent.ACTIVATE_CAMERA_PRESET.value: "activate_camera_preset",
    Intent.ADJUST_CAMERA_POSITION.value: "adjust_camera_position",
    Intent.SET_SPEAKERTRACK.value: "set_speakertrack",
    Intent.SET_STANDBY.value: "set_standby",
    Intent.REBOOT.value: "reboot",
    Intent.FACTORY_RESET.value: "factory_reset",
    Intent.CHAT.value: None,
    Intent.RESET_CONTEXT.value: None,
}


_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "get_status": ("target_device", "include_metrics"),
    "get_environment_info": ("target_device",),
    "get_camera_mode": ("target_device",),
    "get_room_booking": ("target_device",),
    "list_devices": ("limit", "online_only"),
    "webex_join": ("target_device", "meeting_identifier"),
    "join_obtp": ("target_device",),
    "dial": ("target_device", "address"),
    "hang_up": ("target_device", "call_id"),
    "send_dtmf": ("target_device", "tones", "call_id"),
    "set_microphone_mute": ("target_device", "muted"),
    "set_microphone_mode": ("target_device", "mode"),
    "set_volume": ("target_device", "level"),
    "set_video_mute": ("target_device", "muted"),
    "set_selfview": ("target_device", "enabled"),
    "set_camera_mode": ("target_device", "mode"),
    "set_layout": ("target_device", "layout_name"),
    "set_presentation": ("target_device", "enabled"),
    "switch_input_source": ("target_device", "source_id"),
    "assign_matrix": (
        "target_device",
        "output",
        "mode",
        "layout",
        "source_id",
        "remote_main",
    ),
    "unassign_matrix": (
        "target_device",
        "output",
        "source_id",
        "remote_main",
    ),
    "swap_matrix": ("target_device", "output_a", "output_b"),
    "set_display_mode": ("target_device", "mode"),
    "set_display_role": ("target_device", "connector_id", "role"),
    "activate_camera_preset": ("target_device", "preset_id"),
    "adjust_camera_position": (
        "target_device",
        "camera_id",
        "pan",
        "tilt",
        "zoom",
    ),
    "set_speakertrack": ("target_device", "enabled"),
    "set_standby": ("target_device", "enabled"),
    "reboot": ("target_device",),
    "factory_reset": ("target_device", "acknowledged"),
}


_DISPLAY_MODE_ALIASES: dict[str, DisplayMode] = {
    "left-video-right-video": DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
    "left video right video": DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
    "왼쪽영상오른쪽영상": DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
    "dual": DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
    "left-video-right-presentation": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
    "left video right presentation": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
    "왼쪽영상오른쪽프리젠테이션": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
    "왼쪽영상오른쪽프레젠테이션": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
    "dual-presentation-only": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
    "dual presentation only": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
    "dual presentation-only": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
    "dual-presentation only": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
    "dualpresentationonly": DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
    "left-presentation-right-video": DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
    "left presentation right video": DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
    "왼쪽프리젠테이션오른쪽영상": DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
    "왼쪽프레젠테이션오른쪽영상": DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
    "both-presentation": DisplayMode.BOTH_PRESENTATION,
    "both presentation": DisplayMode.BOTH_PRESENTATION,
    "양쪽모두프리젠테이션": DisplayMode.BOTH_PRESENTATION,
    "양쪽모두프레젠테이션": DisplayMode.BOTH_PRESENTATION,
}


_CAMERA_MODE_DIRECT_MAP: dict[str, WritableCameraMode] = {
    "manual": WritableCameraMode.MANUAL,
    "dynamic": WritableCameraMode.DYNAMIC,
    "best overview": WritableCameraMode.BEST_OVERVIEW,
    "bestoverview": WritableCameraMode.BEST_OVERVIEW,
    "closeup": WritableCameraMode.CLOSEUP,
    "close up": WritableCameraMode.CLOSEUP,
    "speaker closeup": WritableCameraMode.CLOSEUP,
    "speaker close up": WritableCameraMode.CLOSEUP,
    "frames": WritableCameraMode.FRAMES,
    "frame": WritableCameraMode.FRAMES,
    "group and speaker": WritableCameraMode.GROUP_AND_SPEAKER,
    "groupandspeaker": WritableCameraMode.GROUP_AND_SPEAKER,
    "group speaker": WritableCameraMode.GROUP_AND_SPEAKER,
}


def normalize_action_payload(
    raw_proposal: dict[str, object],
) -> dict[str, object] | None:
    raw_intent = raw_proposal.get("intent")
    if not isinstance(raw_intent, str):
        return None

    intent_specific_key = _INTENT_KEY_MAP.get(raw_intent)
    if intent_specific_key is None:
        return raw_proposal
    if intent_specific_key in raw_proposal:
        return raw_proposal

    summary = raw_proposal.get("summary")
    confidence = raw_proposal.get("confidence")
    target_device = raw_proposal.get("target_device")

    normalized: dict[str, object] = {
        "intent": raw_intent,
        "summary": summary,
    }
    if confidence is not None:
        normalized["confidence"] = confidence

    nested_payload: dict[str, object] = {}
    if isinstance(target_device, str) and target_device.strip():
        nested_payload["target_device"] = target_device.strip()

    for field_name in _FIELD_MAP.get(intent_specific_key, ()):
        value = raw_proposal.get(field_name)
        if value is not None:
            nested_payload[field_name] = value

    normalized[intent_specific_key] = nested_payload
    return normalized


def normalize_display_mode(raw_mode: str) -> DisplayMode | None:
    normalized = raw_mode.strip().casefold()
    return _DISPLAY_MODE_ALIASES.get(normalized)


def layout_name_as_camera_mode(layout_name: str) -> WritableCameraMode | None:
    normalized = " ".join(layout_name.strip().lower().replace("_", " ").split())
    return CAMERA_MODE_LAYOUT_ALIASES.get(normalized)


def normalize_target_device(
    raw_target_device: object,
    message: InboundUserMessage,
    *,
    fallback_provider: RuleBasedProvider,
    default_target_device: str,
) -> str:
    mentioned_target_device = fallback_provider._extract_mentioned_target_device(
        message.text,
        message.target_device,
    )
    normalized_raw_target_device = (
        raw_target_device.strip() if isinstance(raw_target_device, str) else None
    )

    if isinstance(mentioned_target_device, str) and mentioned_target_device.strip():
        return mentioned_target_device.strip()
    if (
        normalized_raw_target_device is not None
        and normalized_raw_target_device
        and normalized_raw_target_device != default_target_device
    ):
        return normalized_raw_target_device
    if (
        normalized_raw_target_device is not None
        and normalized_raw_target_device
        and not default_target_device
    ):
        return normalized_raw_target_device
    return ""


def normalize_camera_mode(raw_mode: str) -> WritableCameraMode | None:
    normalized = " ".join(raw_mode.strip().casefold().replace("_", " ").split())
    mode = _CAMERA_MODE_DIRECT_MAP.get(normalized)
    if mode is not None:
        return mode
    compact = normalized.replace(" ", "")
    return _CAMERA_MODE_DIRECT_MAP.get(compact)


def normalize_meeting_identifier(raw_meeting_identifier: object) -> str | None:
    if not isinstance(raw_meeting_identifier, str):
        return None
    meeting_identifier = raw_meeting_identifier.strip()
    if not meeting_identifier:
        return None
    return meeting_identifier


def try_decode_webex_identifier(value: str) -> str | None:
    if not value or any(character.isspace() for character in value):
        return None
    padded = value + ("=" * (-len(value) % 4))
    try:
        decoded = b64decode(padded, validate=True).decode("utf-8")
    except Exception:
        return None
    return decoded


def looks_like_internal_meeting_identifier(
    meeting_identifier: str,
    message: InboundUserMessage,
) -> bool:
    normalized_identifier = meeting_identifier.strip()
    lowered_identifier = normalized_identifier.lower()
    if not lowered_identifier:
        return True

    internal_candidates = {
        value.strip()
        for value in (message.session_id, message.room_id)
        if isinstance(value, str) and value.strip()
    }
    if normalized_identifier in internal_candidates:
        return True

    if lowered_identifier.startswith(("ciscospark://", "cizyccosporak://")):
        return True
    if "/room/" in lowered_identifier:
        return True
    if "/people/" in lowered_identifier or "/message/" in lowered_identifier:
        return True
    if "/webhook/" in lowered_identifier or "/attachment_action/" in lowered_identifier:
        return True
    if "/" in normalized_identifier:
        return True

    decoded_candidate = try_decode_webex_identifier(normalized_identifier)
    if decoded_candidate is not None:
        lowered_decoded = decoded_candidate.lower()
        if lowered_decoded.startswith("ciscospark://"):
            return True
        if "/room/" in lowered_decoded:
            return True

    return False
