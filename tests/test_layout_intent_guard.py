import json

from assistant_app.providers.ollama import OllamaProvider
from device_executor.device_client import DeviceClient
from shared.contracts import InboundUserMessage, Intent


def test_ollama_provider_does_not_rewrite_frames_layout_as_speakertrack_mode() -> None:
    provider = OllamaProvider(default_target_device="Room Bar")
    message = InboundUserMessage(
        session_id="layout-guard",
        user_id="user-1",
        text="Frames",
        target_device="Room Bar",
    )
    content = json.dumps(
        {
            "reply_text": None,
            "action_proposal": {
                "intent": "set_layout",
                "summary": "Set Frames layout.",
                "confidence": 0.9,
                "set_layout": {
                    "target_device": "Room Bar",
                    "layout_name": "Frames",
                },
            },
        }
    )

    decision = provider._parse_decision(content, message)

    assert decision is not None
    assert decision.action_proposal is not None
    assert decision.action_proposal.intent == Intent.SET_LAYOUT
    assert decision.action_proposal.set_layout is not None
    assert decision.action_proposal.set_layout.layout_name == "Frames"


def test_ollama_provider_recovers_korean_room_bar_target_when_model_omits_payload_target() -> None:
    provider = OllamaProvider(default_target_device="")
    message = InboundUserMessage(
        session_id="ko-target",
        user_id="user-1",
        text="룸바 기기 상태 확인",
    )
    content = json.dumps(
        {
            "action_proposal": {
                "intent": "get_status",
                "summary": "Get device status.",
                "confidence": 0.8,
            }
        }
    )

    decision = provider._parse_decision(content, message)

    assert decision is not None
    proposal = decision.action_proposal
    assert proposal is not None
    assert proposal.intent == Intent.GET_STATUS
    assert proposal.get_status is not None
    assert proposal.get_status.target_device == "Room Bar"


def test_ollama_provider_prefers_korean_room_bar_mention_over_model_roomba_misread() -> None:
    provider = OllamaProvider(default_target_device="")
    message = InboundUserMessage(
        session_id="ko-roomba",
        user_id="user-1",
        text="룸바 기기 상태 확인",
    )
    content = json.dumps(
        {
            "action_proposal": {
                "intent": "get_status",
                "summary": "Get device status.",
                "confidence": 0.8,
                "get_status": {"target_device": "roomba"},
            }
        }
    )

    decision = provider._parse_decision(content, message)

    assert decision is not None
    proposal = decision.action_proposal
    assert proposal is not None
    assert proposal.get_status is not None
    assert proposal.get_status.target_device == "Room Bar"


def test_device_client_resolves_common_korean_device_aliases() -> None:
    assert DeviceClient.DEVICE_ALIASES["룸바"] == "Room Bar"
    assert DeviceClient.DEVICE_ALIASES["룸바 기기"] == "Room Bar"


def test_device_client_rejects_frames_as_video_layout_candidate() -> None:
    try:
        DeviceClient._normalize_layout_name("Frames")
    except ValueError as exc:
        assert "Frames is a camera mode, not a video layout" in str(exc)
    else:
        raise AssertionError("Frames must not be accepted as Video.Layout.SetLayout input")


def test_device_client_normalizes_supported_video_layout_candidates() -> None:
    assert DeviceClient._normalize_layout_name("prominent") == "Prominent"
    assert DeviceClient._normalize_layout_name("speaker only") == "SpeakerOnly"
