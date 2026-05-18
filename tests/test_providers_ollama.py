"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

import asyncio
import json
from typing import cast

import httpx
import pytest

from assistant_app.main import app
from shared.contracts import (
    InboundUserMessage,
    MessageSource,
)
from tests._helpers import (
    as_mapping,
    build_authenticated_client,
)
from tests.test_webex_integration import (
    QueuedAsyncClient,
    async_client_factory,
    build_client_queue,
    make_response,
)

client = build_authenticated_client(app)


def test_ollama_provider_can_render_execution_reply_markdown() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import ExecutionMode, ExecutionResult, ExecutionStatus, Intent

    provider = OllamaProvider(default_target_device="demo-roomkit")
    provider.settings.render_execution_replies = True

    async def fake_post(url: str, json: dict[str, object]) -> httpx.Response:
        assert url == "/chat"
        messages = cast(list[dict[str, str]], json["messages"])
        assert messages[0]["role"] == "system"
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://test/chat"),
            json={"message": {"content": "### 상태 요약\n- Home Office는 온라인입니다."}},
        )

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args
            _ = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            _ = exc_type
            _ = exc
            _ = tb

        async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
            return await fake_post(url, json)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient)
    try:
        rendered = asyncio.run(
            provider.render_execution_reply(
                ExecutionResult(
                    request_id="req-1",
                    intent=Intent.GET_STATUS,
                    execution_mode=ExecutionMode.ALL_LLM,
                    status=ExecutionStatus.SUCCESS,
                    message="Collected status from Home Office via all-LLM mode.",
                ),
                "Read-only device status can run in either mode for the MVP.",
                "Collected status from Home Office via all-LLM mode. Policy: Read-only device status can run in either mode for the MVP.",
            )
        )
    finally:
        monkeypatch.undo()

    assert rendered == "### 상태 요약\n- Home Office는 온라인입니다."


def test_ollama_provider_render_payload_omits_null_status_fields() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        DeviceStatusSnapshot,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        Intent,
    )

    provider = OllamaProvider(default_target_device="demo-roomkit")
    provider.settings.render_execution_replies = True

    async def fake_post(url: str, payload_json: dict[str, object]) -> httpx.Response:
        assert url == "/chat"
        messages = cast(list[dict[str, str]], payload_json["messages"])
        payload = json.loads(messages[1]["content"])
        execution_result_payload = as_mapping(payload["execution_result"])
        device_status = as_mapping(execution_result_payload["device_status"])
        assert device_status["display_name"] == "Board Pro"
        assert device_status["product_platform"] == "RoomOS"
        assert device_status["volume_muted"] is False
        assert "wifi_status" not in device_status
        assert "presentertrack_status" not in device_status
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://test/chat"),
            json={"message": {"content": "### 상태 요약\n- null fields omitted"}},
        )

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args
            _ = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            _ = exc_type
            _ = exc
            _ = tb

        async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
            return await fake_post(url, json)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient)
    try:
        rendered = asyncio.run(
            provider.render_execution_reply(
                ExecutionResult(
                    request_id="req-status-render-null-omit",
                    intent=Intent.GET_STATUS,
                    execution_mode=ExecutionMode.ALL_LLM,
                    status=ExecutionStatus.SUCCESS,
                    message="Collected status from Board Pro via all-LLM mode.",
                    device_status=DeviceStatusSnapshot(
                        target_device="Board Pro",
                        source="webex-cloud-xapi",
                        display_name="Board Pro",
                        online=True,
                        product_platform="RoomOS",
                        volume_muted=False,
                        wifi_status=None,
                        presentertrack_status=None,
                    ),
                ),
                "Read-only device status can run in either mode for the MVP.",
                "Collected status from Board Pro via all-LLM mode. online=True, display_name=Board Pro, product_platform=RoomOS, volume_muted=False. Policy: Read-only device status can run in either mode for the MVP.",
            )
        )
    finally:
        monkeypatch.undo()

    assert rendered == "### 상태 요약\n- null fields omitted"


def test_ollama_provider_render_payload_omits_null_room_booking_fields() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        Intent,
        RoomBookingStatus,
    )

    provider = OllamaProvider(default_target_device="demo-roomkit")
    provider.settings.render_execution_replies = True

    async def fake_post(url: str, payload_json: dict[str, object]) -> httpx.Response:
        assert url == "/chat"
        messages = cast(list[dict[str, str]], payload_json["messages"])
        payload = json.loads(messages[1]["content"])
        execution_result_payload = as_mapping(payload["execution_result"])
        room_booking_status = as_mapping(execution_result_payload["room_booking_status"])
        assert room_booking_status["display_name"] == "Board Pro"
        assert room_booking_status["availability_status"] == "Available"
        assert room_booking_status["obtp_available"] is False
        assert "next_meeting_title" not in room_booking_status
        assert "next_meeting_end_time" not in room_booking_status
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://test/chat"),
            json={"message": {"content": "### booking summary\n- null fields omitted"}},
        )

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args
            _ = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            _ = exc_type
            _ = exc
            _ = tb

        async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
            return await fake_post(url, json)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient)
    try:
        rendered = asyncio.run(
            provider.render_execution_reply(
                ExecutionResult(
                    request_id="req-room-booking-render-null-omit",
                    intent=Intent.GET_ROOM_BOOKING,
                    execution_mode=ExecutionMode.ALL_LLM,
                    status=ExecutionStatus.SUCCESS,
                    message="Collected room booking info from Board Pro via all-LLM mode.",
                    room_booking_status=RoomBookingStatus(
                        target_device="Board Pro",
                        source="webex-cloud-xapi",
                        display_name="Board Pro",
                        availability_status="Available",
                        obtp_available=False,
                        next_meeting_title=None,
                        next_meeting_end_time=None,
                    ),
                ),
                "Read-only room booking and OBTP queries can run in either mode for the MVP.",
                "Collected room booking info from Board Pro via all-LLM mode. Availability: Available. Join: OBTP not available. Policy: Read-only room booking and OBTP queries can run in either mode for the MVP.",
            )
        )
    finally:
        monkeypatch.undo()

    assert rendered == "### booking summary\n- null fields omitted"


def test_ollama_fallback_preserves_pending_follow_up() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        Intent,
        SessionContext,
    )

    provider = OllamaProvider(default_target_device="demo-roomkit")

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args
            _ = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            _ = exc_type
            _ = exc
            _ = tb

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            _ = kwargs
            return httpx.Response(
                200,
                request=httpx.Request("POST", f"http://test{url}"),
                json={"message": {"content": "not structured output"}},
            )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient)
    try:
        decision = asyncio.run(
            provider.analyze_message(
                InboundUserMessage(
                    session_id="ollama-pending-follow-up",
                    user_id="debug-user",
                    text="webex join on Board Pro",
                    source=MessageSource.DEBUG,
                ),
                SessionContext(session_id="ollama-pending-follow-up", turns=[]),
            )
        )
    finally:
        monkeypatch.undo()

    assert decision.pending_action is not None
    assert decision.pending_action.intent == Intent.WEBEX_JOIN
    assert decision.pending_action.target_device == "Board Pro"
    assert decision.pending_action.meeting_identifier is None


def test_ollama_rejects_internal_meeting_identifier_and_asks_follow_up() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        Intent,
        SessionContext,
    )

    provider = OllamaProvider(default_target_device="demo-roomkit")

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args
            _ = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            _ = exc_type
            _ = exc
            _ = tb

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            _ = kwargs
            return httpx.Response(
                200,
                request=httpx.Request("POST", f"http://test{url}"),
                json={
                    "message": {
                        "content": json.dumps(
                            {
                                "reply_text": None,
                                "action_proposal": {
                                    "intent": "webex_join",
                                    "summary": "Join a Webex meeting from the target device.",
                                    "confidence": 0.92,
                                    "webex_join": {
                                        "target_device": "Home Office",
                                        "meeting_identifier": "Y2lzY29zcGFyazovL3VzL1JPT00vZGIwOTQ1ZjAtM2RlMS0xMWYxLTkwYjUtNDc4M2QwYjc5NTU5",
                                    },
                                },
                            },
                            ensure_ascii=False,
                        )
                    }
                },
            )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient)
    try:
        decision = asyncio.run(
            provider.analyze_message(
                InboundUserMessage(
                    session_id="Y2lzY29zcGFyazovL3VzL1JPT00vZGIwOTQ1ZjAtM2RlMS0xMWYxLTkwYjUtNDc4M2QwYjc5NTU5",
                    room_id="Y2lzY29zcGFyazovL3VzL1JPT00vZGIwOTQ1ZjAtM2RlMS0xMWYxLTkwYjUtNDc4M2QwYjc5NTU5",
                    user_id="debug-user",
                    text="Home office로 미팅참여해줘",
                    source=MessageSource.DEBUG,
                ),
                SessionContext(
                    session_id="Y2lzY29zcGFyazovL3VzL1JPT00vZGIwOTQ1ZjAtM2RlMS0xMWYxLTkwYjUtNDc4M2QwYjc5NTU5",
                    turns=[],
                ),
            )
        )
    finally:
        monkeypatch.undo()

    assert decision.action_proposal is None
    assert decision.pending_action is not None
    assert decision.pending_action.intent == Intent.WEBEX_JOIN
    assert decision.pending_action.target_device == "Home Office"
    assert decision.pending_action.meeting_identifier is None


def test_ollama_korean_join_without_meeting_id_asks_follow_up() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import SessionContext

    provider = OllamaProvider(default_target_device="demo-roomkit")

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args
            _ = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            _ = exc_type
            _ = exc
            _ = tb

        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            _ = kwargs
            return httpx.Response(
                200,
                request=httpx.Request("POST", f"http://test{url}"),
                json={
                    "message": {
                        "content": json.dumps(
                            {
                                "reply_text": None,
                                "action_proposal": {
                                    "intent": "webex_join",
                                    "summary": "Join a Webex meeting from the target device.",
                                    "confidence": 0.88,
                                    "webex_join": {
                                        "target_device": "Home Office",
                                        "meeting_identifier": "cizyccosporak://us/ROOM/db00945f0-3de1-11f1-90b5-478230d2b79559",
                                    },
                                },
                            },
                            ensure_ascii=False,
                        )
                    }
                },
            )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient)
    try:
        decision = asyncio.run(
            provider.analyze_message(
                InboundUserMessage(
                    session_id="shared-room-join-korean",
                    room_id="shared-room-join-korean",
                    user_id="debug-user",
                    text="Home office로 미팅참여해줘",
                    source=MessageSource.DEBUG,
                ),
                SessionContext(session_id="shared-room-join-korean", turns=[]),
            )
        )
    finally:
        monkeypatch.undo()

    assert decision.action_proposal is None
    assert decision.pending_action is not None
    assert decision.pending_action.target_device == "Home Office"
    assert decision.pending_action.meeting_identifier is None


def test_ollama_provider_change_requires_available_host() -> None:
    response = client.put(
        "/admin/providers",
        json={
            "provider": "ollama",
            "model": "missing-model:latest",
            "base_url": "http://127.0.0.1:11434/api",
            "enabled": True,
        },
    )
    assert response.status_code == 409


def test_ollama_provider_uses_llm_before_rule_based_for_contextual_korean_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        Intent,
        ProviderKind,
        ProviderSettings,
        SessionContext,
    )

    llm_client = QueuedAsyncClient()
    llm_client.responses.append(
        make_response(
            "POST",
            "/chat",
            200,
            {
                "message": {
                    "content": json.dumps(
                        {
                            "reply_text": None,
                            "action_proposal": {
                                "intent": "set_selfview",
                                "summary": "LLM interpreted a contextual Korean selfview request.",
                                "confidence": 0.92,
                                "set_selfview": {
                                    "target_device": "",
                                    "enabled": True,
                                },
                            },
                        }
                    )
                }
            },
        )
    )
    _ = build_client_queue(llm_client)
    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", async_client_factory)

    provider = OllamaProvider(default_target_device="")
    provider.bind_settings(
        ProviderSettings(
            provider=ProviderKind.OLLAMA,
            model="test-model",
            base_url="http://ollama.local/api",
            enabled=True,
        )
    )

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="ollama-contextual-korean-selfview",
                user_id="person-1",
                text="화면에 내 모습 나오게 해줘",
                source=MessageSource.WEBEX,
            ),
            SessionContext(session_id="ollama-contextual-korean-selfview", turns=[]),
        )
    )

    assert len(llm_client.requests) == 1
    assert decision.action_proposal is not None
    assert decision.action_proposal.intent == Intent.SET_SELFVIEW
    assert decision.action_proposal.set_selfview is not None
    assert decision.action_proposal.set_selfview.target_device == ""
    assert decision.action_proposal.set_selfview.enabled is True


def test_ollama_provider_falls_back_to_rule_based_when_llm_returns_plain_non_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        Intent,
        ProviderKind,
        ProviderSettings,
        SessionContext,
    )

    llm_client = QueuedAsyncClient()
    llm_client.responses.append(
        make_response(
            "POST",
            "/chat",
            200,
            {"message": {"content": "I am not sure what to do."}},
        )
    )
    _ = build_client_queue(llm_client)
    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", async_client_factory)

    provider = OllamaProvider(default_target_device="")
    provider.bind_settings(
        ProviderSettings(
            provider=ProviderKind.OLLAMA,
            model="test-model",
            base_url="http://ollama.local/api",
            enabled=True,
        )
    )

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="ollama-rule-based-fallback-selfview",
                user_id="person-1",
                text="셀프뷰 켜줘",
                source=MessageSource.WEBEX,
            ),
            SessionContext(session_id="ollama-rule-based-fallback-selfview", turns=[]),
        )
    )

    assert len(llm_client.requests) == 1
    assert decision.action_proposal is not None
    assert decision.action_proposal.intent == Intent.SET_SELFVIEW
    assert decision.action_proposal.set_selfview is not None
    assert decision.action_proposal.set_selfview.enabled is True


def test_ollama_provider_falls_back_for_invalid_llm_korean_webex_join_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import SessionContext

    provider = OllamaProvider("demo-roomkit")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "message": {
                    "content": '{"action_proposal":{"intent":"webex_join","summary":"join"}}'
                }
            }

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, path: str, json: dict[str, object]) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient)

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="ollama-invalid-korean-webex-join",
                user_id="debug-user",
                text="25565427373 미팅번호로 미팅 참여",
                source=MessageSource.WEBEX,
            ),
            SessionContext(session_id="ollama-invalid-korean-webex-join", turns=[]),
        )
    )

    assert decision.pending_action is not None
    assert decision.pending_action.intent.value == "webex_join"
    assert decision.pending_action.meeting_identifier == "25565427373"
    assert decision.reply_text is None


def test_ollama_provider_falls_back_for_invalid_llm_korean_environment_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import SessionContext

    provider = OllamaProvider("demo-roomkit")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "message": {
                    "content": '{"action_proposal":{"intent":"get_environment_info","summary":"check environment"}}'
                }
            }

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, path: str, json: dict[str, object]) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient)

    decision = asyncio.run(
        provider.analyze_message(
            InboundUserMessage(
                session_id="ollama-invalid-korean-environment",
                user_id="debug-user",
                text="Room Bar 온도와 습도 확인해줘",
                source=MessageSource.WEBEX,
            ),
            SessionContext(session_id="ollama-invalid-korean-environment", turns=[]),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.get_environment_info is not None
    assert decision.action_proposal.get_environment_info.target_device == "Room Bar"
    assert decision.reply_text is None


def test_ollama_provider_accepts_semantic_korean_payloads_for_every_roomos_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        Intent,
        ProviderKind,
        ProviderSettings,
        SessionContext,
    )

    cases: list[tuple[str, str, dict[str, object]]] = [
        ("get_status", "룸바 상태 알려줘", {"target_device": "Room Bar", "include_metrics": True}),
        ("get_environment_info", "룸바 온도와 습도 알려줘", {"target_device": "Room Bar"}),
        ("get_camera_mode", "룸바 카메라 모드 알려줘", {"target_device": "Room Bar"}),
        ("get_room_booking", "룸바 다음 회의 예약 알려줘", {"target_device": "Room Bar"}),
        ("list_devices", "온라인 장비 목록 보여줘", {"limit": 10, "online_only": True}),
        (
            "webex_join",
            "룸바로 25565427373 회의 참가해줘",
            {"target_device": "Room Bar", "meeting_identifier": "25565427373"},
        ),
        ("join_obtp", "룸바 다음 예약 회의 참가해줘", {"target_device": "Room Bar"}),
        (
            "dial",
            "룸바에서 young@example.com으로 전화해줘",
            {"target_device": "Room Bar", "address": "young@example.com"},
        ),
        ("hang_up", "룸바 통화 종료해줘", {"target_device": "Room Bar", "call_id": None}),
        (
            "send_dtmf",
            "룸바에서 123# 톤 보내줘",
            {"target_device": "Room Bar", "tones": "123#", "call_id": None},
        ),
        (
            "set_microphone_mute",
            "룸바 마이크 음소거 해줘",
            {"target_device": "Room Bar", "muted": True},
        ),
        (
            "set_microphone_mode",
            "룸바 마이크 노이즈 제거 모드로 해줘",
            {"target_device": "Room Bar", "mode": "noise-reduction"},
        ),
        ("set_volume", "룸바 소리를 35로 맞춰줘", {"target_device": "Room Bar", "level": 35}),
        ("set_video_mute", "룸바 카메라 꺼줘", {"target_device": "Room Bar", "muted": True}),
        (
            "set_selfview",
            "룸바 화면에 내 모습 나오게 해줘",
            {"target_device": "Room Bar", "enabled": True},
        ),
        (
            "set_camera_mode",
            "룸바 카메라를 수동 모드로 바꿔줘",
            {"target_device": "Room Bar", "mode": "Manual"},
        ),
        (
            "set_layout",
            "룸바 레이아웃을 크게 보기로 바꿔줘",
            {"target_device": "Room Bar", "layout_name": "Prominent"},
        ),
        (
            "set_presentation",
            "룸바 화면 공유 시작해줘",
            {"target_device": "Room Bar", "enabled": True},
        ),
        (
            "switch_input_source",
            "룸바 입력 소스를 HDMI1로 바꿔줘",
            {"target_device": "Room Bar", "source_id": "HDMI1"},
        ),
        (
            "assign_matrix",
            "룸바 매트릭스 출력 1에 소스 2를 할당해줘",
            {
                "target_device": "Room Bar",
                "output": "1",
                "mode": "Replace",
                "layout": "Equal",
                "source_id": "2",
                "remote_main": None,
            },
        ),
        (
            "unassign_matrix",
            "룸바 매트릭스 출력 1 소스 2 해제해줘",
            {"target_device": "Room Bar", "output": "1", "source_id": "2", "remote_main": None},
        ),
        (
            "swap_matrix",
            "룸바 매트릭스 출력 1과 출력 2를 바꿔줘",
            {"target_device": "Room Bar", "output_a": "1", "output_b": "2"},
        ),
        (
            "set_display_mode",
            "룸바 디스플레이를 왼쪽 영상 오른쪽 발표 모드로 해줘",
            {"target_device": "Room Bar", "mode": "left-video-right-presentation"},
        ),
        (
            "set_display_role",
            "룸바 커넥터 2를 프레젠테이션 전용으로 설정해줘",
            {"target_device": "Room Bar", "connector_id": 2, "role": "presentation-only"},
        ),
        (
            "activate_camera_preset",
            "룸바 카메라 프리셋 3 실행해줘",
            {"target_device": "Room Bar", "preset_id": "3"},
        ),
        (
            "adjust_camera_position",
            "룸바 카메라 1을 왼쪽으로 조금 움직여줘",
            {
                "target_device": "Room Bar",
                "camera_id": "1",
                "pan": 1000,
                "tilt": None,
                "zoom": None,
            },
        ),
        (
            "set_speakertrack",
            "룸바 스피커트랙 켜줘",
            {"target_device": "Room Bar", "enabled": True},
        ),
        ("set_standby", "룸바 대기모드로 전환해줘", {"target_device": "Room Bar", "enabled": True}),
        ("reboot", "룸바 재부팅해줘", {"target_device": "Room Bar"}),
        (
            "factory_reset",
            "룸바 공장초기화 확인하고 진행해줘",
            {"target_device": "Room Bar", "acknowledged": True},
        ),
    ]

    for intent_value, user_text, payload in cases:
        llm_client = QueuedAsyncClient()
        llm_client.responses.append(
            make_response(
                "POST",
                "/chat",
                200,
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "reply_text": None,
                                "action_proposal": {
                                    "intent": intent_value,
                                    "summary": f"Semantic Korean request for {intent_value}.",
                                    "confidence": 0.95,
                                    intent_value: payload,
                                },
                            }
                        )
                    }
                },
            )
        )

        class FakeAsyncClient:
            _llm_client: QueuedAsyncClient = llm_client

            def __init__(self, *args: object, **kwargs: object) -> None:
                _ = args
                _ = kwargs

            async def __aenter__(self) -> QueuedAsyncClient:
                return self._llm_client

            async def __aexit__(
                self,
                exc_type: object,
                exc: object,
                tb: object,
            ) -> None:
                _ = exc_type
                _ = exc
                _ = tb

        monkeypatch.setattr("assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient)

        provider = OllamaProvider(default_target_device="__no_rule_based_default__")
        provider._fallback_provider.analyze_message = _no_rule_based_match  # type: ignore[method-assign]
        provider.bind_settings(
            ProviderSettings(
                provider=ProviderKind.OLLAMA,
                model="test-model",
                base_url="http://ollama.local/api",
                enabled=True,
            )
        )

        decision = asyncio.run(
            provider.analyze_message(
                InboundUserMessage(
                    session_id=f"semantic-korean-{intent_value}",
                    user_id="person-1",
                    text=user_text,
                    source=MessageSource.WEBEX,
                ),
                SessionContext(session_id=f"semantic-korean-{intent_value}", turns=[]),
            )
        )

        assert len(llm_client.requests) == 1
        assert decision.action_proposal is not None, user_text
        assert decision.action_proposal.intent == Intent(intent_value)


async def _no_rule_based_match(message: object, session: object) -> object:
    from shared.contracts import OrchestrationDecision

    _ = message
    _ = session
    return OrchestrationDecision(reply_text="no deterministic fallback")
