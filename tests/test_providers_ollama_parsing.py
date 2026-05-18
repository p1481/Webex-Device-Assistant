"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

import pytest

from assistant_app.main import app
from shared.contracts import (
    InboundUserMessage,
    MessageSource,
)
from tests._helpers import (
    build_authenticated_client,
)

client = build_authenticated_client(app)


def test_ollama_parser_accepts_flat_action_payload_shape() -> None:
    from assistant_app.providers.ollama import OllamaProvider

    provider = OllamaProvider(default_target_device="demo-roomkit")

    decision = provider._parse_decision(
        '{"intent": "dial", "summary": "Calling youngcle@cisco.com to the home office.", "confidence": 0.95, "dial": {"target_device": "demo-roomkit", "address": "youngcle@cisco.com"}}',
        InboundUserMessage(
            session_id="flat-action-shape",
            user_id="debug-user",
            text="홈오피스로 youngcle@cisco.com 으로 전화해줘",
            source=MessageSource.DEBUG,
        ),
    )

    assert decision is not None
    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "dial"
    assert decision.action_proposal.dial is not None
    assert decision.action_proposal.dial.target_device == "홈오피스"
    assert decision.action_proposal.dial.address == "youngcle@cisco.com"


def test_ollama_detects_invalid_structured_output() -> None:
    from assistant_app.providers.ollama import OllamaProvider

    provider = OllamaProvider(default_target_device="demo-roomkit")

    assert provider._looks_like_structured_output(
        '{"reply_text": null, "action_proposal": {"intent": "dial", "target_device": "demo-roomkit", "address": "youngcle@cisco.com"}}'
    )


def test_ollama_parser_accepts_hybrid_nested_action_payload_shape() -> None:
    from assistant_app.providers.ollama import OllamaProvider

    provider = OllamaProvider(default_target_device="demo-roomkit")

    decision = provider._parse_decision(
        '{"reply_text": null, "action_proposal": {"intent": "dial", "target_device": "demo-roomkit", "address": "youngcle@cisco.com"}, "summary": "Calling youngcle@cisco.com to the home office.", "confidence": 0.95}',
        InboundUserMessage(
            session_id="hybrid-action-shape",
            user_id="debug-user",
            text="홈오피스로 youngcle@cisco.com 으로 전화해줘",
            source=MessageSource.DEBUG,
        ),
    )

    assert decision is not None
    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "dial"
    assert decision.action_proposal.dial is not None
    assert decision.action_proposal.dial.target_device == "홈오피스"
    assert decision.action_proposal.dial.address == "youngcle@cisco.com"
    assert decision.action_proposal.dial.address == "youngcle@cisco.com"


def test_ollama_parser_preserves_blank_target_dial_as_action_proposal() -> None:
    from assistant_app.providers.ollama import OllamaProvider

    provider = OllamaProvider(default_target_device="")

    decision = provider._parse_decision(
        '{"reply_text": null, "action_proposal": {"intent": "dial", "summary": "Dial from the target device.", "confidence": 0.91, "dial": {"target_device": "", "address": "youngcle@cisco.com"}}}',
        InboundUserMessage(
            session_id="ollama-blank-target-dial",
            user_id="debug-user",
            text="dial youngcle@cisco.com",
            source=MessageSource.DEBUG,
        ),
    )

    assert decision is not None
    assert decision.pending_action is None
    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "dial"
    assert decision.action_proposal.dial is not None
    assert decision.action_proposal.dial.address == "youngcle@cisco.com"
    assert decision.action_proposal.dial.target_device == ""


def test_ollama_parser_accepts_camera_position_payload() -> None:
    from assistant_app.providers.ollama import OllamaProvider

    provider = OllamaProvider(default_target_device="")

    decision = provider._parse_decision(
        '{"reply_text": null, "action_proposal": {"intent": "adjust_camera_position", "summary": "Adjust a specific camera position.", "confidence": 0.94, "adjust_camera_position": {"target_device": "Board Pro", "camera_id": "2", "pan": -1000, "tilt": null, "zoom": null}}}',
        InboundUserMessage(
            session_id="ollama-camera-position",
            user_id="debug-user",
            text="camera 2 right on Board Pro",
            source=MessageSource.DEBUG,
        ),
    )

    assert decision is not None
    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "adjust_camera_position"
    assert decision.action_proposal.adjust_camera_position is not None
    assert decision.action_proposal.adjust_camera_position.target_device == "Board Pro"
    assert decision.action_proposal.adjust_camera_position.camera_id == "2"
    assert decision.action_proposal.adjust_camera_position.pan == -1000
    assert decision.action_proposal.adjust_camera_position.tilt is None
    assert decision.action_proposal.adjust_camera_position.zoom is None


def test_ollama_parser_accepts_camera_mode_payload() -> None:
    from assistant_app.providers.ollama import OllamaProvider

    provider = OllamaProvider(default_target_device="")

    decision = provider._parse_decision(
        '{"reply_text": null, "action_proposal": {"intent": "set_camera_mode", "summary": "Change the camera mode.", "confidence": 0.94, "set_camera_mode": {"target_device": "Board Pro", "mode": "GroupAndSpeaker"}}}',
        InboundUserMessage(
            session_id="ollama-camera-mode",
            user_id="debug-user",
            text="set camera mode to group and speaker on Board Pro",
            source=MessageSource.DEBUG,
        ),
    )

    assert decision is not None
    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "set_camera_mode"
    assert decision.action_proposal.set_camera_mode is not None
    assert decision.action_proposal.set_camera_mode.target_device == "Board Pro"
    assert decision.action_proposal.set_camera_mode.mode.value == "GroupAndSpeaker"


@pytest.mark.parametrize(
    "unsupported_mode",
    ["auto", "off", "presenter_track", "selfview"],
)
def test_ollama_parser_rejects_unsupported_camera_mode_payload(
    unsupported_mode: str,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider

    provider = OllamaProvider(default_target_device="")

    decision = provider._parse_decision(
        '{"reply_text": null, "action_proposal": {"intent": "set_camera_mode", "summary": "Change the camera mode.", "confidence": 0.94, "set_camera_mode": {"target_device": "Board Pro", "mode": "'
        + unsupported_mode
        + '"}}}',
        InboundUserMessage(
            session_id="ollama-camera-mode-invalid",
            user_id="debug-user",
            text=f"set camera mode to {unsupported_mode} on Board Pro",
            source=MessageSource.DEBUG,
        ),
    )

    assert decision is None


def test_ollama_parser_rejects_non_numeric_camera_position_payload() -> None:
    from assistant_app.providers.ollama import OllamaProvider

    provider = OllamaProvider(default_target_device="")

    decision = provider._parse_decision(
        '{"reply_text": null, "action_proposal": {"intent": "adjust_camera_position", "summary": "Adjust a specific camera position.", "confidence": 0.94, "adjust_camera_position": {"target_device": "Board Pro", "camera_id": "front", "pan": -1000, "tilt": null, "zoom": null}}}',
        InboundUserMessage(
            session_id="ollama-camera-position-invalid",
            user_id="debug-user",
            text="camera front right on Board Pro",
            source=MessageSource.DEBUG,
        ),
    )

    assert decision is None


def test_ollama_prompt_exposes_all_roomos_actions_and_llm_first_semantic_contract() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import Intent, SessionContext

    provider = OllamaProvider(default_target_device="")
    messages = provider._build_messages(
        InboundUserMessage(
            session_id="semantic-contract",
            user_id="person-1",
            text="룸바 화면 공유 시작해줘",
            source=MessageSource.WEBEX,
        ),
        SessionContext(session_id="semantic-contract", turns=[]),
    )

    system_prompt = messages[0]["content"]
    assert "semantic interpretation" in system_prompt
    assert "Korean or English" in system_prompt
    assert "Do not depend on fixed command phrases" in system_prompt
    for intent in Intent:
        if intent in {Intent.CHAT, Intent.RESET_CONTEXT}:
            continue
        assert f'"{intent.value}"' in system_prompt
