"""Text-extraction helpers extracted from ``Orchestrator``.

Pure regex/string parsing utilities. No state.
"""

from __future__ import annotations

import re

from shared.contracts import InboundUserMessage, WritableCameraMode


def extract_follow_up_webex_meeting_identifier(text: str) -> str | None:
    match = re.search(
        r"(?:webex join|join webex)(?:\s+meeting)?\s+(https?://\S+|[A-Za-z0-9@._:/-]+)",
        text,
        re.IGNORECASE,
    )
    if match is not None:
        return match.group(1).strip().rstrip("?.!")

    candidate = strip_trailing_target_clause(text)
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


def extract_follow_up_dial_address(text: str) -> str | None:
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

    candidate = strip_trailing_target_clause(text)
    candidate = re.sub(r"^(?:to\s+)", "", candidate, flags=re.IGNORECASE).strip()
    if not candidate:
        return None
    if re.fullmatch(r"[A-Za-z0-9@._:+-]+", candidate) is None:
        return None
    return candidate.rstrip("?.!")


def extract_follow_up_volume_level(text: str) -> int | None:
    match = re.search(r"(?:set volume|volume)\s+(?:to\s+)?(\d{1,3})", text)
    if match is None:
        match = re.search(r"\b(\d{1,3})\b", text)
    if match is None:
        return None
    level = int(match.group(1))
    return level if 0 <= level <= 100 else None


def extract_trailing_target_device(text: str) -> str | None:
    match = re.search(
        r"\b(?:on|for|of)\s+([A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)\s*[?.!]*$",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group(1).strip().rstrip("?.!")


def strip_trailing_target_clause(text: str) -> str:
    match = re.search(
        r"^(.*?)(?:\s+\b(?:on|for|of)\s+[A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)\s*[?.!]*$",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return text.strip().rstrip("?.!")
    return match.group(1).strip().rstrip("?.!")


def extract_direct_target_device_response(text: str) -> str | None:
    candidate = re.sub(r"^(?:on|for|of)\s+", "", text.strip(), flags=re.IGNORECASE)
    normalized = candidate.rstrip("?.!")
    return normalized or None


def extract_explicit_camera_mode(normalized_text: str) -> WritableCameraMode | None:
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


def extract_camera_mode_target_device(message: InboundUserMessage) -> str | None:
    trailing_target = extract_trailing_target_device(message.text)
    if trailing_target:
        return trailing_target
    lowered = message.text.lower()
    markers = ["카메라모드", "카메라 모드", "camera mode", "cameramode"]
    marker_positions = [lowered.find(marker) for marker in markers if lowered.find(marker) > 0]
    if marker_positions:
        candidate = message.text[: min(marker_positions)].strip(" ,:：-–—")
        if candidate:
            return candidate
    return message.target_device


def extract_display_mode_target_device(message: InboundUserMessage) -> str | None:
    trailing_target = extract_trailing_target_device(message.text)
    if trailing_target:
        return trailing_target
    lowered = message.text.lower()
    markers = ["디스플레이모드", "디스플레이 모드", "display mode", "displaymode"]
    marker_positions = [lowered.find(marker) for marker in markers if lowered.find(marker) > 0]
    if marker_positions:
        candidate = message.text[: min(marker_positions)].strip(" ,:：-–—")
        if candidate:
            return candidate
    return message.target_device


def is_reset_message(text: str) -> bool:
    return text.strip().lower() in {
        "/reset",
        "/clear-context",
        "reset context",
        "clear context",
    }
