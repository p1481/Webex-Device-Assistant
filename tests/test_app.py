import asyncio
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from os import environ
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant_app.admin_auth import ADMIN_SESSION_COOKIE, _sign_session_id
from assistant_app.main import app, build_app
from assistant_app.state_store import FileBackedStateStore
from assistant_app.webex_gateway import WebexGateway
from shared.contracts import (
    AdminAuthSession,
    ApprovalDecision,
    InboundUserMessage,
    MessageSource,
    RuntimeAdminSettingsUpdate,
)
from tests.test_webex_integration import (
    QueuedAsyncClient,
    StaticTokenProvider,
    async_client_factory,
    build_client_queue,
    make_response,
)


def build_authenticated_client(app_instance: FastAPI | None = None) -> TestClient:
    scoped_app = app_instance or build_app()
    scoped_client = TestClient(scoped_app)
    session_id = f"test-admin-session-{uuid4()}"
    email = scoped_app.state.services.admin_service.get_runtime_admin_settings().default_user_email
    auth_session = scoped_app.state.services.admin_service.create_admin_auth_session(
        AdminAuthSession(
            session_id=session_id,
            email=email,
            approval_request_id="",
            approved=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            approved_at=datetime.now(UTC),
        )
    )
    approval_request = (
        scoped_app.state.services.approval_manager.create_admin_auth_request(
            InboundUserMessage(
                session_id=f"admin-auth:{session_id}",
                user_id=email,
                person_email=email,
                text="admin login",
                source=MessageSource.WEBEX,
                room_id=None,
            ),
            admin_session_id=session_id,
        )
    )
    auth_session.approval_request_id = approval_request.request_id
    _ = scoped_app.state.services.admin_service.update_admin_auth_session(auth_session)
    resolved = scoped_app.state.services.approval_manager.approve_or_reject(
        ApprovalDecision(
            request_id=approval_request.request_id,
            approved=True,
            decided_by="person-1",
            decided_by_email=email,
            admin_session_id=session_id,
        )
    )
    assert resolved is not None
    cookie_secret = (
        getattr(scoped_app.state.services.config, "admin_cookie_secret", None)
        or scoped_app.state.services.config.webex_webhook_secret
        or "device-assistant-dev-admin-cookie-secret"
    )
    scoped_client.cookies.set(
        ADMIN_SESSION_COOKIE,
        _sign_session_id(session_id, cookie_secret),
    )
    return scoped_client


def build_unauthenticated_client(app_instance: FastAPI | None = None) -> TestClient:
    scoped_app = app_instance or build_app()
    return TestClient(scoped_app)


client = build_authenticated_client(app)


@contextmanager
def temporary_env(updates: dict[str, str | None]) -> Iterator[None]:
    original = {key: environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                _ = environ.pop(key, None)
            else:
                environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                _ = environ.pop(key, None)
            else:
                environ[key] = value


def as_mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def as_sequence(value: object) -> Sequence[object]:
    assert isinstance(value, list)
    return cast(list[object], value)


def test_healthz_exposes_mock_modes() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    assert body["status"] == "ok"


def test_debug_get_status_in_separated_mode() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "get status of RoomKit-7F", "preferred_mode": "separated"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "RoomKit-7F" in text
    assert "separated mode" in text
    assert "volume_muted=false" in text.lower()
    assert "software_display_name=RoomOS 11.0" in text
    assert reply["markdown"] is None


def test_debug_get_status_in_all_llm_mode() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "get status of Desk Pro", "preferred_mode": "all-llm"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Desk Pro" in text
    assert "all-LLM mode" in text
    assert "product_platform=RoomOS" in text
    assert "selfview_mode=Off" in text


def test_orchestrator_get_status_reply_includes_new_non_null_fields_and_omits_nulls() -> (
    None
):
    from assistant_app.orchestrator import Orchestrator
    from shared.contracts import (
        DeviceStatusSnapshot,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        Intent,
    )

    orchestrator = Orchestrator.__new__(Orchestrator)

    text = orchestrator._format_execution_result(
        ExecutionResult(
            request_id="req-status-rich",
            intent=Intent.GET_STATUS,
            execution_mode=ExecutionMode.ALL_LLM,
            status=ExecutionStatus.SUCCESS,
            message="Collected status from Board Pro via all-LLM mode.",
            device_status=DeviceStatusSnapshot(
                target_device="Board Pro",
                source="webex-cloud-xapi",
                display_name="Board Pro",
                online=True,
                product="Cisco Board Pro",
                product_platform="RoomOS",
                volume=55,
                volume_muted=False,
                software_display_name="RoomOS March 2026",
                speakertrack_state="Active",
                presentertrack_status=None,
                wifi_status=None,
            ),
        ),
        "Read-only device status can run in either mode for the MVP.",
    )

    assert "product_platform=RoomOS" in text
    assert "software_display_name=RoomOS March 2026" in text
    assert "speakertrack_state=Active" in text
    assert "volume_muted=False" in text
    assert "presentertrack_status=" not in text
    assert "wifi_status=" not in text
    assert "=None" not in text


def test_debug_get_environment_info_in_separated_mode() -> None:
    response = client.post(
        "/debug/messages",
        json={
            "text": "get environment info of RoomKit-7F",
            "preferred_mode": "separated",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "RoomKit-7F" in text
    assert "environment info" in text.lower()
    assert "separated mode" in text


def test_debug_get_environment_info_in_all_llm_mode() -> None:
    response = client.post(
        "/debug/messages",
        json={
            "text": "what is the temperature and humidity on Desk Pro",
            "preferred_mode": "all-llm",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Desk Pro" in text
    assert "environment info" in text.lower()
    assert "all-LLM mode" in text


def test_debug_get_camera_mode_in_separated_mode() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "get camera mode of RoomKit-7F", "preferred_mode": "separated"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "RoomKit-7F" in text
    assert "camera mode" in text.lower()
    assert "separated mode" in text


def test_debug_get_room_booking_in_separated_mode() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "show booking info on RoomKit-7F", "preferred_mode": "separated"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "RoomKit-7F" in text
    assert "booking" in text.lower()
    assert "separated mode" in text
    assert "None" not in text


def test_debug_get_room_booking_in_all_llm_mode() -> None:
    response = client.post(
        "/debug/messages",
        json={
            "text": "is obtp available on Desk Pro",
            "preferred_mode": "all-llm",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Desk Pro" in text
    assert "booking" in text.lower()
    assert "all-LLM mode" in text
    assert "None" not in text


def test_set_camera_mode_executes_without_approval() -> None:
    response = client.post(
        "/debug/messages",
        json={
            "text": "set camera mode to frames on Board Pro",
            "session_id": "camera-mode-direct-case",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Approval required" not in text
    assert "Mock camera mode set to Frames" in text


def test_join_obtp_creates_approval_reply() -> None:
    response = client.post(
        "/debug/messages",
        json={
            "text": "join obtp on Board Pro",
            "session_id": "join-obtp-approval-case",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    attachments = as_sequence(reply["attachments"])
    assert isinstance(text, str)
    assert "Approval required" in text
    assert len(attachments) == 1


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
    monkeypatch.setattr(
        "assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient
    )
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
    monkeypatch.setattr(
        "assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient
    )
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
        room_booking_status = as_mapping(
            execution_result_payload["room_booking_status"]
        )
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
    monkeypatch.setattr(
        "assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient
    )
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

def test_orchestrator_returns_markdown_when_provider_renders_it() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.config import AppConfig
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from device_executor.device_client import DeviceClient
    from device_executor.executor import DeviceExecutor
    from device_executor.handlers import ExecutionHandlers
    from direct_tool_adapter.adapter import DirectToolAdapter
    from direct_tool_adapter.tools import DirectToolSet
    from shared.contracts import (
        ActionProposal,
        DeviceStatusSnapshot,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        GetStatusParams,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        PolicyDecision,
        ProviderSettings,
        SessionContext,
    )

    class FakeProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_STATUS,
                    summary="Get the current device status.",
                    get_status=GetStatusParams(
                        target_device="Home Office",
                        include_metrics=True,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return "### 상태 요약\n- Home Office는 온라인입니다."

    class FakeModeRouter(ModeRouter):
        def __init__(self) -> None:
            super().__init__(
                device_executor=DeviceExecutor(
                    ExecutionHandlers(DeviceClient(AppConfig(), StaticTokenProvider()))
                ),
                direct_tool_adapter=DirectToolAdapter(
                    DirectToolSet(DeviceClient(AppConfig(), StaticTokenProvider()))
                ),
            )

        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = proposal
            _ = policy_decision
            return ExecutionResult(
                request_id="req-1",
                intent=Intent.GET_STATUS,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Collected status from Home Office via all-LLM mode.",
                device_status=DeviceStatusSnapshot(
                    target_device="Home Office",
                    source="webex-cloud-xapi",
                    display_name="Home Office",
                    product="Cisco Desk Pro",
                    online=True,
                    connection_status="connected",
                ),
            )

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())

    orchestrator = Orchestrator(
        FakeProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        FakeModeRouter(),
        approval_manager,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="render-markdown",
                user_id="debug-user",
                text="Home Office 상태 확인해줘",
                source=MessageSource.DEBUG,
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert "Collected status from Home Office via all-LLM mode." in reply.text
    assert reply.markdown == "### 상태 요약\n- Home Office는 온라인입니다."


def test_debug_list_devices_returns_inventory_reply() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "디바이스 리스트 보여줘", "session_id": "device-list-case"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "디바이스 목록" in text


def test_debug_list_devices_reports_clean_token_manager_failure_without_raw_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://127.0.0.1:3000",
            "WEBEX_BOT_TOKEN": None,
        }
    ):
        scoped_client = build_authenticated_client()
        token_client = QueuedAsyncClient()
        token_client.responses.append(
            httpx.Response(
                500,
                json={"detail": "token service unavailable"},
                request=httpx.Request(
                    "GET", "http://127.0.0.1:3000/api/tokens/current"
                ),
            )
        )
        _ = build_client_queue(token_client)
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "장비 리스트",
                "session_id": "device-list-token-manager-failure",
                "preferred_mode": "separated",
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Execution failed: Failed to retrieve a Webex access token" in text
    assert "500 Internal Server Error" not in text


def test_debug_same_session_hi_still_gets_reply() -> None:
    first_response = client.post(
        "/debug/messages",
        json={"text": "디바이스 목록 보여줘", "session_id": "same-session-hi"},
    )
    assert first_response.status_code == 200

    followup_response = client.post(
        "/debug/messages",
        json={"text": "hi", "session_id": "same-session-hi"},
    )
    assert followup_response.status_code == 200
    payload = cast(object, followup_response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert text.strip()


def test_debug_same_session_unsupported_korean_followup_still_gets_reply() -> None:
    first_response = client.post(
        "/debug/messages",
        json={"text": "디바이스 목록 보여줘", "session_id": "same-session-ko-followup"},
    )
    assert first_response.status_code == 200

    followup_response = client.post(
        "/debug/messages",
        json={
            "text": "Down 되어있는 디바이스도 있어?",
            "session_id": "same-session-ko-followup",
        },
    )
    assert followup_response.status_code == 200
    payload = cast(object, followup_response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert text.strip()


def test_reset_command_clears_session() -> None:
    response = client.post(
        "/debug/messages", json={"text": "/reset", "session_id": "reset-case"}
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "cleared the session context" in text


def test_set_volume_executes_without_approval() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "set volume to 35 on Board Pro", "session_id": "volume-direct-case"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Approval required" not in text
    assert "Mock volume set to 35" in text


def test_debug_mutating_command_success_is_not_rendered_as_failure() -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/set_microphone_mute",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct mute execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "mute microphone on Board Pro",
            "session_id": "approved-mic-case-run",
            "preferred_mode": "all-llm",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "microphones" in text.lower()
    assert "muted" in text.lower()
    assert "Execution failed" not in text


def test_debug_korean_targeted_mute_success_is_not_rendered_as_failure() -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/set_microphone_mute",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct Korean mute execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "Codec Pro G2 음소거 해줘",
            "session_id": "approved-korean-mic-case-run",
            "preferred_mode": "all-llm",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "invalid action payload" not in text.lower()
    assert "execution failed" not in text.lower()
    assert "codec pro g2" in text.lower()
    assert "mute" in text.lower()


def test_debug_microphone_mode_change_success_is_not_rendered_as_failure() -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/set_microphone_mode",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct microphone mode execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "microphone mode music mode on Board Pro",
            "session_id": "mic-mode-case-run",
            "preferred_mode": "all-llm",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "music-mode" in text.lower() or "music mode" in text.lower()
    assert "Execution failed" not in text


def test_debug_display_mode_change_success_is_not_rendered_as_failure() -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/set_display_mode",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct display mode execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "display mode dual on Board Pro",
            "session_id": "display-mode-case-run",
            "preferred_mode": "all-llm",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "display mode" in text.lower()
    assert "Execution failed" not in text


def test_debug_display_mode_phrase_without_display_mode_keywords_is_parsed() -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/set_display_mode",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct display mode execution in terse phrase test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "Codec Pro G2 Dual-presentation-only",
            "session_id": "display-mode-terse-phrase-run",
            "preferred_mode": "all-llm",
            "target_device": "Codec Pro G2",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "display mode" in text.lower()
    assert "invalid action payload" not in text.lower()
    assert "Execution failed" not in text


def test_debug_display_role_change_success_is_not_rendered_as_failure() -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/set_display_role",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct display role execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "display role connector 2 presentation only on Board Pro",
            "session_id": "display-role-case-run",
            "preferred_mode": "all-llm",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "connector 2" in text.lower()
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_set_camera_mode_success_is_not_rendered_as_failure(
    preferred_mode: str,
) -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/set_camera_mode",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct camera mode execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "set camera mode to frames on Board Pro",
            "session_id": f"camera-mode-case-{preferred_mode}",
            "preferred_mode": preferred_mode,
        },
    )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "camera mode" in text.lower()
    assert "frames" in text.lower()
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_microphone_mode_exact_supported_values_are_surfaced_in_both_modes(
    monkeypatch: pytest.MonkeyPatch,
    preferred_mode: str,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        scoped_client = build_authenticated_client()
        policy_response = scoped_client.put(
            "/admin/policies/set_microphone_mode",
            json={
                "allowed_modes": ["separated", "all-llm"],
                "risk_level": "low",
                "approval_state": "not_required",
                "reason": "Allow direct microphone mode execution in debug flow test.",
            },
        )
        assert policy_response.status_code == 200

        api_client = QueuedAsyncClient()
        api_client.responses.append(
            make_response(
                "GET",
                "/devices",
                200,
                {"items": [{"id": "device-1", "displayName": "Board Pro"}]},
            )
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/deviceConfigurations",
                200,
                {
                    "items": [
                        {
                            "key": "Audio.Input.MicrophoneMode",
                            "valueSpace": {"enum": ["Focused", "Wide"]},
                        }
                    ]
                },
            )
        )
        config_client = QueuedAsyncClient()
        config_client.responses.append(
            make_response("PATCH", "/deviceConfigurations", 200, [])
        )
        token_client_one = QueuedAsyncClient()
        token_client_one.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_two = QueuedAsyncClient()
        token_client_two.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_three = QueuedAsyncClient()
        token_client_three.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        _ = build_client_queue(
            api_client,
            token_client_one,
            token_client_two,
            config_client,
            token_client_three,
        )
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "microphone mode voice optimized on Board Pro",
                "session_id": f"mic-guidance-{preferred_mode}",
                "preferred_mode": preferred_mode,
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Set microphone mode to voice optimized on Board Pro." in text
    assert (
        "Exact configurable microphone mode values reported by Webex: Focused, Wide."
        in text
    )
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_layout_reply_includes_current_layout_and_best_effort_candidates_in_both_modes(
    monkeypatch: pytest.MonkeyPatch,
    preferred_mode: str,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        scoped_client = build_authenticated_client()
        policy_response = scoped_client.put(
            "/admin/policies/set_layout",
            json={
                "allowed_modes": ["separated", "all-llm"],
                "risk_level": "low",
                "approval_state": "not_required",
                "reason": "Allow direct layout execution in debug flow test.",
            },
        )
        assert policy_response.status_code == 200

        api_client = QueuedAsyncClient()
        api_client.responses.append(
            make_response(
                "GET",
                "/devices",
                200,
                {"items": [{"id": "device-1", "displayName": "Board Pro"}]},
            )
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/xapi/status",
                200,
                {"Video": {"Layout": {"CurrentLayout": "Equal"}}},
            )
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/xapi/status",
                200,
                {"Video": {"Layout": {"LayoutFamily": {"Local": "Prominent"}}}},
            )
        )
        command_client = QueuedAsyncClient()
        command_client.responses.append(
            make_response(
                "POST", "/xapi/command/Video.Layout.SetLayout", 200, {"status": "ok"}
            )
        )
        token_client_one = QueuedAsyncClient()
        token_client_one.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_two = QueuedAsyncClient()
        token_client_two.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_three = QueuedAsyncClient()
        token_client_three.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_four = QueuedAsyncClient()
        token_client_four.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        _ = build_client_queue(
            api_client,
            token_client_one,
            token_client_two,
            token_client_three,
            command_client,
            token_client_four,
        )
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "layout prominent on Board Pro",
                "session_id": f"layout-guidance-{preferred_mode}",
                "preferred_mode": preferred_mode,
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Set layout to Prominent on Board Pro." in text
    assert "Current layout reported by Webex before the change: Equal." in text
    assert (
        "Documented candidate layouts (best-effort guidance, not device-reported support): Equal, Overlay, Prominent, Single, SpeakerOnly."
        in text
    )
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_get_camera_mode_reports_effective_and_available_modes_in_both_modes(
    monkeypatch: pytest.MonkeyPatch,
    preferred_mode: str,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        scoped_client = build_authenticated_client()
        api_client = QueuedAsyncClient()
        api_client.responses.append(
            make_response(
                "GET",
                "/devices",
                200,
                {"items": [{"id": "device-1", "displayName": "Board Pro"}]},
            )
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/xapi/status",
                200,
                {
                    "Cameras": {
                        "SpeakerTrack": {
                            "Availability": "Available",
                            "State": "Active",
                            "Closeup": {"Status": "Inactive"},
                            "Frames": {
                                "Availability": "Available",
                                "Status": "Active",
                            },
                        },
                        "PresenterTrack": {
                            "Availability": "Available",
                            "Status": "Inactive",
                        },
                    }
                },
            )
        )
        api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
        token_client_one = QueuedAsyncClient()
        token_client_one.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_two = QueuedAsyncClient()
        token_client_two.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_three = QueuedAsyncClient()
        token_client_three.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        _ = build_client_queue(
            api_client,
            token_client_one,
            token_client_two,
            token_client_three,
        )
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "get camera mode of Board Pro",
                "session_id": f"camera-mode-query-{preferred_mode}",
                "preferred_mode": preferred_mode,
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Collected camera mode from Board Pro" in text
    assert "current_mode=frames" in text
    assert "effective_mode=frames" in text
    assert "available_modes=best_overview,speaker_closeup,frames" in text
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_switch_input_source_alias_executes_in_both_modes(
    monkeypatch: pytest.MonkeyPatch,
    preferred_mode: str,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        scoped_client = build_authenticated_client()
        policy_response = scoped_client.put(
            "/admin/policies/switch_input_source",
            json={
                "allowed_modes": ["separated", "all-llm"],
                "risk_level": "low",
                "approval_state": "not_required",
                "reason": "Allow direct input source execution in debug flow test.",
            },
        )
        assert policy_response.status_code == 200

        resolve_client = QueuedAsyncClient()
        resolve_client.responses.append(
            make_response(
                "GET",
                "/devices",
                200,
                {"items": [{"id": "device-1", "displayName": "Board Pro"}]},
            )
        )
        command_client = QueuedAsyncClient()
        command_client.responses.append(
            make_response(
                "POST",
                "/xapi/command/Video.Input.SetMainVideoSource",
                200,
                {"status": "ok"},
            )
        )
        token_client_one = QueuedAsyncClient()
        token_client_one.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_two = QueuedAsyncClient()
        token_client_two.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        _ = build_client_queue(
            resolve_client,
            token_client_one,
            command_client,
            token_client_two,
        )
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "switch input source to pc on Board Pro",
                "session_id": f"input-source-alias-{preferred_mode}",
                "preferred_mode": preferred_mode,
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Switched input source to pc on Board Pro." in text
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_matrix_assign_executes_in_both_modes(preferred_mode: str) -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/assign_matrix",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct matrix assign execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "matrix assign output HDMI1 mode Replace layout Equal source 3 on Board Pro",
            "session_id": f"matrix-assign-case-{preferred_mode}",
            "preferred_mode": preferred_mode,
        },
    )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Mock video matrix assign requested for output HDMI1 on Board Pro." in text
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_matrix_unassign_executes_in_both_modes(preferred_mode: str) -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/unassign_matrix",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct matrix unassign execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "matrix unassign output HDMI1 source 3 on Board Pro",
            "session_id": f"matrix-unassign-case-{preferred_mode}",
            "preferred_mode": preferred_mode,
        },
    )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Mock video matrix unassign requested for output HDMI1 on Board Pro." in text
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_matrix_swap_executes_in_both_modes(preferred_mode: str) -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/swap_matrix",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct matrix swap execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "matrix swap output HDMI1 with output HDMI2 on Board Pro",
            "session_id": f"matrix-swap-case-{preferred_mode}",
            "preferred_mode": preferred_mode,
        },
    )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert (
        "Mock video matrix swap requested for outputs HDMI1 and HDMI2 on Board Pro."
        in text
    )
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_adjust_camera_position_executes_in_both_modes(
    preferred_mode: str,
) -> None:
    scoped_client = build_authenticated_client()
    policy_response = scoped_client.put(
        "/admin/policies/adjust_camera_position",
        json={
            "allowed_modes": ["separated", "all-llm"],
            "risk_level": "low",
            "approval_state": "not_required",
            "reason": "Allow direct camera position execution in debug flow test.",
        },
    )
    assert policy_response.status_code == 200

    response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "camera 2 left on Board Pro",
            "session_id": f"camera-position-case-{preferred_mode}",
            "preferred_mode": preferred_mode,
        },
    )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Moved camera 2 left on Board Pro." in text
    assert "Execution failed" not in text


def test_matrix_assign_without_target_asks_follow_up_then_resumes() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "matrix assign output HDMI1 mode Replace layout Equal source 3",
            "session_id": "matrix-assign-target-followup",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "Which device should I use?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={"text": "Board Pro", "session_id": "matrix-assign-target-followup"},
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "matrix-assign-target-followup"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    assign_matrix = as_mapping(execution_request["assign_matrix"])

    assert assign_matrix["target_device"] == "Board Pro"
    assert assign_matrix["output"] == "HDMI1"
    assert assign_matrix["mode"] == "Replace"
    assert assign_matrix["layout"] == "Equal"
    assert assign_matrix["source_id"] == "3"


def test_adjust_camera_position_without_target_asks_follow_up_then_resumes() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "camera 2 zoom in",
            "session_id": "camera-position-target-followup",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "Which device should I use?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={"text": "Board Pro", "session_id": "camera-position-target-followup"},
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "camera-position-target-followup"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    adjust_camera_position = as_mapping(execution_request["adjust_camera_position"])

    assert adjust_camera_position["target_device"] == "Board Pro"
    assert adjust_camera_position["camera_id"] == "2"
    assert adjust_camera_position["pan"] is None
    assert adjust_camera_position["tilt"] is None
    assert adjust_camera_position["zoom"] == -700


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_make_layout_prominent_executes_in_both_modes(
    monkeypatch: pytest.MonkeyPatch,
    preferred_mode: str,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        scoped_client = build_authenticated_client()
        policy_response = scoped_client.put(
            "/admin/policies/set_layout",
            json={
                "allowed_modes": ["separated", "all-llm"],
                "risk_level": "low",
                "approval_state": "not_required",
                "reason": "Allow direct layout execution in debug flow test.",
            },
        )
        assert policy_response.status_code == 200

        api_client = QueuedAsyncClient()
        api_client.responses.append(
            make_response(
                "GET",
                "/devices",
                200,
                {"items": [{"id": "device-1", "displayName": "Board Pro"}]},
            )
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/xapi/status",
                200,
                {"Video": {"Layout": {"CurrentLayout": "Equal"}}},
            )
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/xapi/status",
                200,
                {"Video": {"Layout": {"LayoutFamily": {"Local": "Prominent"}}}},
            )
        )
        command_client = QueuedAsyncClient()
        command_client.responses.append(
            make_response(
                "POST", "/xapi/command/Video.Layout.SetLayout", 200, {"status": "ok"}
            )
        )
        token_client_one = QueuedAsyncClient()
        token_client_one.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_two = QueuedAsyncClient()
        token_client_two.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_three = QueuedAsyncClient()
        token_client_three.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_four = QueuedAsyncClient()
        token_client_four.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        _ = build_client_queue(
            api_client,
            token_client_one,
            token_client_two,
            token_client_three,
            command_client,
            token_client_four,
        )
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "make layout prominent on Board Pro",
                "session_id": f"layout-prominent-natural-{preferred_mode}",
                "preferred_mode": preferred_mode,
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Set layout to Prominent on Board Pro." in text
    assert "Current layout reported by Webex before the change: Equal." in text
    assert "Execution failed" not in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_microphone_mode_unsupported_exact_values_fail_before_mutation_in_both_modes(
    monkeypatch: pytest.MonkeyPatch,
    preferred_mode: str,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        scoped_client = build_authenticated_client()
        policy_response = scoped_client.put(
            "/admin/policies/set_microphone_mode",
            json={
                "allowed_modes": ["separated", "all-llm"],
                "risk_level": "low",
                "approval_state": "not_required",
                "reason": "Allow direct microphone mode execution in debug flow test.",
            },
        )
        assert policy_response.status_code == 200

        api_client = QueuedAsyncClient()
        api_client.responses.append(
            make_response(
                "GET",
                "/devices",
                200,
                {"items": [{"id": "device-1", "displayName": "Board Pro"}]},
            )
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/deviceConfigurations",
                200,
                {
                    "items": [
                        {
                            "key": "Audio.Input.MicrophoneMode",
                            "valueSpace": {"enum": ["Wide"]},
                        }
                    ]
                },
            )
        )
        token_client_one = QueuedAsyncClient()
        token_client_one.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_two = QueuedAsyncClient()
        token_client_two.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        _ = build_client_queue(api_client, token_client_one, token_client_two)
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "microphone mode voice optimized on Board Pro",
                "session_id": f"mic-guidance-unsupported-{preferred_mode}",
                "preferred_mode": preferred_mode,
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert text.startswith(
        "Execution failed: Cannot set microphone mode to voice optimized on Board Pro"
    )
    assert "Webex reports configurable microphone values: Wide." in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_set_camera_mode_rejects_presentertrack_before_mutation_in_both_modes(
    monkeypatch: pytest.MonkeyPatch,
    preferred_mode: str,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        scoped_client = build_authenticated_client()
        policy_response = scoped_client.put(
            "/admin/policies/set_camera_mode",
            json={
                "allowed_modes": ["separated", "all-llm"],
                "risk_level": "low",
                "approval_state": "not_required",
                "reason": "Allow direct camera mode execution in debug flow test.",
            },
        )
        assert policy_response.status_code == 200

        api_client = QueuedAsyncClient()
        api_client.responses.append(
            make_response(
                "GET",
                "/devices",
                200,
                {"items": [{"id": "device-1", "displayName": "Board Pro"}]},
            )
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/xapi/status",
                200,
                {
                    "Cameras": {
                        "SpeakerTrack": {
                            "Availability": "Available",
                            "State": "Active",
                            "Closeup": {"Status": "Inactive"},
                            "Frames": {
                                "Availability": "Available",
                                "Status": "Inactive",
                            },
                        },
                        "PresenterTrack": {
                            "Availability": "Available",
                            "Status": "Active",
                        },
                    }
                },
            )
        )
        api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
        token_client_one = QueuedAsyncClient()
        token_client_one.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_two = QueuedAsyncClient()
        token_client_two.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_three = QueuedAsyncClient()
        token_client_three.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        _ = build_client_queue(
            api_client,
            token_client_one,
            token_client_two,
            token_client_three,
        )
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "set camera mode to frames on Board Pro",
                "session_id": f"camera-mode-reject-{preferred_mode}",
                "preferred_mode": preferred_mode,
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert text.startswith(
        "Set camera mode to Frames on Board Pro (Cameras.SpeakerTrack.Set Behavior: Frames)."
    )


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_device_resolution_failure_suggests_candidate_devices(
    monkeypatch: pytest.MonkeyPatch,
    preferred_mode: str,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        scoped_client = build_authenticated_client()
        api_client = QueuedAsyncClient()
        api_client.responses.append(
            make_response("GET", "/devices", 200, {"items": []})
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/devices",
                200,
                {
                    "items": [
                        {
                            "id": "device-1",
                            "displayName": "Board Pro 1",
                            "product": "Cisco Board Pro",
                            "connectionStatus": "connected",
                        },
                        {
                            "id": "device-2",
                            "displayName": "Board Pro 2",
                            "product": "Cisco Board Pro",
                            "connectionStatus": "disconnected",
                        },
                    ]
                },
            )
        )
        token_client_one = QueuedAsyncClient()
        token_client_one.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_two = QueuedAsyncClient()
        token_client_two.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        _ = build_client_queue(api_client, token_client_one, token_client_two)
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "get status of Board Pro",
                "preferred_mode": preferred_mode,
                "session_id": f"device-suggestion-{preferred_mode}",
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Board Pro" in text
    assert "Board Pro 1" in text
    assert "Board Pro 2" in text
    assert "Execution failed" not in text


def test_ollama_parser_accepts_flat_action_payload_shape() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import InboundUserMessage, MessageSource

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
    from shared.contracts import InboundUserMessage, MessageSource

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
    from shared.contracts import InboundUserMessage, MessageSource

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
    from shared.contracts import InboundUserMessage, MessageSource

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
    from shared.contracts import InboundUserMessage, MessageSource

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
    from shared.contracts import InboundUserMessage, MessageSource

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
    from shared.contracts import InboundUserMessage, MessageSource

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


def test_rule_based_provider_understands_korean_dial_request() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
        InboundUserMessage,
        Intent,
        MessageSource,
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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
        InboundUserMessage,
        Intent,
        MessageSource,
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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
            SessionContext(
                session_id="display-mode-rule-based-presentation-only", turns=[]
            ),
        )
    )

    assert decision.action_proposal is not None
    assert decision.action_proposal.intent.value == "set_display_mode"
    assert decision.action_proposal.set_display_mode is not None
    assert (
        decision.action_proposal.set_display_mode.mode.value
        == "left-video-right-presentation"
    )
    assert decision.action_proposal.set_display_mode.target_device == "Codec Pro G2"


def test_rule_based_provider_understands_get_environment_info_command() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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


def test_debug_approval_executes_pending_action() -> None:
    request_response = client.post(
        "/debug/messages",
        json={
            "text": "dial youngcle@cisco.com on Board Pro",
            "session_id": "approval-exec-case",
        },
    )
    assert request_response.status_code == 200
    request_payload = cast(object, request_response.json())
    request_body = as_mapping(request_payload)
    request_reply = as_mapping(request_body["reply"])
    request_text = request_reply["text"]
    assert isinstance(request_text, str)
    assert "Approval required" in request_text

    approvals_response = client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "approval-exec-case"
    )
    request_id = as_mapping(pending)["request_id"]
    assert isinstance(request_id, str)

    approve_response = client.post(f"/debug/approvals/{request_id}?approved=true")
    assert approve_response.status_code == 200
    approve_payload = cast(object, approve_response.json())
    approve_body = as_mapping(approve_payload)
    approval = as_mapping(approve_body["approval"])
    reply = as_mapping(approve_body["reply"])
    text = reply["text"]

    assert approval["status"] == "executed"
    assert isinstance(text, str)
    assert "Mock dial requested" in text


def test_dial_without_target_asks_follow_up_after_address() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "dial youngcle@cisco.com", "session_id": "dial-followup-case"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]

    assert isinstance(text, str)
    assert text == "Which device should I use?"

    approvals_response = client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(
        as_mapping(approval)["session_id"] == "dial-followup-case"
        for approval in approvals
    )


def test_set_volume_without_target_asks_follow_up_after_level() -> None:
    scoped_client = build_authenticated_client()

    response = scoped_client.post(
        "/debug/messages",
        json={"text": "set volume to 35", "session_id": "volume-target-followup"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]

    assert isinstance(text, str)
    assert text == "Which device should I use?"

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(
        as_mapping(approval)["session_id"] == "volume-target-followup"
        for approval in approvals
    )


def test_webex_join_approval_flow_uses_policy_reason() -> None:
    scoped_client = build_authenticated_client()

    request_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join 987654321 on Board Pro",
            "session_id": "webex-approval-reason",
        },
    )
    assert request_response.status_code == 200

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "webex-approval-reason"
    )
    pending_approval = as_mapping(pending)
    execution_request = as_mapping(pending_approval["execution_request"])
    request_id = pending_approval["request_id"]

    assert execution_request["reason"] == (
        "Meeting joins are mutating actions and should require explicit approval."
    )
    assert isinstance(request_id, str)

    approve_response = scoped_client.post(
        f"/debug/approvals/{request_id}?approved=true"
    )
    assert approve_response.status_code == 200
    approve_payload = cast(object, approve_response.json())
    approve_body = as_mapping(approve_payload)
    reply = as_mapping(approve_body["reply"])
    text = reply["text"]

    assert isinstance(text, str)
    assert (
        "Policy: Meeting joins are mutating actions and should require explicit approval."
        in text
    )


def test_join_obtp_approval_flow_uses_policy_reason() -> None:
    scoped_client = build_authenticated_client()

    request_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "join obtp on Board Pro",
            "session_id": "join-obtp-approval-reason",
        },
    )
    assert request_response.status_code == 200

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "join-obtp-approval-reason"
    )
    pending_approval = as_mapping(pending)
    execution_request = as_mapping(pending_approval["execution_request"])
    request_id = pending_approval["request_id"]

    assert execution_request["reason"] == (
        "Scheduled meeting joins are mutating actions and should require explicit approval."
    )
    assert isinstance(request_id, str)

    approve_response = scoped_client.post(
        f"/debug/approvals/{request_id}?approved=true"
    )
    assert approve_response.status_code == 200
    approve_payload = cast(object, approve_response.json())
    approve_body = as_mapping(approve_payload)
    reply = as_mapping(approve_body["reply"])
    text = reply["text"]

    assert isinstance(text, str)
    assert (
        "Policy: Scheduled meeting joins are mutating actions and should require explicit approval."
        in text
    )


def test_missing_webex_join_params_ask_follow_up_then_resume() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "followup-webex-join",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "What Webex meeting ID or address should I join?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={"text": "987654321", "session_id": "followup-webex-join"},
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "followup-webex-join"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])

    assert webex_join["meeting_identifier"] == "987654321"
    assert webex_join["target_device"] == "Board Pro"


def test_missing_volume_level_asks_follow_up_then_resume() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "set volume on Board Pro",
            "session_id": "followup-volume",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "What volume level should I set (0-100)?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={"text": "35", "session_id": "followup-volume"},
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" not in second_text
    assert "Mock volume set to 35" in second_text
    assert "Board Pro" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    matching = [
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "followup-volume"
    ]
    assert matching == []


def test_ollama_fallback_preserves_pending_follow_up() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        InboundUserMessage,
        Intent,
        MessageSource,
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
    monkeypatch.setattr(
        "assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient
    )
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
        InboundUserMessage,
        Intent,
        MessageSource,
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
    monkeypatch.setattr(
        "assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient
    )
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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    monkeypatch.setattr(
        "assistant_app.providers.ollama.OLLAMA_ASYNC_CLIENT", FakeAsyncClient
    )
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


def test_reset_clears_pending_follow_up() -> None:
    scoped_client = build_authenticated_client()

    initial_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "followup-reset",
        },
    )
    assert initial_response.status_code == 200

    reset_response = scoped_client.post(
        "/debug/messages",
        json={"text": "/reset", "session_id": "followup-reset"},
    )
    assert reset_response.status_code == 200
    reset_payload = cast(object, reset_response.json())
    reset_body = as_mapping(reset_payload)
    reset_reply = as_mapping(reset_body["reply"])
    reset_text = reset_reply["text"]

    assert isinstance(reset_text, str)
    assert "cleared the session context" in reset_text

    post_reset_response = scoped_client.post(
        "/debug/messages",
        json={"text": "987654321", "session_id": "followup-reset"},
    )
    assert post_reset_response.status_code == 200
    post_reset_payload = cast(object, post_reset_response.json())
    post_reset_body = as_mapping(post_reset_payload)
    post_reset_reply = as_mapping(post_reset_body["reply"])
    post_reset_text = post_reset_reply["text"]

    assert isinstance(post_reset_text, str)
    assert "Approval required" not in post_reset_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(
        as_mapping(approval)["session_id"] == "followup-reset" for approval in approvals
    )


def test_shared_room_follow_up_is_scoped_to_actor() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "shared-room-followup",
            "room_id": "shared-room-followup",
            "user_id": "user-a",
        },
    )
    assert first_response.status_code == 200
    first_payload = cast(object, first_response.json())
    first_body = as_mapping(first_payload)
    first_reply = as_mapping(first_body["reply"])
    first_text = first_reply["text"]

    assert isinstance(first_text, str)
    assert first_text == "What Webex meeting ID or address should I join?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "987654321",
            "session_id": "shared-room-followup",
            "room_id": "shared-room-followup",
            "user_id": "user-b",
        },
    )
    assert second_response.status_code == 200
    second_payload = cast(object, second_response.json())
    second_body = as_mapping(second_payload)
    second_reply = as_mapping(second_body["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" not in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(
        as_mapping(approval)["session_id"] == "shared-room-followup"
        for approval in approvals
    )

    third_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "987654321",
            "session_id": "shared-room-followup",
            "room_id": "shared-room-followup",
            "user_id": "user-a",
        },
    )
    assert third_response.status_code == 200
    third_payload = cast(object, third_response.json())
    third_body = as_mapping(third_payload)
    third_reply = as_mapping(third_body["reply"])
    third_text = third_reply["text"]

    assert isinstance(third_text, str)
    assert "Approval required" in third_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "shared-room-followup"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])

    assert webex_join["meeting_identifier"] == "987654321"
    assert webex_join["target_device"] == "Board Pro"


def test_shared_room_reset_clears_only_callers_pending_follow_up() -> None:
    scoped_client = build_authenticated_client()

    user_a_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-a",
        },
    )
    assert user_a_response.status_code == 200

    user_b_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "set volume on Desk Pro",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-b",
        },
    )
    assert user_b_response.status_code == 200

    reset_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "/reset",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-b",
        },
    )
    assert reset_response.status_code == 200
    reset_payload = cast(object, reset_response.json())
    reset_body = as_mapping(reset_payload)
    reset_reply = as_mapping(reset_body["reply"])
    reset_text = reset_reply["text"]

    assert isinstance(reset_text, str)
    assert "cleared the session context" in reset_text

    post_reset_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "35",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-b",
        },
    )
    assert post_reset_response.status_code == 200
    post_reset_payload = cast(object, post_reset_response.json())
    post_reset_body = as_mapping(post_reset_payload)
    post_reset_reply = as_mapping(post_reset_body["reply"])
    post_reset_text = post_reset_reply["text"]

    assert isinstance(post_reset_text, str)
    assert "Approval required" not in post_reset_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    assert not any(
        as_mapping(approval)["session_id"] == "shared-room-reset"
        for approval in approvals
    )

    resumed_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "987654321",
            "session_id": "shared-room-reset",
            "room_id": "shared-room-reset",
            "user_id": "user-a",
        },
    )
    assert resumed_response.status_code == 200
    resumed_payload = cast(object, resumed_response.json())
    resumed_body = as_mapping(resumed_payload)
    resumed_reply = as_mapping(resumed_body["reply"])
    resumed_text = resumed_reply["text"]

    assert isinstance(resumed_text, str)
    assert "Approval required" in resumed_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals_payload = cast(object, approvals_response.json())
    approvals_body = as_mapping(approvals_payload)
    approvals = as_sequence(approvals_body["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "shared-room-reset"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])

    assert webex_join["meeting_identifier"] == "987654321"
    assert webex_join["target_device"] == "Board Pro"


def test_blank_target_get_status_asks_follow_up_then_resumes() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        DeviceStatusSnapshot,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        GetStatusParams,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        PolicyDecision,
        ProviderSettings,
        SessionContext,
    )

    class BlankTargetGetStatusProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_STATUS,
                    summary="Get the current device status.",
                    get_status=GetStatusParams(
                        target_device="",
                        include_metrics=True,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class RecordingModeRouter:
        def __init__(self) -> None:
            self.executed_proposals: list[ActionProposal] = []

        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> object:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("build_request should not be called")

        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = policy_decision
            assert proposal.get_status is not None
            self.executed_proposals.append(proposal)
            return ExecutionResult(
                request_id="req-get-status-followup",
                intent=Intent.GET_STATUS,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message=f"Collected status from {proposal.get_status.target_device} via all-LLM mode.",
                device_status=DeviceStatusSnapshot(
                    target_device=proposal.get_status.target_device,
                    source="mock",
                    display_name=proposal.get_status.target_device,
                    online=True,
                ),
            )

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    router = RecordingModeRouter()
    orchestrator = Orchestrator(
        BlankTargetGetStatusProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, router)),
        approval_manager,
    )

    first_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="generic-target-followup-status",
                user_id="debug-user",
                text="status please",
                source=MessageSource.DEBUG,
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert first_reply.text == "Which device should I use?"
    pending_action = memory_store.get_pending_action(
        "generic-target-followup-status", "debug-user"
    )
    assert pending_action is not None
    assert pending_action.action_proposal is not None
    assert pending_action.action_proposal.get_status is not None
    assert pending_action.action_proposal.get_status.include_metrics is True
    assert pending_action.action_proposal.get_status.target_device == ""

    second_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="generic-target-followup-status",
                user_id="debug-user",
                text="Board Pro",
                source=MessageSource.DEBUG,
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert "Collected status from Board Pro" in second_reply.text
    assert len(router.executed_proposals) == 1
    resumed_proposal = router.executed_proposals[0]
    assert resumed_proposal.get_status is not None
    assert resumed_proposal.get_status.target_device == "Board Pro"
    assert resumed_proposal.get_status.include_metrics is True
    assert (
        memory_store.get_pending_action("generic-target-followup-status", "debug-user")
        is None
    )


def test_blank_target_reboot_asks_follow_up_then_resumes() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ApprovalState,
        ExecutionMode,
        ExecutionRequest,
        ExecutionResult,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        PolicyDecision,
        ProviderSettings,
        RebootParams,
        SessionContext,
    )

    class BlankTargetRebootProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.REBOOT,
                    summary="Reboot the target device.",
                    reboot=RebootParams(target_device=""),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class ApprovalRecordingModeRouter:
        def __init__(self) -> None:
            self.built_requests: list[ExecutionRequest] = []

        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionRequest:
            _ = message
            assert proposal.reboot is not None
            execution_request = ExecutionRequest(
                session_id=message.session_id,
                requested_by=message.user_id,
                intent=proposal.intent,
                execution_mode=policy_decision.selected_mode,
                approval_state=policy_decision.approval_state,
                target_device=proposal.reboot.target_device,
                reason=policy_decision.reason,
                reboot=proposal.reboot,
            )
            self.built_requests.append(execution_request)
            return execution_request

        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError(
                "execute should not be called for approval-required reboot"
            )

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

    memory_store = InMemorySessionStore()
    state_store = InMemoryStateStore()
    approval_manager = ApprovalManager(memory_store, state_store)
    router = ApprovalRecordingModeRouter()
    orchestrator = Orchestrator(
        BlankTargetRebootProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM, state_store=state_store),
        cast(ModeRouter, cast(object, router)),
        approval_manager,
    )

    first_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="generic-target-followup-reboot",
                user_id="debug-user",
                text="reboot it",
                source=MessageSource.DEBUG,
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert first_reply.text == "Which device should I use?"
    pending_action = memory_store.get_pending_action(
        "generic-target-followup-reboot", "debug-user"
    )
    assert pending_action is not None
    assert pending_action.action_proposal is not None
    assert pending_action.action_proposal.reboot is not None
    assert pending_action.action_proposal.reboot.target_device == ""

    second_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="generic-target-followup-reboot",
                user_id="debug-user",
                text="Home Office",
                source=MessageSource.DEBUG,
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert "Approval required" in second_reply.text
    assert len(router.built_requests) == 1
    execution_request = router.built_requests[0]
    assert execution_request.reboot is not None
    assert execution_request.reboot.target_device == "Home Office"
    assert execution_request.target_device == "Home Office"
    assert execution_request.execution_mode == ExecutionMode.SEPARATED
    assert execution_request.approval_state == ApprovalState.REQUIRED
    approvals = state_store.list_approval_requests()
    matching = [
        approval
        for approval in approvals
        if approval.session_id == "generic-target-followup-reboot"
    ]
    assert len(matching) == 1
    assert matching[0].execution_request is not None
    assert matching[0].execution_request.reboot is not None
    assert matching[0].execution_request.reboot.target_device == "Home Office"
    assert (
        memory_store.get_pending_action("generic-target-followup-reboot", "debug-user")
        is None
    )


def test_webex_blank_target_get_status_returns_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        ExecutionResult,
        GetStatusParams,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        PolicyDecision,
        ProviderSettings,
        SessionContext,
    )

    class BlankTargetGetStatusProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_STATUS,
                    summary="Get the current device status.",
                    get_status=GetStatusParams(target_device="", include_metrics=True),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class UnusedModeRouter:
        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> object:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("build_request should not be called")

        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(
                device_id="device-1",
                webex_device_id="webex-device-1",
                display_name="Board Pro",
                product="Cisco Board Pro",
                place="HQ 7F",
                device_type="roomdesk",
                permissions=["xapi"],
                online=True,
            ),
            OrganizationDeviceRecord(
                device_id="device-2",
                webex_device_id="webex-device-2",
                display_name="Desk Pro",
                product="Cisco Desk Pro",
                place="Home Office",
                device_type="roomdesk",
                permissions=["xapi"],
                online=True,
            ),
        ]

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetGetStatusProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card",
                user_id="person-1",
                text="status please",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "Which device should I use?"
    assert reply.markdown == "**Select a device**\n\nWhich device should I use?"
    attachments = reply.attachments
    assert len(attachments) == 1
    content = as_mapping(as_mapping(attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_set = as_mapping(body[2])
    choices = as_sequence(choice_set["choices"])
    assert [as_mapping(choice)["value"] for choice in choices] == [
        "Board Pro",
        "Desk Pro",
    ]
    actions = as_sequence(content["actions"])
    continue_action = as_mapping(actions[0])
    cancel_action = as_mapping(actions[1])
    continue_data = as_mapping(continue_action["data"])
    cancel_data = as_mapping(cancel_action["data"])
    assert continue_data["kind"] == "entity_selection"
    assert continue_data["fieldName"] == "target_device"
    assert continue_data["selectionDecision"] == "submit"
    assert cancel_data["selectionDecision"] == "cancel"
    pending_action = memory_store.get_pending_action("webex-selection-card", "person-1")
    assert pending_action is not None
    assert continue_data["pendingActionId"] == pending_action.pending_action_id


def test_webex_missing_target_for_mute_returns_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
        SetMicrophoneMuteParams,
    )

    class BlankTargetMuteProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_MICROPHONE_MUTE,
                    summary="Mute the microphones.",
                    set_microphone_mute=SetMicrophoneMuteParams(
                        target_device="",
                        muted=True,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetMuteProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-mute",
                user_id="person-1",
                text="뮤트해줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert (
        reply.text
        == "어떤 장치를 음소거할까요? 장치 이름을 말씀해주시거나 목록을 확인해주세요."
    )
    assert len(reply.attachments) == 1
    content = as_mapping(as_mapping(reply.attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_set = as_mapping(body[2])
    choices = as_sequence(choice_set["choices"])
    assert [as_mapping(choice)["value"] for choice in choices] == [
        "Codec Pro G2",
        "Home Office",
    ]


def test_webex_follow_up_mic_mute_repeats_selection_card_when_target_still_missing() -> (
    None
):
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
        SetMicrophoneMuteParams,
    )

    class BlankTargetMuteProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_MICROPHONE_MUTE,
                    summary="Mute the microphones.",
                    set_microphone_mute=SetMicrophoneMuteParams(
                        target_device="",
                        muted=True,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetMuteProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-mute-follow-up",
                user_id="person-1",
                text="음소거 해줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    follow_up_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-mute-follow-up",
                user_id="person-1",
                text="마이크 음소거",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert (
        follow_up_reply.text
        == "어떤 장치를 음소거할까요? 장치 이름을 말씀해주시거나 목록을 확인해주세요."
    )
    assert len(follow_up_reply.attachments) == 1
    content = as_mapping(as_mapping(follow_up_reply.attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_set = as_mapping(body[2])
    choices = as_sequence(choice_set["choices"])
    assert [as_mapping(choice)["value"] for choice in choices] == [
        "Codec Pro G2",
        "Home Office",
    ]


def test_webex_follow_up_status_repeats_selection_card_when_target_still_missing() -> (
    None
):
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        GetStatusParams,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
    )

    class BlankTargetGetStatusProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_STATUS,
                    summary="Get the current device status.",
                    get_status=GetStatusParams(target_device="", include_metrics=True),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Board Pro"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Desk Pro"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetGetStatusProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-status-follow-up",
                user_id="person-1",
                text="status please",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    follow_up_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-status-follow-up",
                user_id="person-1",
                text="status",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert follow_up_reply.text == "Which device should I use?"
    assert len(follow_up_reply.attachments) == 1


def test_webex_missing_target_for_volume_returns_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
        SetVolumeParams,
    )

    class BlankTargetVolumeProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_VOLUME,
                    summary="Increase the volume.",
                    set_volume=SetVolumeParams(
                        target_device="",
                        level=65,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetVolumeProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume",
                user_id="person-1",
                text="볼륨 올려줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "어떤 장치의 볼륨을 올릴까요?"
    assert len(reply.attachments) == 1


def test_webex_follow_up_volume_repeats_selection_card_when_target_still_missing() -> (
    None
):
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
        SetVolumeParams,
    )

    class BlankTargetVolumeProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_VOLUME,
                    summary="Increase the volume.",
                    set_volume=SetVolumeParams(
                        target_device="",
                        level=65,
                    ),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetVolumeProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume-follow-up",
                user_id="person-1",
                text="볼륨 올려줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    follow_up_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume-follow-up",
                user_id="person-1",
                text="볼륨 올려줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert follow_up_reply.text == "어떤 장치의 볼륨을 올릴까요?"
    assert len(follow_up_reply.attachments) == 1


def test_webex_follow_up_reboot_repeats_selection_card_when_target_still_missing() -> (
    None
):
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        RebootParams,
        SessionContext,
    )

    class BlankTargetRebootProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.REBOOT,
                    summary="Reboot the target device.",
                    reboot=RebootParams(target_device=""),
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Board Pro"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        BlankTargetRebootProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-reboot-follow-up",
                user_id="person-1",
                text="reboot it",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    follow_up_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-reboot-follow-up",
                user_id="person-1",
                text="reboot",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert follow_up_reply.text == "Which device should I use?"
    assert len(follow_up_reply.attachments) == 1


def test_webex_missing_volume_target_and_level_prefers_selection_card_first() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        PendingActionProposal,
        ProviderSettings,
        SessionContext,
    )

    class MissingVolumeFieldsProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                pending_action=PendingActionProposal(
                    intent=Intent.SET_VOLUME,
                    summary="Set device volume.",
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        MissingVolumeFieldsProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume-first",
                user_id="person-1",
                text="볼륨 높여줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "어떤 장치의 볼륨을 올릴까요?"
    assert len(reply.attachments) == 1


def test_webex_volume_card_selection_then_asks_for_level() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        Intent,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        PendingActionProposal,
        ProviderSettings,
        SessionContext,
    )

    class MissingVolumeFieldsProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            return OrchestrationDecision(
                pending_action=PendingActionProposal(
                    intent=Intent.SET_VOLUME,
                    summary="Set device volume.",
                )
            )

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Codec Pro G2"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Home Office"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        MissingVolumeFieldsProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    _ = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selection-card-volume-next-field",
                user_id="person-1",
                text="볼륨 높여줘",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    pending_action = memory_store.get_pending_action(
        "webex-selection-card-volume-next-field", "person-1"
    )
    assert pending_action is not None

    selection_reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action_id=pending_action.pending_action_id,
            field_name="target_device",
            user_id="person-1",
            selected_value="Codec Pro G2",
            room_id="room-1",
        )
    )

    assert handled is True
    assert selection_reply.text == "What volume level should I set (0-100)?"
    assert len(selection_reply.attachments) == 0


def test_resume_pending_action_selection_rejects_other_user() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        ExecutionResult,
        GetStatusParams,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
    )

    class PassiveProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: object
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("analyze_message should not be called")

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class UnusedModeRouter:
        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> object:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    pending_action = memory_store.set_pending_action(
        "selection-auth-session",
        "owner-user",
        PendingActionProposal(
            intent=Intent.GET_STATUS,
            summary="Get the current device status.",
            action_proposal=ActionProposal(
                intent=Intent.GET_STATUS,
                summary="Get the current device status.",
                get_status=GetStatusParams(target_device="", include_metrics=True),
            ),
        ),
    )
    orchestrator = Orchestrator(
        PassiveProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    reply, resolved = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action_id=pending_action.pending_action_id,
            field_name="target_device",
            selected_value="Board Pro",
            user_id="different-user",
            room_id="room-1",
        )
    )

    assert resolved is False
    assert reply.text == "This selection card belongs to another user."
    assert (
        memory_store.get_pending_action("selection-auth-session", "owner-user")
        is not None
    )


def test_resume_pending_action_selection_cancel_clears_pending_state() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ExecutionMode,
        ExecutionResult,
        GetStatusParams,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
    )

    class PassiveProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: object
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("analyze_message should not be called")

        async def render_execution_reply(
            self,
            execution_result: ExecutionResult,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class UnusedModeRouter:
        async def execute(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> ExecutionResult:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("execute should not be called")

        async def execute_request(self, execution_request: object) -> ExecutionResult:
            _ = execution_request
            raise AssertionError("execute_request should not be called")

        def build_request(
            self,
            message: InboundUserMessage,
            proposal: ActionProposal,
            policy_decision: PolicyDecision,
        ) -> object:
            _ = message
            _ = proposal
            _ = policy_decision
            raise AssertionError("build_request should not be called")

    memory_store = InMemorySessionStore()
    pending_action = memory_store.set_pending_action(
        "selection-cancel-session",
        "owner-user",
        PendingActionProposal(
            intent=Intent.GET_STATUS,
            summary="Get the current device status.",
            action_proposal=ActionProposal(
                intent=Intent.GET_STATUS,
                summary="Get the current device status.",
                get_status=GetStatusParams(target_device="", include_metrics=True),
            ),
        ),
    )
    orchestrator = Orchestrator(
        PassiveProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    reply, resolved = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action_id=pending_action.pending_action_id,
            field_name="target_device",
            selected_value=None,
            user_id="owner-user",
            room_id="room-1",
            cancel=True,
        )
    )

    assert resolved is True
    assert reply.text == "Okay, I cancelled that request."
    assert (
        memory_store.get_pending_action("selection-cancel-session", "owner-user")
        is None
    )


def test_debug_status_reply_includes_expanded_metadata() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "get status of RoomKit-7F", "preferred_mode": "separated"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "display_name=RoomKit-7F" in text
    assert "product=Room Kit" in text
    assert "place=Mock HQ" in text
    assert "software_version=RoomOS 11.0" in text
    assert "serial_number=MOCK123456" in text


@pytest.mark.parametrize("preferred_mode", ["all-llm", "separated"])
def test_debug_get_environment_info_reports_normalized_sensor_fields_in_both_modes(
    monkeypatch: pytest.MonkeyPatch,
    preferred_mode: str,
) -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        scoped_client = build_authenticated_client()
        api_client = QueuedAsyncClient()
        api_client.responses.append(
            make_response(
                "GET",
                "/devices",
                200,
                {"items": [{"id": "device-1", "displayName": "Board Pro"}]},
            )
        )
        api_client.responses.append(
            make_response(
                "GET",
                "/xapi/status",
                200,
                {
                    "RoomAnalytics": {
                        "AmbientTemperature": 21.5,
                        "RelativeHumidity": 48,
                        "AmbientNoise": {"Level": {"A": 39.2}},
                        "PeopleCount": {"Current": 4},
                    },
                    "Peripherals": {
                        "ConnectedDevice": [
                            {"RoomAnalytics": {"AirQuality": {"Index": 83}}}
                        ]
                    },
                },
            )
        )
        token_client_one = QueuedAsyncClient()
        token_client_one.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        token_client_two = QueuedAsyncClient()
        token_client_two.responses.append(
            make_response(
                "GET",
                "/api/tokens/current",
                200,
                {"accessToken": "bot-token"},
            )
        )
        _ = build_client_queue(api_client, token_client_one, token_client_two)
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        response = scoped_client.post(
            "/debug/messages",
            json={
                "text": "get environment info of Board Pro",
                "session_id": f"environment-query-{preferred_mode}",
                "preferred_mode": preferred_mode,
            },
        )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    assert isinstance(text, str)
    assert "Collected environment info from Board Pro" in text
    assert "temperature_celsius=21.5" in text
    assert "relative_humidity_percent=48.0" in text
    assert "ambient_noise_db=39.2" in text
    assert "people_count=4" in text
    assert "air_quality_index=83" in text
    assert "Execution failed" not in text


def test_admin_login_creates_approval_reply() -> None:
    response = client.post(
        "/debug/messages",
        json={"text": "admin login", "session_id": "admin-login-case"},
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    reply = as_mapping(body["reply"])
    text = reply["text"]
    attachments = as_sequence(reply["attachments"])
    assert isinstance(text, str)
    assert "Approval required" in text
    assert len(attachments) == 1


def test_admin_routes_require_authenticated_session() -> None:
    scoped_client = build_unauthenticated_client()

    response = scoped_client.get("/admin/settings")

    assert response.status_code == 401
    assert response.json() == {"detail": "Admin login is required."}


def test_admin_auth_start_allows_default_admin_when_allowlist_empty() -> None:
    scoped_app = build_app()
    scoped_client = build_unauthenticated_client(scoped_app)

    response = scoped_client.post(
        "/admin/auth/start",
        json={"email": "youngcle@cisco.com"},
    )

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    assert body["status"] == "pending"
    session_id = body["session_id"]
    assert isinstance(session_id, str)
    auth_session = scoped_app.state.services.admin_service.get_admin_auth_session(
        session_id
    )
    assert auth_session is not None
    assert auth_session.email == "youngcle@cisco.com"


def test_admin_auth_start_rejects_email_outside_explicit_allowlist() -> None:
    scoped_app = build_app()
    _ = scoped_app.state.services.admin_service.update_runtime_admin_settings(
        RuntimeAdminSettingsUpdate(
            allowed_admin_emails=["ops-admin@example.com"],
        )
    )
    scoped_client = build_unauthenticated_client(scoped_app)

    response = scoped_client.post(
        "/admin/auth/start",
        json={"email": "youngcle@cisco.com"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin email is not allowed."}


def test_admin_auth_browser_flow_sets_cookie_and_logout_clears_access() -> None:
    scoped_app = build_app()
    scoped_client = build_unauthenticated_client(scoped_app)

    start_response = scoped_client.post(
        "/admin/auth/start",
        json={"email": "youngcle@cisco.com"},
    )
    assert start_response.status_code == 200
    start_payload = cast(object, start_response.json())
    start_body = as_mapping(start_payload)
    session_id = start_body["session_id"]
    assert isinstance(session_id, str)

    pending_status_response = scoped_client.get(f"/admin/auth/status/{session_id}")
    assert pending_status_response.status_code == 200
    pending_status_payload = cast(object, pending_status_response.json())
    pending_status_body = as_mapping(pending_status_payload)
    assert pending_status_body["status"] == "pending"
    assert ADMIN_SESSION_COOKIE not in scoped_client.cookies

    approvals = scoped_app.state.services.state_store.list_approval_requests()
    pending_approval = next(
        approval for approval in approvals if approval.admin_session_id == session_id
    )

    approval_response = scoped_client.post(

            f"/debug/approvals/{pending_approval.request_id}?approved=true"
            f"&user_id=person-1&email=youngcle@cisco.com&admin_session_id={session_id}"

    )
    assert approval_response.status_code == 200

    approved_status_response = scoped_client.get(f"/admin/auth/status/{session_id}")
    assert approved_status_response.status_code == 200
    approved_status_payload = cast(object, approved_status_response.json())
    approved_status_body = as_mapping(approved_status_payload)
    assert approved_status_body["status"] == "approved"
    assert ADMIN_SESSION_COOKIE in scoped_client.cookies

    settings_response = scoped_client.get("/admin/settings")
    assert settings_response.status_code == 200

    logout_response = scoped_client.post(
        "/admin/auth/logout",
        json={},
    )
    assert logout_response.status_code == 200
    assert logout_response.json() == {"status": "logged_out"}

    after_logout_response = scoped_client.get("/admin/settings")
    assert after_logout_response.status_code == 401


def test_admin_auth_rejects_mismatched_admin_session_id() -> None:
    scoped_app = build_app()
    scoped_client = build_unauthenticated_client(scoped_app)

    start_response = scoped_client.post(
        "/admin/auth/start",
        json={"email": "youngcle@cisco.com"},
    )
    assert start_response.status_code == 200
    start_payload = cast(object, start_response.json())
    start_body = as_mapping(start_payload)
    session_id = start_body["session_id"]
    assert isinstance(session_id, str)

    approvals = scoped_app.state.services.state_store.list_approval_requests()
    pending_approval = next(
        approval for approval in approvals if approval.admin_session_id == session_id
    )

    reject_response = scoped_client.post(

            f"/debug/approvals/{pending_approval.request_id}?approved=true"
            "&user_id=person-1&email=youngcle@cisco.com&admin_session_id=wrong-session"

    )
    assert reject_response.status_code == 200
    reject_payload = cast(object, reject_response.json())
    reject_body = as_mapping(reject_payload)
    approval = as_mapping(reject_body["approval"])
    assert approval["status"] == "rejected"

    status_response = scoped_client.get(f"/admin/auth/status/{session_id}")
    assert status_response.status_code == 200
    status_payload = cast(object, status_response.json())
    status_body = as_mapping(status_payload)
    assert status_body["status"] == "rejected"
    assert ADMIN_SESSION_COOKIE not in scoped_client.cookies


def test_admin_provider_endpoints_are_available() -> None:
    response = client.get("/admin/providers")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    assert "providers" in body
    active = as_mapping(body["active"])
    assert active["provider"] == "ollama"


def test_admin_settings_endpoint_exposes_default_admin_user() -> None:
    response = client.get("/admin/settings")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    runtime = as_mapping(body["runtime"])
    assert runtime["default_user_email"] == "youngcle@cisco.com"


def test_admin_settings_report_split_webex_auth_config() -> None:
    async def fake_resolve_identity(_self: WebexGateway) -> object:
        return None

    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
            "ADMIN_COOKIE_SECRET": "test-cookie-secret",
        }
    ):
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(WebexGateway, "resolve_bot_identity", fake_resolve_identity)
        try:
            with build_authenticated_client() as scoped_client:
                response = scoped_client.get("/admin/settings")
        finally:
            monkeypatch.undo()

    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    runtime = as_mapping(body["runtime"])
    startup = as_mapping(body["startup"])
    access_token = as_mapping(runtime["access_token"])
    bot_token = as_mapping(runtime["bot_token"])
    assert access_token["present"] is True
    assert access_token["masked_value"] == "***token-manager-configured***"
    assert bot_token["present"] is True
    assert bot_token["masked_value"] == "***configured***"
    assert startup["webex_token_manager_base_url"] == "http://127.0.0.1:3000"


def test_admin_settings_update_changes_next_runtime_view() -> None:
    response = client.put(
        "/admin/settings",
        json={
            "default_user_email": "youngcle@cisco.com",
            "default_space_id": "space-123",
            "default_space_title": "Ops Space",
            "default_execution_mode": "all-llm",
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    runtime = as_mapping(body["runtime"])
    assert runtime["default_space_id"] == "space-123"
    assert runtime["default_execution_mode"] == "all-llm"


def test_admin_devices_endpoint_returns_org_device_list() -> None:
    response = client.get("/admin/devices")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    devices = as_sequence(body["devices"])
    assert len(devices) >= 1


def test_admin_actions_and_stats_endpoints_are_available() -> None:
    actions_response = client.get("/admin/actions")
    assert actions_response.status_code == 200
    actions_payload = cast(object, actions_response.json())
    actions_body = as_mapping(actions_payload)
    actions = as_sequence(actions_body["actions"])
    assert len(actions) >= 1
    action_intents = {
        as_mapping(action)["intent"] for action in actions if isinstance(action, dict)
    }
    assert {"assign_matrix", "unassign_matrix", "swap_matrix"}.issubset(action_intents)

    stats_response = client.get("/admin/stats")
    assert stats_response.status_code == 200
    stats_payload = cast(object, stats_response.json())
    stats_body = as_mapping(stats_payload)
    stats = as_mapping(stats_body["stats"])
    assert "approvals_total" in stats


def test_admin_page_renders_real_html() -> None:
    response = client.get("/admin-page")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Webex Device Assistant Admin" in body
    assert "youngcle@cisco.com" in body
    assert "/admin-page/docs" in body
    assert "/admin-page/static/admin.js" in body


def test_admin_page_docs_renders_manual_summaries() -> None:
    response = client.get("/admin-page/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Webex Device Assistant Manuals" in body
    assert "/admin-page/manuals/ARCHITECTURE.md" in body
    assert "/admin-page/architecture-guide" in body
    assert "/admin-page/manuals/INSTALL.md" in body
    assert "/admin-page/manuals/USER_MANUAL.md" in body
    assert "ARCHITECTURE_CURRENT.md" not in body
    assert "Open the full markdown manuals" in body


def test_admin_page_static_css_asset_is_served() -> None:
    response = client.get("/admin-page/static/admin.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--color-accent" in response.text


@pytest.mark.parametrize(
    ("manual_name", "expected_heading"),
    [
        ("ARCHITECTURE.md", "# Architecture Manual"),
        ("INSTALL.md", "# Install Manual"),
        ("USER_MANUAL.md", "# User Manual"),
        ("MANUAL_KO.md", "# Webex Device Assistant 앱 아키텍처 및 사용 가이드"),
    ],
)
def test_admin_page_manual_routes_serve_top_level_manuals(
    manual_name: str, expected_heading: str
) -> None:
    response = client.get(f"/admin-page/manuals/{manual_name}")
    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert expected_heading in response.text


def test_admin_page_architecture_guide_renders_current_html_manual() -> None:
    response = client.get("/admin-page/architecture-guide")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Device Assistant Guide" in body
    assert "/admin-page/manuals/ARCHITECTURE.md" in body
    assert "Cameras.SpeakerTrack.Set" in body


def test_admin_page_healthz_reports_ready_ui() -> None:
    response = client.get("/admin-page/healthz")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    assert body["ui"] == "ready"
    assert body["page"] == "/admin-page"


def test_admin_policy_endpoints_are_available() -> None:
    response = client.get("/admin/policies")
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    policies = as_mapping(body["policies"])
    assert "get_status" in policies


def test_debug_approval_endpoint_resolves_request() -> None:
    approval_response = client.post(
        "/debug/messages",
        json={
            "text": "dial youngcle@cisco.com on Board Pro",
            "session_id": "resolve-approval-case",
        },
    )
    approval_payload = cast(object, approval_response.json())
    approval_body = as_mapping(approval_payload)
    reply = as_mapping(approval_body["reply"])
    attachments = as_sequence(reply["attachments"])
    first_attachment = as_mapping(attachments[0])
    content = as_mapping(first_attachment["content"])
    actions = as_sequence(content["actions"])
    first_action = as_mapping(actions[0])
    data = as_mapping(first_action["data"])
    request_id = data["requestId"]
    assert isinstance(request_id, str)

    decision_response = client.post(f"/debug/approvals/{request_id}?approved=true")
    assert decision_response.status_code == 200
    decision_payload = cast(object, decision_response.json())
    decision_body = as_mapping(decision_payload)
    approval = as_mapping(decision_body["approval"])
    assert approval["status"] == "executed"


def test_non_implemented_provider_change_is_rejected_live() -> None:
    response = client.put(
        "/admin/providers",
        json={
            "provider": "openai",
            "model": "gpt-4.1",
            "enabled": True,
        },
    )
    assert response.status_code == 409


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


def test_admin_provider_endpoint_does_not_echo_api_key() -> None:
    response = client.put(
        "/admin/providers",
        json={
            "provider": "rule_based",
            "model": "rule-based-default",
            "api_key": "super-secret",
            "enabled": True,
        },
    )
    assert response.status_code == 200
    payload = cast(object, response.json())
    body = as_mapping(payload)
    provider = as_mapping(body["provider"])
    assert provider["api_key"] is None

    list_response = client.get("/admin/providers")
    assert list_response.status_code == 200
    listed_payload = cast(object, list_response.json())
    listed_body = as_mapping(listed_payload)
    active = as_mapping(listed_body["active"])
    assert active["api_key"] is None


def test_persisted_admin_runtime_state_survives_restart(tmp_path: Path) -> None:
    state_path = tmp_path / "admin-state.json"
    with temporary_env({"ADMIN_STATE_PATH": str(state_path)}):
        first_app = build_app()
        first_client = build_authenticated_client(first_app)

        settings_response = first_client.put(
            "/admin/settings",
            json={
                "default_space_id": "space-789",
                "default_space_title": "Persistent Ops",
                "default_user_email": "ops-admin@example.com",
                "default_execution_mode": "all-llm",
                "selected_provider": "ollama",
                "selected_provider_model": "persisted-model",
                "selected_device_id": "device-7",
                "selected_device_name": "Board Pro 7",
            },
        )
        assert settings_response.status_code == 200

        provider_response = first_client.put(
            "/admin/providers",
            json={
                "provider": "ollama",
                "model": "gemma4:latest",
                "base_url": "http://127.0.0.1:11434/api",
                "api_key": "do-not-persist",
                "temperature": 0.3,
                "max_tokens": 512,
                "enabled": True,
            },
        )
        assert provider_response.status_code == 200

        policy_response = first_client.put(
            "/admin/policies/get_status",
            json={
                "allowed_modes": ["all-llm"],
                "risk_level": "read_only",
                "approval_state": "not_required",
                "reason": "Allow all-llm for restart-survival test.",
            },
        )
        assert policy_response.status_code == 200

        approval_response = first_client.post(
            "/debug/messages",
            json={
                "text": "dial youngcle@cisco.com on Board Pro",
                "session_id": "persisted-approval-case",
            },
        )
        assert approval_response.status_code == 200

        second_app = build_app()
        second_client = build_authenticated_client(second_app)

        persisted_settings_response = second_client.get("/admin/settings")
        assert persisted_settings_response.status_code == 200
        persisted_settings_payload = cast(object, persisted_settings_response.json())
        persisted_settings_body = as_mapping(persisted_settings_payload)
        runtime = as_mapping(persisted_settings_body["runtime"])
        assert runtime["default_space_id"] == "space-789"
        assert runtime["default_space_title"] == "Persistent Ops"
        assert runtime["default_user_email"] == "ops-admin@example.com"
        assert runtime["default_execution_mode"] == "all-llm"
        assert runtime["selected_provider"] == "ollama"
        assert runtime["selected_provider_model"] == "persisted-model"
        assert runtime["selected_device_id"] == "device-7"
        assert runtime["selected_device_name"] == "Board Pro 7"

        persisted_providers_response = second_client.get("/admin/providers")
        assert persisted_providers_response.status_code == 200
        persisted_providers_payload = cast(object, persisted_providers_response.json())
        persisted_providers_body = as_mapping(persisted_providers_payload)
        active = as_mapping(persisted_providers_body["active"])
        assert active["provider"] == "ollama"
        assert active["model"] == "gemma4:latest"
        assert active["base_url"] == "http://127.0.0.1:11434/api"
        assert active["temperature"] == 0.3
        assert active["max_tokens"] == 512
        assert active["api_key"] is None

        persisted_policies_response = second_client.get("/admin/policies")
        assert persisted_policies_response.status_code == 200
        persisted_policies_payload = cast(object, persisted_policies_response.json())
        persisted_policies_body = as_mapping(persisted_policies_payload)
        policies = as_mapping(persisted_policies_body["policies"])
        get_status_policy = as_mapping(policies["get_status"])
        assert get_status_policy["allowed_modes"] == ["all-llm"]
        assert get_status_policy["reason"] == "Allow all-llm for restart-survival test."

        approvals_response = second_client.get("/admin/approvals")
        assert approvals_response.status_code == 200
        approvals_payload = cast(object, approvals_response.json())
        approvals_body = as_mapping(approvals_payload)
        approvals = as_sequence(approvals_body["approvals"])
        persisted_action_approvals = [
            as_mapping(approval)
            for approval in approvals
            if as_mapping(approval)["session_id"] == "persisted-approval-case"
        ]
        assert len(persisted_action_approvals) == 1
        assert persisted_action_approvals[0]["status"] == "pending"

        stats_response = second_client.get("/admin/stats")
        assert stats_response.status_code == 200
        stats_payload = cast(object, stats_response.json())
        stats_body = as_mapping(stats_payload)
        stats = as_mapping(stats_body["stats"])
        approvals_total = stats["approvals_total"]
        approvals_pending = stats["approvals_pending"]
        assert isinstance(approvals_total, int)
        assert approvals_total >= 1
        assert approvals_pending == 1
        audit_total = stats["audit_total"]
        assert isinstance(audit_total, int)
        assert audit_total >= 2
        assert stats["sessions_total"] == 0
        assert stats["processed_webhook_events"] == 0


def test_environment_info_policy_defaults_to_no_approval() -> None:
    scoped_client = build_authenticated_client()

    policies_response = scoped_client.get("/admin/policies")
    assert policies_response.status_code == 200
    policies_payload = cast(object, policies_response.json())
    policies_body = as_mapping(policies_payload)
    policies = as_mapping(policies_body["policies"])

    environment_policy = as_mapping(policies["get_environment_info"])
    assert environment_policy["allowed_modes"] == ["separated", "all-llm"]
    assert environment_policy["approval_state"] == "not_required"
    assert environment_policy["risk_level"] == "read_only"


def test_room_booking_policy_defaults_to_no_approval() -> None:
    scoped_client = build_authenticated_client()

    policies_response = scoped_client.get("/admin/policies")
    assert policies_response.status_code == 200
    policies_payload = cast(object, policies_response.json())
    policies_body = as_mapping(policies_payload)
    policies = as_mapping(policies_body["policies"])

    booking_policy = as_mapping(policies["get_room_booking"])
    assert booking_policy["allowed_modes"] == ["separated", "all-llm"]
    assert booking_policy["approval_state"] == "not_required"
    assert booking_policy["risk_level"] == "read_only"


def test_join_obtp_policy_defaults_to_approval_required() -> None:
    scoped_client = build_authenticated_client()

    policies_response = scoped_client.get("/admin/policies")
    assert policies_response.status_code == 200
    policies_payload = cast(object, policies_response.json())
    policies_body = as_mapping(policies_payload)
    policies = as_mapping(policies_body["policies"])

    join_policy = as_mapping(policies["join_obtp"])
    assert join_policy["allowed_modes"] == ["separated", "all-llm"]
    assert join_policy["approval_state"] == "required"
    assert join_policy["risk_level"] == "low"


def test_action_registry_lists_environment_info_as_approval_free() -> None:
    scoped_client = build_authenticated_client()

    registry_response = scoped_client.get("/admin/actions")
    assert registry_response.status_code == 200
    registry_payload = cast(object, registry_response.json())
    registry_body = as_mapping(registry_payload)
    actions = as_sequence(registry_body["actions"])
    environment_action = next(
        action
        for action in actions
        if as_mapping(action)["intent"] == "get_environment_info"
    )
    environment_mapping = as_mapping(environment_action)

    assert environment_mapping["approval_required_by_default"] is False
    assert environment_mapping["supported_modes"] == ["separated", "all-llm"]


def test_action_registry_lists_room_booking_and_join_obtp_defaults() -> None:
    scoped_client = build_authenticated_client()

    registry_response = scoped_client.get("/admin/actions")
    assert registry_response.status_code == 200
    registry_payload = cast(object, registry_response.json())
    registry_body = as_mapping(registry_payload)
    actions = as_sequence(registry_body["actions"])
    booking_action = next(
        action
        for action in actions
        if as_mapping(action)["intent"] == "get_room_booking"
    )
    join_action = next(
        action for action in actions if as_mapping(action)["intent"] == "join_obtp"
    )

    booking_mapping = as_mapping(booking_action)
    join_mapping = as_mapping(join_action)

    assert booking_mapping["approval_required_by_default"] is False
    assert booking_mapping["supported_modes"] == ["separated", "all-llm"]
    assert join_mapping["approval_required_by_default"] is True
    assert join_mapping["supported_modes"] == ["separated", "all-llm"]


def test_persisted_approval_can_be_resolved_after_restart(tmp_path: Path) -> None:
    state_path = tmp_path / "approval-state.json"
    with temporary_env({"ADMIN_STATE_PATH": str(state_path)}):
        first_app = build_app()
        first_client = TestClient(first_app)

        approval_response = first_client.post(
            "/debug/messages",
            json={
                "text": "dial youngcle@cisco.com on Board Pro",
                "session_id": "restart-approval-case",
            },
        )
        assert approval_response.status_code == 200
        approval_payload = cast(object, approval_response.json())
        approval_body = as_mapping(approval_payload)
        reply = as_mapping(approval_body["reply"])
        attachments = as_sequence(reply["attachments"])
        first_attachment = as_mapping(attachments[0])
        content = as_mapping(first_attachment["content"])
        actions = as_sequence(content["actions"])
        first_action = as_mapping(actions[0])
        data = as_mapping(first_action["data"])
        request_id = data["requestId"]
        assert isinstance(request_id, str)

        second_app = build_app()
        second_client = build_authenticated_client(second_app)

        decision_response = second_client.post(
            f"/debug/approvals/{request_id}?approved=true"
        )
        assert decision_response.status_code == 200
        decision_payload = cast(object, decision_response.json())
        decision_body = as_mapping(decision_payload)
        approval = as_mapping(decision_body["approval"])
        assert approval["status"] == "executed"

        approvals_response = second_client.get("/admin/approvals")
        assert approvals_response.status_code == 200
        approvals_payload = cast(object, approvals_response.json())
        approvals_body = as_mapping(approvals_payload)
        approvals = as_sequence(approvals_body["approvals"])
        resolved = as_mapping(approvals[0])
        assert resolved["request_id"] == request_id
        assert resolved["status"] == "executed"


def test_file_backed_state_store_persists_processed_webhook_event_ids(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "webhook-dedupe-state.json"
    first_store = FileBackedStateStore(state_path)

    assert not first_store.has_processed_webhook_event("message-1")

    first_store.mark_processed_webhook_event("message-1")

    assert first_store.has_processed_webhook_event("message-1")
    assert first_store.get_stats().processed_webhook_events == 1

    restarted_store = FileBackedStateStore(state_path)

    assert restarted_store.has_processed_webhook_event("message-1")
    assert restarted_store.get_stats().processed_webhook_events == 1



def test_setting_option_request_returns_toggle_selection_card_with_device_dropdown() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        MessageSource,
        OrchestrationDecision,
        OrganizationDeviceRecord,
        ProviderSettings,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("setting option card request should not use provider")

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called before card selection")

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
                OrganizationDeviceRecord(
                    device_id="device-1",
                    display_name="Board Pro",
                    product="Board Pro",
                    place="HQ",
                ),
                OrganizationDeviceRecord(
                    device_id="device-2",
                    display_name="Room Bar",
                    product="Room Bar",
                    place="Home",
                ),
        ]

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="setting-option-card",
                user_id="person-1",
                text="마이크 음소거 설정",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "마이크 음소거 상태를 선택해주세요."
    attachments = reply.attachments
    assert len(attachments) == 1
    content = as_mapping(as_mapping(attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_sets = [
        as_mapping(item)
        for item in body
        if as_mapping(item).get("type") == "Input.ChoiceSet"
    ]
    assert [choice_set["id"] for choice_set in choice_sets] == [
        "settingValue",
        "selectedValue",
    ]
    assert choice_sets[0]["style"] == "expanded"
    assert [as_mapping(choice)["value"] for choice in as_sequence(choice_sets[0]["choices"])] == [
        "true",
        "false",
    ]
    assert choice_sets[1]["style"] == "compact"
    assert [as_mapping(choice)["value"] for choice in as_sequence(choice_sets[1]["choices"])] == [
        "Board Pro",
        "Room Bar",
    ]
    actions = as_sequence(content["actions"])
    assert [as_mapping(action)["title"] for action in actions] == ["Apply", "Cancel"]

    pending_action = memory_store.get_pending_action("setting-option-card", "person-1")
    assert pending_action is not None
    assert pending_action.intent.value == "set_microphone_mute"
    submit_data = as_mapping(as_mapping(actions[0])["data"])
    assert submit_data["kind"] == "entity_selection"
    assert submit_data["pendingActionId"] == pending_action.pending_action_id
    assert submit_data["fieldName"] == "setting_value"
    assert submit_data["settingFieldName"] == "muted"


def test_setting_card_submission_applies_value_and_device_selection() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ApprovalState,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
        RiskLevel,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("submission should resume an existing pending action")

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class CapturingModeRouter:
        def __init__(self) -> None:
            self.proposal: object | None = None

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("approval should not be required in this test")

        async def execute(self, message: InboundUserMessage, proposal: object, policy_decision: object) -> ExecutionResult:
            _ = message
            _ = policy_decision
            self.proposal = proposal
            return ExecutionResult(
                request_id="setting-submit-result",
                intent=Intent.SET_MICROPHONE_MUTE,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Muted Board Pro.",
            )

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    mode_router = CapturingModeRouter()
    pending_action = PendingActionProposal(
        intent=Intent.SET_MICROPHONE_MUTE,
        summary="Change microphone mute state.",
    )
    memory_store.set_pending_action("setting-submit", "person-1", pending_action)
    class NoApprovalPolicyEvaluator(PolicyEvaluator):
        def evaluate(
            self, proposal: object, preferred_mode: object = None
        ) -> PolicyDecision:
            _ = proposal
            _ = preferred_mode
            return PolicyDecision(
                selected_mode=ExecutionMode.ALL_LLM,
                allowed_modes=[ExecutionMode.ALL_LLM],
                risk_level=RiskLevel.LOW,
                approval_state=ApprovalState.NOT_REQUIRED,
                reason="Test bypasses approval to verify setting-card submission.",
            )

    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        NoApprovalPolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, mode_router)),
        approval_manager,
    )

    reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action.pending_action_id,
            "setting_value",
            "Board Pro",
            "person-1",
            "room-1",
            setting_field_name="muted",
            setting_value="true",
        )
    )

    assert handled is True
    assert reply.text == (
        "Muted Board Pro. Policy: Test bypasses approval to verify setting-card submission."
    )
    assert isinstance(mode_router.proposal, ActionProposal)
    proposal = mode_router.proposal
    assert proposal.intent == Intent.SET_MICROPHONE_MUTE
    assert proposal.set_microphone_mute is not None
    assert proposal.set_microphone_mute.target_device == "Board Pro"
    assert proposal.set_microphone_mute.muted is True
    assert memory_store.get_pending_action("setting-submit", "person-1") is None

def test_camera_mode_request_returns_supported_mode_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        MessageSource,
        OrchestrationDecision,
        ProviderSettings,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("camera mode card request should not use provider")

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called before card selection")

    async def list_camera_modes(target_device: str) -> tuple[str, ...]:
        assert target_device == "Room Bar"
        return ("Manual", "Dynamic", "BestOverview", "Closeup", "Frames", "GroupAndSpeaker")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        camera_mode_lister=list_camera_modes,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="camera-mode-card",
                user_id="person-1",
                text="Room Bar 카메라 모드 변경",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "카메라 모드를 선택해주세요."
    assert reply.markdown == "**카메라 모드 선택**\n\n대상 장치: Room Bar"
    attachments = reply.attachments
    assert len(attachments) == 1
    content = as_mapping(as_mapping(attachments[0])["content"])
    actions = as_sequence(content["actions"])
    assert [as_mapping(action)["title"] for action in actions] == [
        "Manual",
        "Dynamic",
        "BestOverview",
        "Closeup",
        "Frames",
        "GroupAndSpeaker",
        "Cancel",
    ]
    assert [
        as_mapping(as_mapping(action)["data"]).get("selectedValue")
        for action in actions[:6]
    ] == ["Manual", "Dynamic", "BestOverview", "Closeup", "Frames", "GroupAndSpeaker"]
    for action in actions[:6]:
        data = as_mapping(as_mapping(action)["data"])
        assert data["kind"] == "entity_selection"
        assert data["fieldName"] == "camera_mode"
        assert data["selectionDecision"] == "submit"

    pending_action = memory_store.get_pending_action("camera-mode-card", "person-1")
    assert pending_action is not None
    assert pending_action.intent.value == "set_camera_mode"
    assert as_mapping(as_mapping(actions[0])["data"])["pendingActionId"] == pending_action.pending_action_id


def test_rule_based_provider_understands_turn_on_selfview_without_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import (
        InboundUserMessage,
        Intent,
        MessageSource,
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


def test_webex_turn_on_selfview_without_target_returns_device_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        MessageSource,
        OrganizationDeviceRecord,
    )

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Board Pro"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Room Bar"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called while target is missing")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called while target is missing")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called while target is missing")

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        approval_manager,
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="webex-selfview-selection-card",
                user_id="person-1",
                text="turn on Selfview",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text == "어떤 장치의 Selfview를 켜드릴까요? 장치 이름을 말씀해 주세요."
    assert len(reply.attachments) == 1
    content = as_mapping(as_mapping(reply.attachments[0])["content"])
    body = as_sequence(content["body"])
    choice_set = as_mapping(body[2])
    assert choice_set["id"] == "selectedValue"
    assert [as_mapping(choice)["value"] for choice in as_sequence(choice_set["choices"])] == [
        "Board Pro",
        "Room Bar",
    ]


def test_rule_based_turn_on_toggle_commands_without_target_prompt_for_device() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import InboundUserMessage, Intent, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, Intent, MessageSource, SessionContext

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


def test_webex_korean_selfview_and_video_without_target_return_device_selection_card() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        MessageSource,
        OrganizationDeviceRecord,
    )

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(device_id="device-1", display_name="Board Pro"),
            OrganizationDeviceRecord(device_id="device-2", display_name="Room Bar"),
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called while target is missing")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called while target is missing")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called while target is missing")

    cases = [
        ("셀프뷰 켜줘", "어떤 장치의 Selfview를 켜드릴까요? 장치 이름을 말씀해 주세요."),
        ("비디오 켜줘", "어떤 장치의 비디오를 켜드릴까요? 장치 이름을 말씀해 주세요."),
    ]

    for text, expected_reply in cases:
        memory_store = InMemorySessionStore()
        approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
        orchestrator = Orchestrator(
            RuleBasedProvider(default_target_device=""),
            memory_store,
            PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
            cast(ModeRouter, cast(object, UnusedModeRouter())),
            approval_manager,
            device_lister=list_devices,
        )

        reply = asyncio.run(
            orchestrator.handle_message(
                InboundUserMessage(
                    session_id=f"webex-korean-toggle-selection-card-{text}",
                    user_id="person-1",
                    text=text,
                    source=MessageSource.WEBEX,
                    room_id="room-1",
                    preferred_mode=ExecutionMode.ALL_LLM,
                )
            )
        )

        assert reply.text == expected_reply
        assert len(reply.attachments) == 1
        content = as_mapping(as_mapping(reply.attachments[0])["content"])
        body = as_sequence(content["body"])
        choice_set = as_mapping(body[2])
        assert choice_set["id"] == "selectedValue"
        assert choice_set["placeholder"] == "장치를 선택하세요"
        assert [as_mapping(choice)["value"] for choice in as_sequence(choice_set["choices"])] == [
            "Board Pro",
            "Room Bar",
        ]


def test_ollama_provider_uses_llm_before_rule_based_for_contextual_korean_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        InboundUserMessage,
        Intent,
        MessageSource,
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
        InboundUserMessage,
        Intent,
        MessageSource,
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


def test_rule_based_provider_extracts_korean_webex_join_number_without_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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


def test_ollama_provider_falls_back_for_invalid_llm_korean_webex_join_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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


def test_rule_based_provider_extracts_korean_environment_info_with_target() -> None:
    from assistant_app.providers.rule_based import RuleBasedProvider
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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


def test_ollama_provider_falls_back_for_invalid_llm_korean_environment_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import InboundUserMessage, MessageSource, SessionContext

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


def test_missing_webex_join_accepts_https_meet_url_follow_up_then_resume() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "webex join on Board Pro",
            "session_id": "followup-webex-join-url",
        },
    )
    assert first_response.status_code == 200
    first_reply = as_mapping(as_mapping(cast(object, first_response.json()))["reply"])
    assert first_reply["text"] == "What Webex meeting ID or address should I join?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "https://acecloud.webex.com/meet/youngcle",
            "session_id": "followup-webex-join-url",
        },
    )
    assert second_response.status_code == 200
    second_reply = as_mapping(as_mapping(cast(object, second_response.json()))["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals = as_sequence(as_mapping(cast(object, approvals_response.json()))["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "followup-webex-join-url"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])

    assert webex_join["meeting_identifier"] == "https://acecloud.webex.com/meet/youngcle"
    assert webex_join["target_device"] == "Board Pro"


def test_missing_webex_join_accepts_spaced_number_follow_up_then_uses_default_webex_device() -> None:
    scoped_client = build_authenticated_client()

    first_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "Join meeting",
            "session_id": "followup-webex-join-spaced-number-default",
            "source": "webex",
            "room_id": "debug-room",
            "target_device": "Room Bar",
        },
    )
    assert first_response.status_code == 200
    first_reply = as_mapping(as_mapping(cast(object, first_response.json()))["reply"])
    assert first_reply["text"] == "What Webex meeting ID or address should I join?"

    second_response = scoped_client.post(
        "/debug/messages",
        json={
            "text": "2571 017 7729",
            "session_id": "followup-webex-join-spaced-number-default",
            "source": "webex",
            "room_id": "debug-room",
            "target_device": "Room Bar",
        },
    )
    assert second_response.status_code == 200
    second_reply = as_mapping(as_mapping(cast(object, second_response.json()))["reply"])
    second_text = second_reply["text"]

    assert isinstance(second_text, str)
    assert "Approval required" in second_text or "Webex join requested for 25710177729 on Room Bar" in second_text

    approvals_response = scoped_client.get("/admin/approvals")
    assert approvals_response.status_code == 200
    approvals = as_sequence(as_mapping(cast(object, approvals_response.json()))["approvals"])
    pending = next(
        approval
        for approval in approvals
        if as_mapping(approval)["session_id"] == "followup-webex-join-spaced-number-default"
    )
    execution_request = as_mapping(as_mapping(pending)["execution_request"])
    webex_join = as_mapping(execution_request["webex_join"])
    assert webex_join["meeting_identifier"] == "25710177729"
    assert webex_join["target_device"] == "Room Bar"


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
    assert "hang up requested for Room Bar" in text or "hang up requested for room bar" in text.lower()
    assert "invalid action payload" not in text.lower()



def test_selfview_request_prompts_device_first_then_filtered_capability_options() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        MessageSource,
        OrganizationDeviceRecord,
    )

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(
                device_id="device-room-bar",
                display_name="Room Bar",
                product="Cisco Room Bar",
                place="HQ 7F",
                online=True,
            ),
            OrganizationDeviceRecord(
                device_id="device-navigator",
                display_name="Navigator",
                product="Cisco Room Navigator",
                place="HQ 7F",
                online=True,
            ),
        ]

    class CapturingModeRouter:
        def __init__(self) -> None:
            self.execute_request_calls: list[object] = []

        async def execute(self, *args: object, **kwargs: object) -> object:
            from shared.contracts import ExecutionResult, ExecutionStatus, Intent

            self.execute_request_calls.append((args, kwargs))
            return ExecutionResult(
                request_id="req-selfview-cap-test",
                intent=Intent.SET_SELFVIEW,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Enabled selfview on Room Bar.",
            )

        async def execute_request(self, execution_request: object) -> object:
            from shared.contracts import ExecutionResult, ExecutionStatus, Intent

            self.execute_request_calls.append(execution_request)
            return ExecutionResult(
                request_id="req-selfview-cap-test",
                intent=Intent.SET_SELFVIEW,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Enabled selfview on Room Bar.",
            )

        def build_request(self, *args: object, **kwargs: object) -> object:
            return object()

    memory_store = InMemorySessionStore()
    approval_manager = ApprovalManager(memory_store, InMemoryStateStore())
    captured_router = CapturingModeRouter()
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, captured_router)),
        approval_manager,
        device_lister=list_devices,
    )

    first_reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="capability-selfview-device-first",
                user_id="person-1",
                text="turn on Selfview",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert len(first_reply.attachments) == 1
    content = as_mapping(as_mapping(first_reply.attachments[0])["content"])
    body = as_sequence(content["body"])
    device_choice_set = as_mapping(body[2])
    assert device_choice_set["id"] == "selectedValue"
    assert [as_mapping(choice)["value"] for choice in as_sequence(device_choice_set["choices"])] == [
        "Room Bar"
    ]
    assert "Navigator" not in json.dumps(content, ensure_ascii=False)

    pending_action = memory_store.get_pending_action("capability-selfview-device-first", "person-1")
    assert pending_action is not None

    second_reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action.pending_action_id,
            "target_device",
            "Room Bar",
            "person-1",
            "room-1",
        )
    )

    assert handled is True
    # With enabled=True already extracted from "turn on Selfview", the device
    # selection should execute immediately — no second ON/OFF card.
    assert second_reply.attachments == []
    assert "Enabled selfview on Room Bar" in second_reply.text
    assert len(captured_router.execute_request_calls) == 1


def test_device_list_formats_workspace_name_with_model_and_capabilities() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import ExecutionMode, OrganizationDeviceRecord

    memory_store = InMemorySessionStore()
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, object())),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    rendered = orchestrator._format_device_list(
        [
            OrganizationDeviceRecord(
                device_id="device-room-bar",
                display_name="Executive Room",
                product="Cisco Room Bar",
                place="HQ 7F",
                online=True,
                connection_status="connected",
                software_version="RoomOS 11.20",
            ),
            OrganizationDeviceRecord(
                device_id="device-navigator",
                display_name="Touch Panel",
                product="Cisco Room Navigator",
                online=False,
                connection_status="disconnected",
            ),
        ],
        "allowed",
    )

    assert "Executive Room (Cisco Room Bar)" in rendered
    assert "지원 기능: 오디오, 카메라, 디스플레이, 레이아웃, 미팅, 프레젠테이션, 셀프뷰, 스탠바이" in rendered
    assert "Touch Panel (Cisco Room Navigator)" in rendered
    assert "지원 기능:" not in rendered.split("Touch Panel (Cisco Room Navigator)", 1)[1]
    assert "software=RoomOS 11.20" in rendered


def test_status_response_is_detailed_korean_sections() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        DeviceStatusSnapshot,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        Intent,
    )

    memory_store = InMemorySessionStore()
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, object())),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    rendered = orchestrator._format_execution_result(
        ExecutionResult(
            request_id="req-detailed-status",
            intent=Intent.GET_STATUS,
            execution_mode=ExecutionMode.ALL_LLM,
            status=ExecutionStatus.SUCCESS,
            message="Status for Executive Room.",
            device_status=DeviceStatusSnapshot(
                target_device="Executive Room",
                source="webex",
                device_id="device-room-bar",
                display_name="Executive Room",
                product="Cisco Room Bar",
                place="HQ 7F",
                software_version="RoomOS 11.20",
                serial_number="SERIAL1",
                online=True,
                connection_status="connected",
                system_state="Initialized",
                active_interface="Ethernet",
                ipv4_address="192.0.2.10",
                volume=55,
                volume_muted=False,
                microphones_muted=True,
                call_active=False,
                active_call_count=0,
                presentation_active=True,
                selfview_mode="On",
                speakertrack_state="Active",
                standby_state="Off",
            ),
        ),
        "allowed",
    )

    assert "**상태 상세**" in rendered
    assert "장치: Executive Room (Cisco Room Bar)" in rendered
    assert "연결: online=True, connection=connected, system=Initialized" in rendered
    assert "네트워크: interface=Ethernet, ipv4=192.0.2.10" in rendered
    assert "오디오: volume=55, muted=False, microphones_muted=True" in rendered
    assert "통화/공유: call_active=False, active_call_count=0, presentation_active=True" in rendered
    assert "카메라/화면: selfview=On, speakertrack=Active" in rendered



def test_korean_selfview_keyword_starts_device_then_option_flow() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.rule_based import RuleBasedProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ExecutionMode,
        InboundUserMessage,
        MessageSource,
        OrganizationDeviceRecord,
    )

    async def list_devices() -> list[OrganizationDeviceRecord]:
        return [
            OrganizationDeviceRecord(
                device_id="device-room-bar",
                display_name="Room Bar",
                product="Cisco Room Bar",
                place="HQ 7F",
                online=True,
            )
        ]

    class UnusedModeRouter:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("execute should not be called before device and option selection")

        async def execute_request(self, execution_request: object) -> object:
            raise AssertionError("execute_request should not be called before device and option selection")

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("build_request should not be called before device and option selection")

    memory_store = InMemorySessionStore()
    orchestrator = Orchestrator(
        RuleBasedProvider(default_target_device=""),
        memory_store,
        PolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, UnusedModeRouter())),
        ApprovalManager(memory_store, InMemoryStateStore()),
        device_lister=list_devices,
    )

    reply = asyncio.run(
        orchestrator.handle_message(
            InboundUserMessage(
                session_id="korean-selfview-keyword-flow",
                user_id="person-1",
                text="셀프뷰",
                source=MessageSource.WEBEX,
                room_id="room-1",
                preferred_mode=ExecutionMode.ALL_LLM,
            )
        )
    )

    assert reply.text != "What should I do next?"
    assert len(reply.attachments) == 1
    content = as_mapping(as_mapping(reply.attachments[0])["content"])
    assert "장치" in json.dumps(content, ensure_ascii=False)
    assert "Room Bar" in json.dumps(content, ensure_ascii=False)


def test_setting_option_card_submit_uses_selected_value_as_setting_not_target() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ApprovalState,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
        RiskLevel,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("submission should resume pending action")

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class CapturingModeRouter:
        def __init__(self) -> None:
            self.proposal: ActionProposal | None = None

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("approval should not be required")

        async def execute(self, message: InboundUserMessage, proposal: ActionProposal, policy_decision: object) -> ExecutionResult:
            _ = message
            _ = policy_decision
            self.proposal = proposal
            return ExecutionResult(
                request_id="setting-selected-value-result",
                intent=Intent.SET_SELFVIEW,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Selfview enabled on Room Bar.",
            )

    class NoApprovalPolicyEvaluator(PolicyEvaluator):
        def evaluate(self, proposal: object, preferred_mode: object = None) -> PolicyDecision:
            _ = proposal
            _ = preferred_mode
            return PolicyDecision(
                selected_mode=ExecutionMode.ALL_LLM,
                allowed_modes=[ExecutionMode.ALL_LLM],
                risk_level=RiskLevel.LOW,
                approval_state=ApprovalState.NOT_REQUIRED,
                reason="Test bypasses approval.",
            )

    memory_store = InMemorySessionStore()
    pending_action = PendingActionProposal(
        intent=Intent.SET_SELFVIEW,
        summary="Selfview setting.",
        target_device="Room Bar",
    )
    memory_store.set_pending_action("setting-selected-value", "person-1", pending_action)
    mode_router = CapturingModeRouter()
    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        NoApprovalPolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, mode_router)),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action.pending_action_id,
            "setting_value",
            "true",
            "person-1",
            "room-1",
            setting_field_name="enabled",
        )
    )

    assert handled is True
    assert "Selfview enabled on Room Bar" in reply.text
    assert mode_router.proposal is not None
    assert mode_router.proposal.set_selfview is not None
    assert mode_router.proposal.set_selfview.target_device == "Room Bar"
    assert mode_router.proposal.set_selfview.enabled is True



def test_setting_option_card_submit_uses_setting_value_when_selected_value_missing() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.mode_router import ModeRouter
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.policy_evaluator import PolicyEvaluator
    from assistant_app.providers.base import LLMProvider
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import (
        ActionProposal,
        ApprovalState,
        ExecutionMode,
        ExecutionResult,
        ExecutionStatus,
        InboundUserMessage,
        Intent,
        OrchestrationDecision,
        PendingActionProposal,
        PolicyDecision,
        ProviderSettings,
        RiskLevel,
        SessionContext,
    )

    class UnusedProvider(LLMProvider):
        def bind_settings(self, settings: ProviderSettings) -> None:
            _ = settings

        async def analyze_message(
            self, message: InboundUserMessage, session: SessionContext
        ) -> OrchestrationDecision:
            _ = message
            _ = session
            raise AssertionError("submission should resume pending action")

        async def render_execution_reply(
            self,
            execution_result: object,
            policy_reason: str,
            canonical_text: str,
        ) -> str | None:
            _ = execution_result
            _ = policy_reason
            _ = canonical_text
            return None

    class CapturingModeRouter:
        def __init__(self) -> None:
            self.proposal: ActionProposal | None = None

        def build_request(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("approval should not be required")

        async def execute(self, message: InboundUserMessage, proposal: ActionProposal, policy_decision: object) -> ExecutionResult:
            _ = message
            _ = policy_decision
            self.proposal = proposal
            return ExecutionResult(
                request_id="setting-value-only-result",
                intent=Intent.SET_MICROPHONE_MUTE,
                execution_mode=ExecutionMode.ALL_LLM,
                status=ExecutionStatus.SUCCESS,
                message="Microphones muted on Room Bar.",
            )

    class NoApprovalPolicyEvaluator(PolicyEvaluator):
        def evaluate(self, proposal: object, preferred_mode: object = None) -> PolicyDecision:
            _ = proposal
            _ = preferred_mode
            return PolicyDecision(
                selected_mode=ExecutionMode.ALL_LLM,
                allowed_modes=[ExecutionMode.ALL_LLM],
                risk_level=RiskLevel.LOW,
                approval_state=ApprovalState.NOT_REQUIRED,
                reason="Test bypasses approval.",
            )

    memory_store = InMemorySessionStore()
    pending_action = PendingActionProposal(
        intent=Intent.SET_MICROPHONE_MUTE,
        summary="Microphone mute setting.",
        target_device="Room Bar",
    )
    memory_store.set_pending_action("setting-value-only", "person-1", pending_action)
    mode_router = CapturingModeRouter()
    orchestrator = Orchestrator(
        UnusedProvider(),
        memory_store,
        NoApprovalPolicyEvaluator(default_mode=ExecutionMode.ALL_LLM),
        cast(ModeRouter, cast(object, mode_router)),
        ApprovalManager(memory_store, InMemoryStateStore()),
    )

    reply, handled = asyncio.run(
        orchestrator.resume_pending_action_selection(
            pending_action.pending_action_id,
            "setting_value",
            None,
            "person-1",
            "room-1",
            setting_field_name="muted",
            setting_value="true",
        )
    )

    assert handled is True
    assert reply.attachments == []
    assert "Microphones muted on Room Bar" in reply.text
    assert mode_router.proposal is not None
    assert mode_router.proposal.set_microphone_mute is not None
    assert mode_router.proposal.set_microphone_mute.target_device == "Room Bar"
    assert mode_router.proposal.set_microphone_mute.muted is True
    assert memory_store.get_pending_action("setting-value-only", "person-1") is None


def test_default_config_uses_ollama_for_llm_first_semantic_parsing() -> None:
    from assistant_app.config import AppConfig
    from assistant_app.ollama_support import DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_MODEL
    from shared.contracts import ProviderKind

    config = AppConfig.from_env()

    assert config.default_provider == ProviderKind.OLLAMA
    assert config.default_provider_model == DEFAULT_OLLAMA_MODEL
    assert config.default_provider_base_url == DEFAULT_OLLAMA_BASE_URL


def test_in_memory_state_store_defaults_to_ollama_provider_settings() -> None:
    from assistant_app.ollama_support import DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_MODEL
    from assistant_app.state_store import InMemoryStateStore
    from shared.contracts import ProviderKind

    settings = InMemoryStateStore().get_provider_settings()

    assert settings.provider == ProviderKind.OLLAMA
    assert settings.model == DEFAULT_OLLAMA_MODEL
    assert settings.base_url == DEFAULT_OLLAMA_BASE_URL


def test_ollama_prompt_exposes_all_roomos_actions_and_llm_first_semantic_contract() -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import InboundUserMessage, Intent, MessageSource, SessionContext

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


def test_ollama_provider_accepts_semantic_korean_payloads_for_every_roomos_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assistant_app.providers.ollama import OllamaProvider
    from shared.contracts import (
        InboundUserMessage,
        Intent,
        MessageSource,
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
        ("webex_join", "룸바로 25565427373 회의 참가해줘", {"target_device": "Room Bar", "meeting_identifier": "25565427373"}),
        ("join_obtp", "룸바 다음 예약 회의 참가해줘", {"target_device": "Room Bar"}),
        ("dial", "룸바에서 young@example.com으로 전화해줘", {"target_device": "Room Bar", "address": "young@example.com"}),
        ("hang_up", "룸바 통화 종료해줘", {"target_device": "Room Bar", "call_id": None}),
        ("send_dtmf", "룸바에서 123# 톤 보내줘", {"target_device": "Room Bar", "tones": "123#", "call_id": None}),
        ("set_microphone_mute", "룸바 마이크 음소거 해줘", {"target_device": "Room Bar", "muted": True}),
        ("set_microphone_mode", "룸바 마이크 노이즈 제거 모드로 해줘", {"target_device": "Room Bar", "mode": "noise-reduction"}),
        ("set_volume", "룸바 소리를 35로 맞춰줘", {"target_device": "Room Bar", "level": 35}),
        ("set_video_mute", "룸바 카메라 꺼줘", {"target_device": "Room Bar", "muted": True}),
        ("set_selfview", "룸바 화면에 내 모습 나오게 해줘", {"target_device": "Room Bar", "enabled": True}),
        ("set_camera_mode", "룸바 카메라를 수동 모드로 바꿔줘", {"target_device": "Room Bar", "mode": "Manual"}),
        ("set_layout", "룸바 레이아웃을 크게 보기로 바꿔줘", {"target_device": "Room Bar", "layout_name": "Prominent"}),
        ("set_presentation", "룸바 화면 공유 시작해줘", {"target_device": "Room Bar", "enabled": True}),
        ("switch_input_source", "룸바 입력 소스를 HDMI1로 바꿔줘", {"target_device": "Room Bar", "source_id": "HDMI1"}),
        ("assign_matrix", "룸바 매트릭스 출력 1에 소스 2를 할당해줘", {"target_device": "Room Bar", "output": "1", "mode": "Replace", "layout": "Equal", "source_id": "2", "remote_main": None}),
        ("unassign_matrix", "룸바 매트릭스 출력 1 소스 2 해제해줘", {"target_device": "Room Bar", "output": "1", "source_id": "2", "remote_main": None}),
        ("swap_matrix", "룸바 매트릭스 출력 1과 출력 2를 바꿔줘", {"target_device": "Room Bar", "output_a": "1", "output_b": "2"}),
        ("set_display_mode", "룸바 디스플레이를 왼쪽 영상 오른쪽 발표 모드로 해줘", {"target_device": "Room Bar", "mode": "left-video-right-presentation"}),
        ("set_display_role", "룸바 커넥터 2를 프레젠테이션 전용으로 설정해줘", {"target_device": "Room Bar", "connector_id": 2, "role": "presentation-only"}),
        ("activate_camera_preset", "룸바 카메라 프리셋 3 실행해줘", {"target_device": "Room Bar", "preset_id": "3"}),
        ("adjust_camera_position", "룸바 카메라 1을 왼쪽으로 조금 움직여줘", {"target_device": "Room Bar", "camera_id": "1", "pan": 1000, "tilt": None, "zoom": None}),
        ("set_speakertrack", "룸바 스피커트랙 켜줘", {"target_device": "Room Bar", "enabled": True}),
        ("set_standby", "룸바 대기모드로 전환해줘", {"target_device": "Room Bar", "enabled": True}),
        ("reboot", "룸바 재부팅해줘", {"target_device": "Room Bar"}),
        ("factory_reset", "룸바 공장초기화 확인하고 진행해줘", {"target_device": "Room Bar", "acknowledged": True}),
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
