"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

import asyncio

import pytest

from assistant_app.main import app
from shared.contracts import (
    InboundUserMessage,
    MessageSource,
)
from tests._helpers import (
    as_mapping,
    build_authenticated_client,
    temporary_env,
)

client = build_authenticated_client(app)


def test_rule_based_provider_understands_korean_dial_request() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="korean-dial",
                user_id="debug-user",
                text="홈오피스로 youngcle@cisco.com 으로 전화해줘",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="korean-dial", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "dial"
    assert decision.action_proposal.dial is not None
    assert decision.action_proposal.dial.target_device == "홈오피스"
    assert decision.action_proposal.dial.address == "youngcle@cisco.com"


def test_rule_based_provider_understands_camera_position_command() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="camera-position-rule-based",
                user_id="debug-user",
                text="camera 3 tilt up on Board Pro",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="camera-position-rule-based", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "adjust_camera_position"
    assert decision.action_proposal.adjust_camera_position is not None
    assert decision.action_proposal.adjust_camera_position.target_device == "Board Pro"
    assert decision.action_proposal.adjust_camera_position.camera_id == "3"
    assert decision.action_proposal.adjust_camera_position.pan is None
    assert decision.action_proposal.adjust_camera_position.tilt == 1000
    assert decision.action_proposal.adjust_camera_position.zoom is None


def test_rule_based_provider_understands_get_camera_mode_command() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="camera-mode-rule-based-get",
                user_id="debug-user",
                text="what camera mode is on Board Pro",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="camera-mode-rule-based-get", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "get_camera_mode"
    assert decision.action_proposal.get_camera_mode is not None


def test_rule_based_provider_understands_korean_mute_without_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import (
        Intent,
        SessionContext,
    )

    provider = RuleBasedProvider(default_target_device="")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="korean-mute-no-target",
                user_id="debug-user",
                text="뮤트해줘",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="korean-mute-no-target", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent == Intent.SET_MICROPHONE_MUTE
    assert decision.action_proposal.set_microphone_mute is not None
    assert decision.action_proposal.set_microphone_mute.target_device == ""
    assert decision.action_proposal.set_microphone_mute.muted is True


def test_rule_based_provider_understands_korean_targeted_mute() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="korean-mute-targeted",
                user_id="debug-user",
                text="Codec Pro G2 음소거 해줘",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="korean-mute-targeted", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "set_microphone_mute"
    assert decision.action_proposal.set_microphone_mute is not None
    assert decision.action_proposal.set_microphone_mute.target_device == "Codec Pro G2"
    assert decision.action_proposal.set_microphone_mute.muted is True


def test_rule_based_provider_understands_korean_volume_without_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import (
        Intent,
        SessionContext,
    )

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="korean-volume-no-target",
                user_id="debug-user",
                text="볼륨 높여줘",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="korean-volume-no-target", turns=[]),
        )
    )

    assert decision.pending_action is not None
    assert decision.pending_action.intent == Intent.SET_VOLUME
    assert decision.pending_action.target_device is None
    assert decision.pending_action.level is None


def test_rule_based_provider_prefers_dual_presentation_only_over_dual() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="display-mode-rule-based-presentation-only",
                user_id="debug-user",
                text="Codec Pro G2 Dual-presentation-only",
                source=MessageSource.DEBUG,
                target_device="Codec Pro G2",
            ),
            SessionContext(session_id="display-mode-rule-based-presentation-only", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "set_display_mode"
    assert decision.action_proposal.set_display_mode is not None
    assert decision.action_proposal.set_display_mode.mode.value == "left-video-right-presentation"
    assert decision.action_proposal.set_display_mode.target_device == "Codec Pro G2"


def test_rule_based_provider_understands_get_environment_info_command() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="environment-rule-based-get",
                user_id="debug-user",
                text="what is the temperature, humidity, and air quality on Board Pro",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="environment-rule-based-get", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "get_environment_info"
    assert decision.action_proposal.get_environment_info is not None
    assert decision.action_proposal.get_environment_info.target_device == "Board Pro"


def test_rule_based_provider_understands_get_room_booking_command() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="room-booking-rule-based-get",
                user_id="debug-user",
                text="next meeting on Board Pro",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="room-booking-rule-based-get", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "get_room_booking"
    assert decision.action_proposal.get_room_booking is not None
    assert decision.action_proposal.get_room_booking.target_device == "Board Pro"


def test_rule_based_provider_keeps_generic_status_queries_on_get_status() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="generic-status-rule-based",
                user_id="debug-user",
                text="get status of Board Pro",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="generic-status-rule-based", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "get_status"
    assert decision.action_proposal.get_status is not None
    assert decision.action_proposal.get_environment_info is None


def test_rule_based_provider_understands_join_obtp_command() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="join-obtp-rule-based",
                user_id="debug-user",
                text="join the scheduled meeting on Board Pro",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="join-obtp-rule-based", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "join_obtp"
    assert decision.action_proposal.join_obtp is not None
    assert decision.action_proposal.join_obtp.target_device == "Board Pro"


def test_rule_based_provider_understands_set_camera_mode_command() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="camera-mode-rule-based-set",
                user_id="debug-user",
                text="set camera mode to group and speaker on Board Pro",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="camera-mode-rule-based-set", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "set_camera_mode"
    assert decision.action_proposal.set_camera_mode is not None
    assert decision.action_proposal.set_camera_mode.target_device == "Board Pro"
    assert decision.action_proposal.set_camera_mode.mode.value == "GroupAndSpeaker"


@pytest.mark.parametrize(
    "text",
    [
        "set camera mode to auto on Board Pro",
        "set camera mode to off on Board Pro",
        "set camera mode to presentertrack on Board Pro",
        "set camera mode to selfview on Board Pro",
    ],
)
def test_rule_based_provider_rejects_unsupported_camera_mode_command(text: str) -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="camera-mode-rule-based-unsupported",
                user_id="debug-user",
                text=text,
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="camera-mode-rule-based-unsupported", turns=[]),
        )
    )

    assert decision.action_proposal is None
    assert isinstance(decision.reply_text, str)


def test_rule_based_provider_ignores_non_numeric_camera_position_command() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="camera-position-rule-based-invalid",
                user_id="debug-user",
                text="camera front tilt up on Board Pro",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="camera-position-rule-based-invalid", turns=[]),
        )
    )

    assert decision.action_proposal is None
    assert isinstance(decision.reply_text, str)


def test_rule_based_provider_extracts_trailing_target_for_webex_join() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="webex-join-trailing-target",
                user_id="debug-user",
                text="webex join 987654321 on Board Pro",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="webex-join-trailing-target", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.webex_join is not None
    assert decision.action_proposal.webex_join.meeting_identifier == "987654321"
    assert decision.action_proposal.webex_join.target_device == "Board Pro"


def test_rule_based_provider_extracts_trailing_target_for_dial() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="dial-trailing-target",
                user_id="debug-user",
                text="dial user@example.com on Home Office",
                source=MessageSource.DEBUG,
            ),
            SessionContext(session_id="dial-trailing-target", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.dial is not None
    assert decision.action_proposal.dial.address == "user@example.com"
    assert decision.action_proposal.dial.target_device == "Home Office"


def test_rule_based_provider_understands_turn_on_selfview_without_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import (
        Intent,
        SessionContext,
    )

    provider = RuleBasedProvider(default_target_device="")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="selfview-turn-on-no-target",
                user_id="debug-user",
                text="turn on Selfview",
                source=MessageSource.WEBEX,
            ),
            SessionContext(session_id="selfview-turn-on-no-target", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent == Intent.SET_SELFVIEW
    assert decision.action_proposal.set_selfview is not None
    assert decision.action_proposal.set_selfview.target_device == ""
    assert decision.action_proposal.set_selfview.enabled is True


def test_rule_based_turn_on_toggle_commands_without_target_prompt_for_device() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import Intent, SessionContext

    cases = [
        ("turn on SpeakerTrack", Intent.SET_SPEAKERTRACK, "set_speakertrack", "enabled"),
        ("turn on standby", Intent.SET_STANDBY, "set_standby", "enabled"),
        ("start presentation", Intent.SET_PRESENTATION, "set_presentation", "enabled"),
        ("turn on video", Intent.SET_VIDEO_MUTE, "set_video_mute", "muted"),
    ]
    provider = RuleBasedProvider(default_target_device="")

    for text, intent, payload_name, bool_field in cases:
        decision = asyncio.run(
            provider.analyze_message(
                InboundUserMessage(
                    session_id=f"toggle-no-target-{intent.value}",
                    user_id="debug-user",
                    text=text,
                    source=MessageSource.WEBEX,
                ),
                SessionContext(session_id=f"toggle-no-target-{intent.value}", turns=[]),
            )
        )

        assert decision.action_proposal is not None, text
        assert decision.action_proposal.intent == intent
        payload = getattr(decision.action_proposal, payload_name)
        assert payload is not None
        assert payload.target_device == ""
        assert getattr(payload, bool_field) is not None


def test_rule_based_understands_korean_selfview_and_video_without_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import Intent, SessionContext

    cases = [
        ("셀프뷰 켜줘", Intent.SET_SELFVIEW, "set_selfview", "enabled", True),
        ("셀프뷰 꺼줘", Intent.SET_SELFVIEW, "set_selfview", "enabled", False),
        ("비디오 켜줘", Intent.SET_VIDEO_MUTE, "set_video_mute", "muted", False),
        ("비디오 꺼줘", Intent.SET_VIDEO_MUTE, "set_video_mute", "muted", True),
    ]
    provider = RuleBasedProvider(default_target_device="")

    for text, intent, payload_name, bool_field, expected_value in cases:
        decision = asyncio.run(
            provider.analyze_message(
                InboundUserMessage(
                    session_id=f"korean-toggle-no-target-{intent.value}",
                    user_id="debug-user",
                    text=text,
                    source=MessageSource.WEBEX,
                ),
                SessionContext(session_id=f"korean-toggle-no-target-{intent.value}", turns=[]),
            )
        )

        assert decision.action_proposal is not None, text
        assert decision.action_proposal.intent == intent
        payload = getattr(decision.action_proposal, payload_name)
        assert payload is not None
        assert payload.target_device == ""
        assert getattr(payload, bool_field) is expected_value


def test_rule_based_provider_extracts_korean_webex_join_number_without_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="korean-webex-join-number-no-target",
                user_id="debug-user",
                text="2556 542 7373 미팅 참여해줘",
                source=MessageSource.WEBEX,
            ),
            SessionContext(session_id="korean-webex-join-number-no-target", turns=[]),
        )
    )

    assert decision.pending_action is not None
    assert decision.pending_action.intent.value == "webex_join"
    assert decision.pending_action.meeting_identifier == "25565427373"
    assert decision.pending_action.target_device is None


def test_rule_based_provider_extracts_korean_webex_join_number_with_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="korean-webex-join-number-target",
                user_id="debug-user",
                text="Room Bar 로 25565427373 미팅번호 미팅 참여",
                source=MessageSource.WEBEX,
            ),
            SessionContext(session_id="korean-webex-join-number-target", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.webex_join is not None
    assert decision.action_proposal.webex_join.meeting_identifier == "25565427373"
    assert decision.action_proposal.webex_join.target_device == "Room Bar"


def test_rule_based_provider_extracts_korean_environment_info_with_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import SessionContext

    provider = RuleBasedProvider(default_target_device="demo-roomkit")

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="korean-environment-info-target",
                user_id="debug-user",
                text="Room Bar 온도와 습도 확인해줘",
                source=MessageSource.WEBEX,
            ),
            SessionContext(session_id="korean-environment-info-target", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.get_environment_info is not None
    assert decision.action_proposal.get_environment_info.target_device == "Room Bar"


def test_room_bar_drop_routes_to_hang_up_with_rule_based_fallback() -> None:
    with temporary_env({"DEFAULT_PROVIDER": "rule_based"}):
        scoped_client = build_authenticated_client()
        policy_response = scoped_client.put(
            "/admin/policies/hang_up",
            json={
                "allowed_modes": ["separated", "all-llm"],
                "risk_level": "low",
                "approval_state": "not_required",
                "reason": "Allow direct hangup execution in debug flow test.",
            },
        )
        assert policy_response.status_code == 200
        response = scoped_client.post(
            "/debug/messages",
            json={
                "session_id": "room-bar-drop-fallback",
                "user_id": "debug-user",
                "text": "Room Bar drop",
                "source": "webex",
                "room_id": "debug-room",
                "target_device": "Room Bar",
            },
        )
    assert response.status_code == 200
    body = response.json()
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert (
        "hang up requested for Room Bar" in text or "hang up requested for room bar" in text.lower()
    )
    assert "invalid action payload" not in text.lower()
