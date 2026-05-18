"""End-to-end and integration tests for the Device Assistant app.

Helpers and fixtures have been extracted to ``tests/_helpers.py`` and
``tests/conftest.py``. This file is being split by domain incrementally;
see ``docs/improvement-plan.md`` for the migration plan.
"""

import asyncio
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
    temporary_env,
)
from tests.test_webex_integration import (
    QueuedAsyncClient,
    StaticTokenProvider,
    async_client_factory,
    build_client_queue,
    make_response,
)

client = build_authenticated_client(app)


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


def test_orchestrator_get_status_reply_includes_new_non_null_fields_and_omits_nulls() -> None:
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
        Intent,
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
                request=httpx.Request("GET", "http://127.0.0.1:3000/api/tokens/current"),
            )
        )
        _ = build_client_queue(token_client)
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)

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
        config_client.responses.append(make_response("PATCH", "/deviceConfigurations", 200, []))
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
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)
        monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", async_client_factory)

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
    assert "Exact configurable microphone mode values reported by Webex: Focused, Wide." in text
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
            make_response("POST", "/xapi/command/Video.Layout.SetLayout", 200, {"status": "ok"})
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
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)
        monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", async_client_factory)

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
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)
        monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", async_client_factory)

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
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)
        monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", async_client_factory)

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
    assert "Mock video matrix swap requested for outputs HDMI1 and HDMI2 on Board Pro." in text
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
            make_response("POST", "/xapi/command/Video.Layout.SetLayout", 200, {"status": "ok"})
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
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)
        monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", async_client_factory)

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
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)
        monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", async_client_factory)

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
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)
        monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", async_client_factory)

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
        api_client.responses.append(make_response("GET", "/devices", 200, {"items": []}))
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
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)
        monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", async_client_factory)

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
                        "ConnectedDevice": [{"RoomAnalytics": {"AirQuality": {"Index": 83}}}]
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
        monkeypatch.setattr("assistant_app.token_provider.httpx.AsyncClient", async_client_factory)
        monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", async_client_factory)

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
