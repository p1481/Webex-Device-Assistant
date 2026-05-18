"""Pure-function text extractors and detectors used by ``RuleBasedProvider``.

Phase 3.1 extraction from ``rule_based.py``. These helpers are intentionally
free of provider state; the small amount of configuration they need (steps,
constants, regexes) lives at module scope.
"""

from __future__ import annotations

import re
from typing import TypedDict

from shared.contracts import (
    DisplayMode,
    DisplayRole,
    MicrophoneProcessingMode,
    WritableCameraMode,
)


class MatrixAssignMatch(TypedDict):
    output: str
    mode: str
    layout: str
    source_id: str | None
    remote_main: bool | None


class MatrixUnassignMatch(TypedDict):
    output: str
    source_id: str | None
    remote_main: bool | None


class MatrixSwapMatch(TypedDict):
    output_a: str
    output_b: str


class CameraPositionMatch(TypedDict):
    camera_id: str
    pan: int | None
    tilt: int | None
    zoom: int | None


SOURCE_ALIAS_PATTERN: re.Pattern[str] = re.compile(
    r"(?:switch\s+)?(?:input\s+source|source\s+input)\s+(?:to\s+)?([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
PROMINENT_LAYOUT_PHRASES: tuple[str, ...] = (
    "layout prominent",
    "prominent layout",
    "make layout prominent",
    "set layout prominent",
    "set layout to prominent",
    "switch layout to prominent",
)
TOGGLE_ACTION_NAMES: frozenset[str] = frozenset(
    {
        "selfview",
        "self view",
        "speakertrack",
        "speaker track",
        "standby",
        "presentation",
        "share",
        "video",
        "camera",
    }
)
CAMERA_PAN_STEP: int = 1000
CAMERA_TILT_STEP: int = 1000
CAMERA_ZOOM_STEP: int = 700


def is_list_devices_request(lowered_text: str) -> bool:
    if lowered_text.strip().endswith(" drop"):
        return False
    return any(
        phrase in lowered_text
        for phrase in {
            "device list",
            "list devices",
            "show devices",
            "show me devices",
            "디바이스 리스트",
            "장비 리스트",
            "디바이스 목록",
            "장비 목록",
        }
    )


def is_get_camera_mode_request(lowered_text: str) -> bool:
    if not mentions_camera_mode(lowered_text):
        return False
    return any(
        phrase in lowered_text
        for phrase in {
            "camera mode",
            "camera tracking mode",
            "what camera mode",
            "which camera mode",
            "current camera mode",
            "get camera mode",
            "show camera mode",
            "camera framing mode",
        }
    ) and not is_set_camera_mode_request(lowered_text)


def is_get_environment_info_request(lowered_text: str) -> bool:
    environment_keywords = {
        "temperature",
        "humidity",
        "noise",
        "people count",
        "air quality",
        "environment",
        "sensor",
        "ambient",
        "온도",
        "습도",
        "소음",
        "공기질",
        "환경",
        "센서",
    }
    if "status" in lowered_text and not any(
        keyword in lowered_text for keyword in environment_keywords
    ):
        return False
    return any(
        phrase in lowered_text
        for phrase in {
            "get environment info",
            "environment info",
            "environment data",
            "environment sensor",
            "sensor info",
            "room analytics",
            "temperature",
            "humidity",
            "ambient noise",
            "noise level",
            "people count",
            "air quality",
            "온도",
            "습도",
            "소음",
            "공기질",
            "환경 정보",
            "센서 정보",
        }
    )


def is_get_room_booking_request(lowered_text: str) -> bool:
    booking_phrases = {
        "booking info",
        "room booking",
        "booked",
        "next meeting",
        "scheduled meeting",
        "obtp available",
        "one button to push",
    }
    if not any(phrase in lowered_text for phrase in booking_phrases):
        return False
    if is_join_obtp_request(lowered_text):
        return False
    return any(
        phrase in lowered_text
        for phrase in {
            "show booking info",
            "get booking info",
            "room booking",
            "is the room booked",
            "is room booked",
            "next meeting",
            "scheduled meeting",
            "obtp available",
            "is obtp available",
            "one button to push",
        }
    )


def is_webex_join_request(lowered_text: str) -> bool:
    if "webex join" in lowered_text or "join webex" in lowered_text:
        return True
    if lowered_text.strip() in {"join meeting", "join a meeting", "join the meeting"}:
        return True
    return ("미팅" in lowered_text or "회의" in lowered_text or "meeting" in lowered_text) and any(
        phrase in lowered_text
        for phrase in {
            "참여",
            "참가",
            "입장",
            "조인",
            "join",
        }
    )


def is_join_obtp_request(lowered_text: str) -> bool:
    return any(
        phrase in lowered_text
        for phrase in {
            "join scheduled meeting",
            "join the scheduled meeting",
            "join obtp",
            "join the obtp",
            "join next meeting",
            "join the next meeting",
        }
    )


def is_set_camera_mode_request(lowered_text: str) -> bool:
    return any(
        phrase in lowered_text
        for phrase in {
            "set camera mode",
            "camera mode to",
            "camera mode best",
            "camera mode speaker",
            "camera mode frames",
            "switch camera mode",
            "change camera mode",
            "enable frames",
            "speaker closeup",
            "best overview",
        }
    )


def mentions_camera_mode(lowered_text: str) -> bool:
    return any(
        phrase in lowered_text
        for phrase in {
            "camera mode",
            "camera framing",
            "frames",
            "speaker closeup",
            "best overview",
        }
    )


def extract_target_device(
    text: str, explicit_target: str | None, default_target_device: str
) -> str:
    mentioned_target_device = extract_mentioned_target_device(text, explicit_target)
    if mentioned_target_device is not None:
        return mentioned_target_device
    return default_target_device


def extract_mentioned_target_device(text: str, explicit_target: str | None) -> str | None:
    if explicit_target:
        return explicit_target

    korean_phrase_target = extract_korean_phrase_target_device(text)
    if korean_phrase_target is not None:
        return korean_phrase_target

    lowered = " ".join(text.casefold().split())
    if "룸바" in lowered or "룸 바" in lowered or "room bar" in lowered:
        return "Room Bar"

    trailing_target = extract_trailing_target_device(text)
    if trailing_target is not None:
        return trailing_target

    turn_toggle_target = extract_turn_toggle_target_device(text)
    if turn_toggle_target is not None:
        return turn_toggle_target

    match = re.search(
        r"(?:status|volume|reboot|factory reset|webex join|join webex|dial|call|hang up|hangup|drop|dtmf|mute|unmute|selfview|layout|presentation|share|input source|camera preset|speakertrack|speaker track|standby|전화|통화)\s+(?:of|on|for|로|으로)\s+([A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip().rstrip("?.!")


def extract_trailing_target_device(text: str) -> str | None:
    match = re.search(
        r"\b(?:on|for|of)\s+([A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)\s*[?.!]*$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    candidate = match.group(1).strip().rstrip("?.!")
    lowered = " ".join(text.casefold().split())
    normalized_candidate = " ".join(candidate.casefold().split())
    if lowered.startswith("turn on ") and normalized_candidate in TOGGLE_ACTION_NAMES:
        return None
    return candidate


def extract_turn_toggle_target_device(text: str) -> str | None:
    lowered = " ".join(text.casefold().split())
    for action in ("turn on", "turn off"):
        prefix = f"{action} "
        if not lowered.startswith(prefix):
            continue
        candidate = text[len(prefix) :].strip().rstrip("?.!")
        normalized_candidate = " ".join(candidate.casefold().split())
        if normalized_candidate in TOGGLE_ACTION_NAMES:
            return None
        if candidate:
            return candidate
    return None


def strip_trailing_target_clause(text: str) -> str:
    match = re.search(
        r"^(.*?)(?:\s+\b(?:on|for|of)\s+[A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)\s*[?.!]*$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return text.strip().rstrip("?.!")
    return match.group(1).strip().rstrip("?.!")


def extract_korean_phrase_target_device(text: str) -> str | None:
    lowered = text.lower()
    if not any(
        token in lowered
        for token in {
            "전화",
            "통화",
            "음소거",
            "뮤트",
            "언뮤트",
            "미팅",
            "회의",
        }
    ):
        return None

    email_match = re.search(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+", text)
    candidate_text = text if email_match is None else text[: email_match.start()]
    number_match = re.search(r"(?<!\d)(?:\d[\s-]*){9,14}(?!\d)", candidate_text)
    if number_match is not None:
        before_number = candidate_text[: number_match.start()].strip()
        target_match = re.search(r"(.+?)(?:로|으로)\s*$", before_number)
        if target_match:
            candidate = target_match.group(1).strip().rstrip("?.!")
            return candidate or None
    candidate_match = re.search(r"(.+?)(?:로|으로)\s*$", candidate_text)
    if not candidate_match:
        candidate_match = re.search(
            r"^(.+?)\s+(?:음소거(?:\s+해줘)?|뮤트(?:해줘)?|언뮤트(?:해줘)?|음소거\s+해제(?:해줘)?)\s*$",
            candidate_text,
        )
    if not candidate_match:
        return None

    candidate = candidate_match.group(1).strip().rstrip("?.!")
    if not candidate:
        return None
    if any(
        token in candidate.lower()
        for token in {
            "전화",
            "통화",
            "call",
            "dial",
            "음소거",
            "뮤트",
            "언뮤트",
            "미팅",
            "회의",
        }
    ):
        return None
    return candidate


def extract_volume_level(text: str) -> int | None:
    match = re.search(r"(?:set volume|volume)\s+(?:to\s+)?(\d{1,3})", text)
    if match:
        level = int(match.group(1))
        return level if 0 <= level <= 100 else None
    lowered = text.lower()
    if any(token in lowered for token in {"volume up", "increase volume", "볼륨 올", "볼륨 높"}):
        return None
    if any(
        token in lowered
        for token in {
            "volume down",
            "decrease volume",
            "볼륨 내",
            "볼륨 낮",
            "볼륨 줄",
        }
    ):
        return None
    return None


def extract_webex_meeting_identifier(text: str) -> str | None:
    stripped_text = strip_trailing_target_clause(text)
    match = re.search(
        r"(?:webex join|join webex)(?:\s+meeting)?\s+([A-Za-z0-9@._:-]+)",
        stripped_text,
        re.IGNORECASE,
    )
    if not match:
        digit_match = re.search(r"(?<!\d)(?:\d[\s-]*){9,14}(?!\d)", stripped_text)
        if digit_match:
            candidate = re.sub(r"\D+", "", digit_match.group(0))
            return candidate if 9 <= len(candidate) <= 14 else None
        return None
    candidate = match.group(1).strip().rstrip("?.!")
    if candidate.lower() in {"on", "for", "of"}:
        return None
    return re.sub(r"\D+", "", candidate) if re.fullmatch(r"[\d\s-]+", candidate) else candidate


def extract_dial_address(text: str) -> str | None:
    stripped_text = strip_trailing_target_clause(text)
    match = re.search(
        r"(?:dial|call|join sip|sip|전화(?:해줘)?|통화(?:해줘)?)\s+(?:to\s+|로\s+|으로\s+)?([A-Za-z0-9@._:+-]+)",
        stripped_text,
        re.IGNORECASE,
    )
    if not match:
        fallback_match = re.search(r"([A-Za-z0-9._+-]+@[A-Za-z0-9.-]+)", stripped_text)
        if not fallback_match:
            return None
        return fallback_match.group(1).strip().rstrip("?.!")
    return match.group(1).strip().rstrip("?.!")


def extract_dtmf_tones(text: str) -> str | None:
    match = re.search(
        r"(?:dtmf|send tone|send digits)\s+(?:to\s+)?([0-9A-D#*,]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip().upper()


def extract_call_id(text: str) -> int | None:
    match = re.search(r"call(?:\s+id)?\s+(\d+)", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def mentions_microphone_toggle(lowered_text: str) -> bool:
    return (
        "microphone" in lowered_text
        or "mic " in lowered_text
        or lowered_text.endswith(" mic")
        or "mute" in lowered_text
        or "unmute" in lowered_text
        or "음소거" in lowered_text
        or "뮤트" in lowered_text
        or "언뮤트" in lowered_text
    )


def mentions_video_toggle(lowered_text: str) -> bool:
    return (
        "video" in lowered_text
        or "camera" in lowered_text
        or "비디오" in lowered_text
        or "카메라" in lowered_text
    )


def extract_camera_mode(lowered_text: str) -> WritableCameraMode | None:
    mode_phrases: dict[WritableCameraMode, set[str]] = {
        WritableCameraMode.MANUAL: {"manual", "수동"},
        WritableCameraMode.DYNAMIC: {"dynamic", "동적"},
        WritableCameraMode.BEST_OVERVIEW: {
            "best overview",
            "best_overview",
            "bestoverview",
            "overview",
        },
        WritableCameraMode.CLOSEUP: {
            "closeup",
            "close up",
            "speaker closeup",
            "speaker close up",
        },
        WritableCameraMode.FRAMES: {"frames", "frame"},
        WritableCameraMode.GROUP_AND_SPEAKER: {
            "group and speaker",
            "group_and_speaker",
            "groupandspeaker",
            "group speaker",
        },
    }
    for mode, phrases in mode_phrases.items():
        if any(phrase in lowered_text for phrase in phrases):
            return mode
    return None


def extract_toggle_state(
    lowered_text: str,
    enable_words: set[str],
    disable_words: set[str],
    enable_value: bool = True,
) -> bool | None:
    for phrase in disable_words:
        if phrase in lowered_text:
            return not enable_value
    for phrase in enable_words:
        if phrase in lowered_text:
            return enable_value
    return None


def extract_layout_name(text: str) -> str | None:
    lowered = text.lower()
    if any(phrase in lowered for phrase in PROMINENT_LAYOUT_PHRASES):
        return "Prominent"
    match = re.search(r"layout\s+(?:to\s+)?([A-Za-z0-9_-]+)", text, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().rstrip("?.!")


def extract_source_id(text: str) -> str | None:
    match = SOURCE_ALIAS_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip().rstrip("?.!")


def extract_matrix_assign(text: str) -> MatrixAssignMatch | None:
    stripped_text = strip_trailing_target_clause(text)
    match = re.search(
        r"matrix\s+assign\s+output\s+([A-Za-z0-9_-]+)\s+(?:to\s+)?mode\s+([A-Za-z0-9_-]+)\s+layout\s+([A-Za-z0-9_-]+)(?:\s+source\s+([A-Za-z0-9_-]+))?(?:\s+(remote\s+main))?",
        stripped_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    remote_main = match.group(5)
    return {
        "output": match.group(1).strip().rstrip("?.!"),
        "mode": match.group(2).strip().rstrip("?.!"),
        "layout": match.group(3).strip().rstrip("?.!"),
        "source_id": (match.group(4).strip().rstrip("?.!") if match.group(4) is not None else None),
        "remote_main": True if remote_main is not None else None,
    }


def extract_matrix_unassign(text: str) -> MatrixUnassignMatch | None:
    stripped_text = strip_trailing_target_clause(text)
    match = re.search(
        r"matrix\s+unassign\s+output\s+([A-Za-z0-9_-]+)(?:\s+source\s+([A-Za-z0-9_-]+))?(?:\s+(remote\s+main))?",
        stripped_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    remote_main = match.group(3)
    return {
        "output": match.group(1).strip().rstrip("?.!"),
        "source_id": (match.group(2).strip().rstrip("?.!") if match.group(2) is not None else None),
        "remote_main": True if remote_main is not None else None,
    }


def extract_matrix_swap(text: str) -> MatrixSwapMatch | None:
    stripped_text = strip_trailing_target_clause(text)
    match = re.search(
        r"matrix\s+swap\s+output\s+([A-Za-z0-9_-]+)\s+(?:with|and)\s+output\s+([A-Za-z0-9_-]+)",
        stripped_text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "output_a": match.group(1).strip().rstrip("?.!"),
        "output_b": match.group(2).strip().rstrip("?.!"),
    }


def extract_preset_id(text: str) -> str | None:
    match = re.search(
        r"(?:camera preset|preset)\s+(?:to\s+)?([A-Za-z0-9_-]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip().rstrip("?.!")


def extract_camera_position(text: str) -> CameraPositionMatch | None:
    stripped_text = strip_trailing_target_clause(text)
    lowered = stripped_text.lower()
    if "camera preset" in lowered or "speakertrack" in lowered:
        return None

    camera_match = re.search(
        r"\bcamera\s+(\d+)\b",
        stripped_text,
        re.IGNORECASE,
    )
    if camera_match is None:
        return None

    pan: int | None = None
    tilt: int | None = None
    zoom: int | None = None

    if re.search(r"\b(?:pan\s+)?left\b", lowered):
        pan = CAMERA_PAN_STEP
    elif re.search(r"\b(?:pan\s+)?right\b", lowered):
        pan = -CAMERA_PAN_STEP

    if re.search(r"\b(?:tilt\s+)?up\b", lowered):
        tilt = CAMERA_TILT_STEP
    elif re.search(r"\b(?:tilt\s+)?down\b", lowered):
        tilt = -CAMERA_TILT_STEP

    if re.search(r"\bzoom\s+in\b", lowered):
        zoom = -CAMERA_ZOOM_STEP
    elif re.search(r"\bzoom\s+out\b", lowered):
        zoom = CAMERA_ZOOM_STEP

    if pan is None and tilt is None and zoom is None:
        return None

    return {
        "camera_id": camera_match.group(1).strip().rstrip("?.!"),
        "pan": pan,
        "tilt": tilt,
        "zoom": zoom,
    }


def extract_microphone_mode(
    lowered_text: str,
) -> MicrophoneProcessingMode | None:
    mode_phrases: dict[MicrophoneProcessingMode, set[str]] = {
        MicrophoneProcessingMode.NORMAL: {"normal", "standard"},
        MicrophoneProcessingMode.NOISE_REDUCTION: {
            "noise reduction",
            "noise-reduction",
        },
        MicrophoneProcessingMode.VOICE_OPTIMIZED: {
            "voice optimized",
            "voice-optimized",
            "focused",
        },
        MicrophoneProcessingMode.MUSIC_MODE: {"music mode", "music-mode"},
    }
    for mode, phrases in mode_phrases.items():
        if any(phrase in lowered_text for phrase in phrases):
            return mode
    return None


def extract_display_mode(lowered_text: str) -> DisplayMode | None:
    compact_text = re.sub(r"\s+", "", lowered_text)
    mode_phrases: tuple[tuple[DisplayMode, tuple[str, ...]], ...] = (
        (
            DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
            (
                "left video right presentation",
                "left-video-right-presentation",
                "dual presentation only",
                "dual-presentation-only",
                "dual presentation-only",
                "dual-presentation only",
                "dualpresentationonly",
                "왼쪽영상오른쪽프리젠테이션",
                "왼쪽영상오른쪽프레젠테이션",
            ),
        ),
        (
            DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
            (
                "left presentation right video",
                "left-presentation-right-video",
                "왼쪽프리젠테이션오른쪽영상",
                "왼쪽프레젠테이션오른쪽영상",
            ),
        ),
        (
            DisplayMode.BOTH_PRESENTATION,
            (
                "both presentation",
                "both-presentation",
                "양쪽모두프리젠테이션",
                "양쪽모두프레젠테이션",
            ),
        ),
        (
            DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
            (
                "left video right video",
                "left-video-right-video",
                "dual",
                "왼쪽영상오른쪽영상",
            ),
        ),
    )
    for mode, phrases in mode_phrases:
        if any(phrase in lowered_text or phrase in compact_text for phrase in phrases):
            return mode
    return None


def extract_display_role(lowered_text: str) -> DisplayRole | None:
    role_phrases: dict[DisplayRole, set[str]] = {
        DisplayRole.AUTO: {"auto"},
        DisplayRole.FIRST: {"first"},
        DisplayRole.SECOND: {"second"},
        DisplayRole.THIRD: {"third"},
        DisplayRole.PRESENTATION_ONLY: {
            "presentation only",
            "presentation-only",
        },
        DisplayRole.RECORDER: {"recorder"},
    }
    for role, phrases in role_phrases.items():
        if any(phrase in lowered_text for phrase in phrases):
            return role
    return None


def extract_connector_id(text: str) -> int | None:
    match = re.search(r"connector\s+(\d+)", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))
