import asyncio
import hashlib
import hmac
import json
from collections.abc import Iterator
from contextlib import contextmanager
from os import environ
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant_app.config import AppConfig
from assistant_app.main import build_app
from assistant_app.token_provider import TokenManagerTokenProvider
from assistant_app.webex_gateway import (
    WebexBotIdentityMismatchError,
    WebexGateway,
    WebexWebhookEnvelope,
    WebexWebhookRecord,
    WebexWebhookRegistration,
)
from device_executor.device_client import DeviceClient, DeviceResolutionError
from shared.contracts import InboundUserMessage, MessageSource, OutboundReply


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


class QueuedAsyncClient:
    queued_clients: list["QueuedAsyncClient"] = []

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, object]]] = []
        self.responses: list[httpx.Response] = []

    async def __aenter__(self) -> "QueuedAsyncClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def get(self, path: str, **kwargs: object) -> httpx.Response:
        self.requests.append(("GET", path, dict(kwargs)))
        return self.responses.pop(0)

    async def post(self, path: str, **kwargs: object) -> httpx.Response:
        self.requests.append(("POST", path, dict(kwargs)))
        return self.responses.pop(0)

    async def delete(self, path: str, **kwargs: object) -> httpx.Response:
        self.requests.append(("DELETE", path, dict(kwargs)))
        return self.responses.pop(0)

    async def patch(self, path: str, **kwargs: object) -> httpx.Response:
        self.requests.append(("PATCH", path, dict(kwargs)))
        return self.responses.pop(0)


def make_response(
    method: str, path: str, status_code: int, body: object
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=body,
        request=httpx.Request(method, f"https://webexapis.com/v1{path}"),
    )


def make_empty_response(method: str, path: str, status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request(method, f"https://webexapis.com/v1{path}"),
    )


def build_client_queue(*clients: QueuedAsyncClient) -> list[QueuedAsyncClient]:
    QueuedAsyncClient.queued_clients = list(clients)
    return QueuedAsyncClient.queued_clients


def async_client_factory(*args: object, **kwargs: object) -> QueuedAsyncClient:
    _ = args, kwargs
    return QueuedAsyncClient.queued_clients.pop(0)


class StaticTokenProvider:
    def __init__(self, token: str = "bot-token") -> None:
        self.token: str = token

    async def get_bearer_token(self) -> str:
        return self.token


@pytest.fixture(autouse=True)
def clear_client_queue() -> Iterator[None]:
    QueuedAsyncClient.queued_clients = []
    yield
    QueuedAsyncClient.queued_clients = []


def test_real_mode_requires_webex_bot_token() -> None:
    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": None,
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
        }
    ):
        with pytest.raises(
            ValueError,
            match="WEBEX_BOT_TOKEN is required when WEBEX_MOCK_MODE=false.",
        ):
            _ = AppConfig.from_env()


def test_real_mode_requires_webhook_secret() -> None:
    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": None,
        }
    ):
        with pytest.raises(
            ValueError,
            match="WEBEX_WEBHOOK_SECRET is required when WEBEX_MOCK_MODE=false.",
        ):
            _ = AppConfig.from_env()


def test_gateway_resolve_bot_identity_rejects_mismatched_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_client = QueuedAsyncClient()
    identity_client.responses.append(
        make_response(
            "GET",
            "/people/me",
            200,
            {"id": "resolved-bot-id", "emails": ["wxdeviceassist@webex.bot"]},
        )
    )
    _ = build_client_queue(identity_client)
    monkeypatch.setattr(
        "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
    )

    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="configured-bot-id",
            webex_webhook_secret="secret",
        )
    )

    with pytest.raises(
        WebexBotIdentityMismatchError,
        match="WEBEX_BOT_PERSON_ID does not match the bot identity returned by people/me.",
    ):
        _ = asyncio.run(gateway.resolve_bot_identity())


def test_gateway_resolve_bot_identity_accepts_application_and_people_forms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_client = QueuedAsyncClient()
    identity_client.responses.append(
        make_response(
            "GET",
            "/people/me",
            200,
            {
                "id": "Y2lzY29zcGFyazovL3VzL1BFT1BMRS80Y2E3YTI1ZS1jOTFhLTQ3NjktOTAzMi1mOGJkODI3ZWZlODI",
                "emails": ["wxdeviceassist@webex.bot"],
            },
        )
    )
    _ = build_client_queue(identity_client)
    monkeypatch.setattr(
        "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
    )

    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="Y2lzY29zcGFyazovL3VzL0FQUExJQ0FUSU9OLzRjYTdhMjVlLWM5MWEtNDc2OS05MDMyLWY4YmQ4MjdlZmU4Mg",
            webex_webhook_secret="secret",
        )
    )

    identity = asyncio.run(gateway.resolve_bot_identity())

    assert identity is not None
    assert (
        identity.id
        == "Y2lzY29zcGFyazovL3VzL1BFT1BMRS80Y2E3YTI1ZS1jOTFhLTQ3NjktOTAzMi1mOGJkODI3ZWZlODI"
    )


def test_gateway_treats_application_and_people_ids_as_same_self_author(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="Y2lzY29zcGFyazovL3VzL0FQUExJQ0FUSU9OLzRjYTdhMjVlLWM5MWEtNDc2OS05MDMyLWY4YmQ4MjdlZmU4Mg",
            webex_webhook_secret="secret",
        )
    )
    gateway.bot_person_id = "Y2lzY29zcGFyazovL3VzL1BFT1BMRS80Y2E3YTI1ZS1jOTFhLTQ3NjktOTAzMi1mOGJkODI3ZWZlODI"

    event = gateway.parse_webhook_payload(
        {
            "id": "event-self-envelope",
            "resource": "messages",
            "event": "created",
            "data": {
                "id": "message-self-envelope",
                "roomId": "room-1",
                "personId": "Y2lzY29zcGFyazovL3VzL0FQUExJQ0FUSU9OLzRjYTdhMjVlLWM5MWEtNDc2OS05MDMyLWY4YmQ4MjdlZmU4Mg",
            },
        }
    )

    inbound = asyncio.run(gateway.fetch_inbound_message(event))

    assert inbound is None


def test_reconcile_matches_group_filter_with_people_and_me_forms() -> None:
    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="Y2lzY29zcGFyazovL3VzL0FQUExJQ0FUSU9OLzRjYTdhMjVlLWM5MWEtNDc2OS05MDMyLWY4YmQ4MjdlZmU4Mg",
            webex_webhook_secret="secret",
            webex_webhook_target_url="https://example.com/webhooks/webex/messages",
            webex_webhook_reconcile_on_startup=True,
        ),
    )
    gateway.bot_person_id = "Y2lzY29zcGFyazovL3VzL1BFT1BMRS80Y2E3YTI1ZS1jOTFhLTQ3NjktOTAzMi1mOGJkODI3ZWZlODI"

    assert (
        gateway._filters_match(
            "roomType=group&mentionedPeople=me",
            "roomType=group&mentionedPeople=Y2lzY29zcGFyazovL3VzL1BFT1BMRS80Y2E3YTI1ZS1jOTFhLTQ3NjktOTAzMi1mOGJkODI3ZWZlODI",
        )
        is True
    )


def test_gateway_drops_self_authored_webhook_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
        )
    )
    gateway.bot_person_id = "bot-person-id"
    gateway.bot_emails = {"wxdeviceassist@webex.bot"}

    event = gateway.parse_webhook_payload(
        {
            "id": "event-self-envelope",
            "resource": "messages",
            "event": "created",
            "data": {
                "id": "message-self-envelope",
                "roomId": "room-1",
                "personId": "bot-person-id",
                "personEmail": "wxdeviceassist@webex.bot",
            },
        }
    )

    inbound = asyncio.run(gateway.fetch_inbound_message(event))

    assert inbound is None


def test_reconcile_mode_requires_target_url() -> None:
    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
            "WEBEX_WEBHOOK_RECONCILE_ON_STARTUP": "true",
            "WEBEX_WEBHOOK_TARGET_URL": None,
        }
    ):
        with pytest.raises(
            ValueError,
            match="WEBEX_WEBHOOK_TARGET_URL is required when WEBEX_MOCK_MODE=false.",
        ):
            _ = AppConfig.from_env()


def test_real_device_mode_requires_token_manager_api_key() -> None:
    with temporary_env(
        {
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": None,
        }
    ):
        with pytest.raises(
            ValueError,
            match="WEBEX_TOKEN_MANAGER_API_KEY is required when DEVICE_MOCK_MODE=false.",
        ):
            _ = AppConfig.from_env()


def test_real_mode_requires_https_target_url_when_provided() -> None:
    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
            "WEBEX_WEBHOOK_TARGET_URL": "http://example.com/webhooks/webex/messages",
        }
    ):
        with pytest.raises(
            ValueError, match="WEBEX_WEBHOOK_TARGET_URL must be a valid https URL."
        ):
            _ = AppConfig.from_env()


def test_real_mode_locks_webhook_subscription_to_messages_created() -> None:
    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
            "WEBEX_WEBHOOK_RESOURCE": "rooms",
        }
    ):
        with pytest.raises(
            ValueError, match="WEBEX_WEBHOOK_RESOURCE must be 'messages'."
        ):
            _ = AppConfig.from_env()


def test_gateway_webhook_lifecycle_uses_official_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_client = QueuedAsyncClient()
    list_client.responses.append(
        make_response(
            "GET",
            "/webhooks",
            200,
            {
                "items": [
                    {
                        "id": "hook-1",
                        "name": "webex-device-assistant-messages-created",
                        "targetUrl": "https://example.com/webhooks/webex/messages",
                        "resource": "messages",
                        "event": "created",
                        "filter": "roomType=direct",
                    }
                ]
            },
        )
    )
    create_client = QueuedAsyncClient()
    create_client.responses.append(
        make_response(
            "POST",
            "/webhooks",
            200,
            {
                "id": "hook-2",
                "name": "webex-device-assistant-messages-created",
                "targetUrl": "https://example.com/webhooks/webex/messages",
                "resource": "messages",
                "event": "created",
                "filter": "roomType=direct",
            },
        )
    )
    delete_client = QueuedAsyncClient()
    delete_client.responses.append(
        make_empty_response("DELETE", "/webhooks/hook-2", 204)
    )
    _ = build_client_queue(list_client, create_client, delete_client)
    monkeypatch.setattr(
        "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
    )

    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            webex_webhook_target_url="https://example.com/webhooks/webex/messages",
        ),
    )

    listed = asyncio.run(gateway.list_webhooks())
    created = asyncio.run(
        gateway.create_webhook(
            WebexWebhookRegistration(
                name="webex-device-assistant-messages-created",
                targetUrl="https://example.com/webhooks/webex/messages",
                resource="messages",
                event="created",
                filter="roomType=direct",
                secret="secret",
            )
        )
    )
    asyncio.run(gateway.delete_webhook("hook-2"))

    assert listed[0].id == "hook-1"
    assert created.id == "hook-2"
    assert list_client.requests == [
        (
            "GET",
            "/webhooks",
            {"headers": {"Authorization": "Bearer bot-token"}},
        )
    ]
    assert create_client.requests == [
        (
            "POST",
            "/webhooks",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "name": "webex-device-assistant-messages-created",
                    "targetUrl": "https://example.com/webhooks/webex/messages",
                    "resource": "messages",
                    "event": "created",
                    "filter": "roomType=direct",
                    "secret": "secret",
                },
            },
        )
    ]
    assert delete_client.requests == [
        (
            "DELETE",
            "/webhooks/hook-2",
            {"headers": {"Authorization": "Bearer bot-token"}},
        )
    ]


def test_gateway_fetches_message_details_and_posts_replies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_client = QueuedAsyncClient()
    fetch_client.responses.append(
        make_response(
            "GET",
            "/messages/message-1",
            200,
            {
                "id": "message-1",
                "roomId": "room-1",
                "personId": "user-1",
                "personEmail": "user@example.com",
                "text": "get status of Board Pro",
            },
        )
    )
    send_client = QueuedAsyncClient()
    send_client.responses.append(
        make_response("POST", "/messages", 200, {"id": "reply-1"})
    )
    _ = build_client_queue(fetch_client, send_client)
    monkeypatch.setattr(
        "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
    )

    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
        ),
    )
    event = gateway.parse_webhook_payload(
        {
            "id": "event-1",
            "resource": "messages",
            "event": "created",
            "data": {"id": "message-1", "roomId": "room-1", "personId": "user-1"},
        }
    )

    inbound = asyncio.run(gateway.fetch_inbound_message(event))
    assert inbound is not None
    assert inbound.text == "get status of Board Pro"
    assert inbound.room_id == "room-1"

    asyncio.run(gateway.send_reply(OutboundReply(text="Status ok", room_id="room-1")))

    assert fetch_client.requests == [
        (
            "GET",
            "/messages/message-1",
            {"headers": {"Authorization": "Bearer bot-token"}},
        )
    ]
    assert send_client.requests == [
        (
            "POST",
            "/messages",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {"roomId": "room-1", "text": "Status ok"},
            },
        )
    ]


def test_gateway_posts_card_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    send_client = QueuedAsyncClient()
    send_client.responses.append(
        make_response("POST", "/messages", 200, {"id": "reply-1"})
    )
    _ = build_client_queue(send_client)
    monkeypatch.setattr(
        "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
    )

    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
        ),
    )

    asyncio.run(
        gateway.send_reply(
            OutboundReply(
                text="Approval required",
                markdown="**Approval required**",
                room_id="room-1",
                attachments=[
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": {"type": "AdaptiveCard", "version": "1.0"},
                    }
                ],
            )
        )
    )

    assert send_client.requests == [
        (
            "POST",
            "/messages",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "roomId": "room-1",
                    "text": "Approval required",
                    "markdown": "**Approval required**",
                    "attachments": [
                        {
                            "contentType": "application/vnd.microsoft.card.adaptive",
                            "content": {
                                "type": "AdaptiveCard",
                                "version": "1.0",
                            },
                        }
                    ],
                },
            },
        )
    ]


def test_gateway_fetches_attachment_action_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = QueuedAsyncClient()
    client.responses.append(
        make_response(
            "GET",
            "/attachment/actions/action-1",
            200,
            {
                "id": "action-1",
                "type": "submit",
                "messageId": "message-1",
                "personId": "person-1",
                "roomId": "room-1",
                "inputs": {"decision": "approve", "requestId": "req-1"},
            },
        )
    )
    _ = build_client_queue(client)
    monkeypatch.setattr(
        "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
    )

    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
        ),
    )

    details = asyncio.run(gateway.fetch_attachment_action_details("action-1"))

    assert details.inputs["decision"] == "approve"
    assert client.requests == [
        (
            "GET",
            "/attachment/actions/action-1",
            {"headers": {"Authorization": "Bearer bot-token"}},
        )
    ]


def test_gateway_deletes_message(monkeypatch: pytest.MonkeyPatch) -> None:
    client = QueuedAsyncClient()
    client.responses.append(
        httpx.Response(
            204,
            request=httpx.Request(
                "DELETE", "https://webexapis.com/v1/messages/message-1"
            ),
        )
    )
    _ = build_client_queue(client)
    monkeypatch.setattr(
        "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
    )

    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
        )
    )

    asyncio.run(gateway.delete_message("message-1"))

    assert client.requests == [
        (
            "DELETE",
            "/messages/message-1",
            {"headers": {"Authorization": "Bearer bot-token"}},
        )
    ]


def test_attachment_action_webhook_resolves_admin_login_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
        }
    ):
        app = build_app()
        approval_manager = app.state.services.approval_manager
        from shared.contracts import InboundUserMessage, MessageSource

        approval_request = approval_manager.create_admin_auth_request(
            InboundUserMessage(
                session_id="session-1",
                user_id="person-1",
                person_email="youngcle@cisco.com",
                text="admin login",
                source=MessageSource.WEBEX,
                room_id="room-1",
            )
        )

        fetch_client = QueuedAsyncClient()
        fetch_client.responses.append(
            make_response(
                "GET",
                "/attachment/actions/action-1",
                200,
                {
                    "id": "action-1",
                    "type": "submit",
                    "messageId": "message-1",
                    "personId": "person-1",
                    "roomId": "room-1",
                    "inputs": {
                        "decision": "approve",
                        "requestId": approval_request.request_id,
                    },
                },
            )
        )
        person_lookup_client = QueuedAsyncClient()
        person_lookup_client.responses.append(
            make_response(
                "GET",
                "/people/person-1",
                200,
                {"emails": ["youngcle@cisco.com"]},
            )
        )
        delete_client = QueuedAsyncClient()
        delete_client.responses.append(
            httpx.Response(
                204,
                request=httpx.Request(
                    "DELETE", "https://webexapis.com/v1/messages/message-1"
                ),
            )
        )
        _ = build_client_queue(fetch_client, person_lookup_client, delete_client)
        monkeypatch.setattr(
            "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
        )

        client = TestClient(app)
        payload = {
            "id": "event-attachment-1",
            "resource": "attachmentActions",
            "event": "created",
            "data": {"id": "action-1"},
        }
        raw_body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(b"secret", raw_body, hashlib.sha1).hexdigest()

        response = client.post(
            "/webhooks/webex/attachment-actions",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Spark-Signature": signature,
            },
        )

        resolved = app.state.services.state_store.get_approval_request(
            approval_request.request_id
        )

    assert response.status_code == 202
    assert resolved is not None
    assert resolved.status == "approved"
    assert delete_client.requests == [
        (
            "DELETE",
            "/messages/message-1",
            {"headers": {"Authorization": "Bearer bot-token"}},
        )
    ]


def test_attachment_action_webhook_executes_approved_action_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
        }
    ):
        app = build_app()
        test_client = TestClient(app)
        request_response = test_client.post(
            "/debug/messages",
            json={
                "text": "dial youngcle@cisco.com on Board Pro",
                "session_id": "webex-approval-action",
                "room_id": "room-1",
            },
        )
        assert request_response.status_code == 200

        approvals = app.state.services.state_store.list_approval_requests()
        approval_request = next(
            request
            for request in approvals
            if request.session_id == "webex-approval-action"
        )

        fetch_client = QueuedAsyncClient()
        fetch_client.responses.append(
            make_response(
                "GET",
                "/attachment/actions/action-2",
                200,
                {
                    "id": "action-2",
                    "type": "submit",
                    "messageId": "message-1",
                    "personId": "person-1",
                    "roomId": "room-1",
                    "inputs": {
                        "decision": "approve",
                        "requestId": approval_request.request_id,
                    },
                },
            )
        )
        delete_client = QueuedAsyncClient()
        delete_client.responses.append(
            httpx.Response(
                204,
                request=httpx.Request(
                    "DELETE", "https://webexapis.com/v1/messages/message-1"
                ),
            )
        )
        person_lookup_client = QueuedAsyncClient()
        person_lookup_client.responses.append(
            make_response(
                "GET",
                "/people/person-1",
                200,
                {"emails": ["approver@example.com"]},
            )
        )
        send_client = QueuedAsyncClient()
        send_client.responses.append(
            make_response("POST", "/messages", 200, {"id": "reply-2"})
        )
        _ = build_client_queue(
            fetch_client, person_lookup_client, delete_client, send_client
        )
        monkeypatch.setattr(
            "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
        )

        payload = {
            "id": "event-attachment-2",
            "resource": "attachmentActions",
            "event": "created",
            "data": {"id": "action-2"},
        }
        raw_body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(b"secret", raw_body, hashlib.sha1).hexdigest()

        response = test_client.post(
            "/webhooks/webex/attachment-actions",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Spark-Signature": signature,
            },
        )

        resolved = app.state.services.state_store.get_approval_request(
            approval_request.request_id
        )

    assert response.status_code == 202
    assert resolved is not None
    assert resolved.status == "executed"
    assert fetch_client.requests == [
        (
            "GET",
            "/attachment/actions/action-2",
            {"headers": {"Authorization": "Bearer bot-token"}},
        ),
    ]
    assert delete_client.requests == [
        (
            "DELETE",
            "/messages/message-1",
            {"headers": {"Authorization": "Bearer bot-token"}},
        )
    ]
    assert send_client.requests == [
        (
            "POST",
            "/messages",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "roomId": "room-1",
                    "text": "Mock dial requested to youngcle@cisco.com on Board Pro. Policy: Outbound calls are mutating actions and should require explicit approval.",
                },
            },
        ),
    ]


def test_attachment_action_webhook_executes_approved_action_request_in_real_device_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
            "DEVICE_MOCK_MODE": "false",
            "WEBEX_TOKEN_MANAGER_API_KEY": "token-manager-key",
            "WEBEX_TOKEN_MANAGER_BASE_URL": "http://token-manager.local",
        }
    ):
        app = build_app()
        test_client = TestClient(app)
        request_response = test_client.post(
            "/debug/messages",
            json={
                "text": "dial youngcle@cisco.com on Board Pro",
                "session_id": "webex-approval-action-real",
                "room_id": "room-1",
            },
        )
        assert request_response.status_code == 200

        approvals = app.state.services.state_store.list_approval_requests()
        approval_request = next(
            request
            for request in approvals
            if request.session_id == "webex-approval-action-real"
        )

        fetch_client = QueuedAsyncClient()
        fetch_client.responses.append(
            make_response(
                "GET",
                "/attachment/actions/action-3",
                200,
                {
                    "id": "action-3",
                    "type": "submit",
                    "messageId": "message-1",
                    "personId": "person-1",
                    "roomId": "room-1",
                    "inputs": {
                        "decision": "approve",
                        "requestId": approval_request.request_id,
                    },
                },
            )
        )
        delete_client = QueuedAsyncClient()
        delete_client.responses.append(
            httpx.Response(
                204,
                request=httpx.Request(
                    "DELETE", "https://webexapis.com/v1/messages/message-1"
                ),
            )
        )
        person_lookup_client = QueuedAsyncClient()
        person_lookup_client.responses.append(
            make_response(
                "GET",
                "/people/person-1",
                200,
                {"emails": ["approver@example.com"]},
            )
        )
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
            make_response("POST", "/xapi/command/Dial", 200, {"status": "OK"})
        )
        send_client = QueuedAsyncClient()
        send_client.responses.append(
            make_response("POST", "/messages", 200, {"id": "reply-3"})
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
            fetch_client,
            person_lookup_client,
            delete_client,
            resolve_client,
            token_client_one,
            command_client,
            token_client_two,
            send_client,
        )
        monkeypatch.setattr(
            "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
        )
        monkeypatch.setattr(
            "device_executor.device_client.httpx.AsyncClient", async_client_factory
        )

        payload = {
            "id": "event-attachment-3",
            "resource": "attachmentActions",
            "event": "created",
            "data": {"id": "action-3"},
        }
        raw_body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(b"secret", raw_body, hashlib.sha1).hexdigest()

        response = test_client.post(
            "/webhooks/webex/attachment-actions",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Spark-Signature": signature,
            },
        )

        resolved = app.state.services.state_store.get_approval_request(
            approval_request.request_id
        )

    assert response.status_code == 202
    assert resolved is not None
    assert resolved.status == "executed"
    assert resolve_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        )
    ]
    assert command_client.requests == [
        (
            "POST",
            "/xapi/command/Dial",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "deviceId": "device-1",
                    "arguments": {"Number": "youngcle@cisco.com"},
                },
            },
        )
    ]
    assert send_client.requests == [
        (
            "POST",
            "/messages",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "roomId": "room-1",
                    "text": "Dial requested to youngcle@cisco.com on Board Pro. Policy: Outbound calls are mutating actions and should require explicit approval.",
                },
            },
        )
    ]


def test_attachment_action_webhook_routes_entity_selection_without_approval_manager() -> (
    None
):
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.webex_gateway import WebexAttachmentActionDetails
    from assistant_app.webhook_controller import WebhookController
    from shared.contracts import OutboundReply

    class FakeGateway:
        def __init__(self) -> None:
            self.deleted_message_ids: list[str] = []
            self.sent_replies: list[OutboundReply] = []

        async def fetch_attachment_action_details(
            self, action_id: str
        ) -> WebexAttachmentActionDetails:
            assert action_id == "action-selection-1"
            return WebexAttachmentActionDetails(
                id=action_id,
                type="submit",
                messageId="message-selection-1",
                personId="person-1",
                roomId="room-1",
                inputs={
                    "kind": "entity_selection",
                    "pendingActionId": "pending-1",
                    "fieldName": "target_device",
                    "selectedValue": "Board Pro",
                    "selectionDecision": "submit",
                },
            )

        async def fetch_person_email(self, person_id: str) -> str | None:
            assert person_id == "person-1"
            return "user@example.com"

        async def delete_message(self, message_id: str) -> None:
            self.deleted_message_ids.append(message_id)

        async def send_reply(self, reply: OutboundReply) -> None:
            self.sent_replies.append(reply)

    class FakeOrchestrator:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def resume_pending_action_selection(
            self,
            pending_action_id: str,
            field_name: str,
            selected_value: str | None,
            user_id: str,
            room_id: str | None,
            person_email: str | None = None,
            *,
            cancel: bool = False,
        ) -> tuple[OutboundReply, bool]:
            self.calls.append(
                {
                    "pending_action_id": pending_action_id,
                    "field_name": field_name,
                    "selected_value": selected_value,
                    "user_id": user_id,
                    "room_id": room_id,
                    "person_email": person_email,
                    "cancel": cancel,
                }
            )
            return OutboundReply(text="Selection applied.", room_id=room_id), True

    class FailApprovalManager:
        def approve_or_reject(self, decision: object) -> object:
            _ = decision
            raise AssertionError("approval manager should not handle entity selection")

    gateway = FakeGateway()
    orchestrator = FakeOrchestrator()
    controller = WebhookController(
        webhook_secret="secret",
        gateway=cast(WebexGateway, cast(object, gateway)),
        orchestrator=cast(Orchestrator, cast(object, orchestrator)),
        approval_manager=cast(ApprovalManager, cast(object, FailApprovalManager())),
        memory_store=InMemorySessionStore(),
    )

    asyncio.run(
        controller.process_attachment_action_event(
            {"id": "event-selection-1", "data": {"id": "action-selection-1"}}
        )
    )

    assert orchestrator.calls == [
        {
            "pending_action_id": "pending-1",
            "field_name": "target_device",
            "selected_value": "Board Pro",
            "user_id": "person-1",
            "room_id": "room-1",
            "person_email": "user@example.com",
            "cancel": False,
        }
    ]
    assert gateway.deleted_message_ids == ["message-selection-1"]
    assert [reply.text for reply in gateway.sent_replies] == ["Selection applied."]


def test_attachment_action_webhook_entity_selection_survives_person_email_lookup_failure() -> (
    None
):
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.webex_gateway import WebexAttachmentActionDetails
    from assistant_app.webhook_controller import WebhookController
    from shared.contracts import OutboundReply

    class FakeGateway:
        def __init__(self) -> None:
            self.deleted_message_ids: list[str] = []
            self.sent_replies: list[OutboundReply] = []

        async def fetch_attachment_action_details(
            self, action_id: str
        ) -> WebexAttachmentActionDetails:
            assert action_id == "action-selection-email-failure"
            return WebexAttachmentActionDetails(
                id=action_id,
                type="submit",
                messageId="message-selection-email-failure",
                personId="person-1",
                roomId="room-1",
                inputs={
                    "kind": "entity_selection",
                    "pendingActionId": "pending-email-failure",
                    "fieldName": "target_device",
                    "selectedValue": "Board Pro",
                    "selectionDecision": "submit",
                },
            )

        async def fetch_person_email(self, person_id: str) -> str | None:
            assert person_id == "person-1"
            raise RuntimeError("people lookup failed")

        async def delete_message(self, message_id: str) -> None:
            self.deleted_message_ids.append(message_id)

        async def send_reply(self, reply: OutboundReply) -> None:
            self.sent_replies.append(reply)

    class FakeOrchestrator:
        async def resume_pending_action_selection(
            self,
            pending_action_id: str,
            field_name: str,
            selected_value: str | None,
            user_id: str,
            room_id: str | None,
            person_email: str | None = None,
            *,
            cancel: bool = False,
        ) -> tuple[OutboundReply, bool]:
            assert pending_action_id == "pending-email-failure"
            assert field_name == "target_device"
            assert selected_value == "Board Pro"
            assert user_id == "person-1"
            assert room_id == "room-1"
            assert person_email is None
            assert cancel is False
            return OutboundReply(text="Selection applied.", room_id=room_id), True

    class FailApprovalManager:
        def approve_or_reject(self, decision: object) -> object:
            _ = decision
            raise AssertionError("approval manager should not handle entity selection")

    gateway = FakeGateway()
    memory_store = InMemorySessionStore()
    controller = WebhookController(
        webhook_secret="secret",
        gateway=cast(WebexGateway, cast(object, gateway)),
        orchestrator=cast(Orchestrator, cast(object, FakeOrchestrator())),
        approval_manager=cast(ApprovalManager, cast(object, FailApprovalManager())),
        memory_store=memory_store,
    )

    asyncio.run(
        controller.process_attachment_action_event(
            {
                "id": "event-selection-email-failure",
                "data": {"id": "action-selection-email-failure"},
            }
        )
    )

    assert gateway.deleted_message_ids == ["message-selection-email-failure"]
    assert [reply.text for reply in gateway.sent_replies] == ["Selection applied."]
    assert memory_store.has_processed_event("action-selection-email-failure") is True


def test_attachment_action_webhook_keeps_selection_card_when_wrong_user_attempts_submit() -> (
    None
):
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.webex_gateway import WebexAttachmentActionDetails
    from assistant_app.webhook_controller import WebhookController
    from shared.contracts import OutboundReply

    class FakeGateway:
        def __init__(self) -> None:
            self.deleted_message_ids: list[str] = []
            self.sent_replies: list[OutboundReply] = []

        async def fetch_attachment_action_details(
            self, action_id: str
        ) -> WebexAttachmentActionDetails:
            assert action_id == "action-selection-unauthorized"
            return WebexAttachmentActionDetails(
                id=action_id,
                type="submit",
                messageId="message-selection-unauthorized",
                personId="person-2",
                roomId="room-1",
                inputs={
                    "kind": "entity_selection",
                    "pendingActionId": "pending-2",
                    "fieldName": "target_device",
                    "selectedValue": "Board Pro",
                    "selectionDecision": "submit",
                },
            )

        async def fetch_person_email(self, person_id: str) -> str | None:
            assert person_id == "person-2"
            return "other@example.com"

        async def delete_message(self, message_id: str) -> None:
            self.deleted_message_ids.append(message_id)

        async def send_reply(self, reply: OutboundReply) -> None:
            self.sent_replies.append(reply)

    class FakeOrchestrator:
        async def resume_pending_action_selection(
            self,
            pending_action_id: str,
            field_name: str,
            selected_value: str | None,
            user_id: str,
            room_id: str | None,
            person_email: str | None = None,
            *,
            cancel: bool = False,
        ) -> tuple[OutboundReply, bool]:
            assert pending_action_id == "pending-2"
            assert field_name == "target_device"
            assert selected_value == "Board Pro"
            assert user_id == "person-2"
            assert room_id == "room-1"
            assert person_email == "other@example.com"
            assert cancel is False
            return OutboundReply(
                text="This selection card belongs to another user.",
                room_id=room_id,
            ), False

    class FailApprovalManager:
        def approve_or_reject(self, decision: object) -> object:
            _ = decision
            raise AssertionError("approval manager should not handle entity selection")

    gateway = FakeGateway()
    controller = WebhookController(
        webhook_secret="secret",
        gateway=cast(WebexGateway, cast(object, gateway)),
        orchestrator=cast(Orchestrator, cast(object, FakeOrchestrator())),
        approval_manager=cast(ApprovalManager, cast(object, FailApprovalManager())),
        memory_store=InMemorySessionStore(),
    )

    asyncio.run(
        controller.process_attachment_action_event(
            {
                "id": "event-selection-unauthorized",
                "data": {"id": "action-selection-unauthorized"},
            }
        )
    )

    assert gateway.deleted_message_ids == []
    assert [reply.text for reply in gateway.sent_replies] == [
        "This selection card belongs to another user."
    ]


def test_attachment_action_webhook_deletes_selection_card_on_cancel() -> None:
    from assistant_app.approval_manager import ApprovalManager
    from assistant_app.memory_store import InMemorySessionStore
    from assistant_app.orchestrator import Orchestrator
    from assistant_app.webex_gateway import WebexAttachmentActionDetails
    from assistant_app.webhook_controller import WebhookController
    from shared.contracts import OutboundReply

    class FakeGateway:
        def __init__(self) -> None:
            self.deleted_message_ids: list[str] = []
            self.sent_replies: list[OutboundReply] = []

        async def fetch_attachment_action_details(
            self, action_id: str
        ) -> WebexAttachmentActionDetails:
            assert action_id == "action-selection-cancel"
            return WebexAttachmentActionDetails(
                id=action_id,
                type="submit",
                messageId="message-selection-cancel",
                personId="person-1",
                roomId="room-1",
                inputs={
                    "kind": "entity_selection",
                    "pendingActionId": "pending-3",
                    "fieldName": "target_device",
                    "selectionDecision": "cancel",
                },
            )

        async def fetch_person_email(self, person_id: str) -> str | None:
            assert person_id == "person-1"
            return "user@example.com"

        async def delete_message(self, message_id: str) -> None:
            self.deleted_message_ids.append(message_id)

        async def send_reply(self, reply: OutboundReply) -> None:
            self.sent_replies.append(reply)

    class FakeOrchestrator:
        async def resume_pending_action_selection(
            self,
            pending_action_id: str,
            field_name: str,
            selected_value: str | None,
            user_id: str,
            room_id: str | None,
            person_email: str | None = None,
            *,
            cancel: bool = False,
        ) -> tuple[OutboundReply, bool]:
            assert pending_action_id == "pending-3"
            assert field_name == "target_device"
            assert selected_value is None
            assert user_id == "person-1"
            assert room_id == "room-1"
            assert person_email == "user@example.com"
            assert cancel is True
            return OutboundReply(
                text="Okay, I cancelled that request.", room_id=room_id
            ), True

    class FailApprovalManager:
        def approve_or_reject(self, decision: object) -> object:
            _ = decision
            raise AssertionError("approval manager should not handle entity selection")

    gateway = FakeGateway()
    controller = WebhookController(
        webhook_secret="secret",
        gateway=cast(WebexGateway, cast(object, gateway)),
        orchestrator=cast(Orchestrator, cast(object, FakeOrchestrator())),
        approval_manager=cast(ApprovalManager, cast(object, FailApprovalManager())),
        memory_store=InMemorySessionStore(),
    )

    asyncio.run(
        controller.process_attachment_action_event(
            {"id": "event-selection-cancel", "data": {"id": "action-selection-cancel"}}
        )
    )

    assert gateway.deleted_message_ids == ["message-selection-cancel"]
    assert [reply.text for reply in gateway.sent_replies] == [
        "Okay, I cancelled that request."
    ]


def test_device_client_list_devices_filters_non_main_or_non_xapi_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "webexDeviceId": "webex-device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "type": "roomdesk",
                        "permissions": ["xapi", "spark-admin:devices_read"],
                        "place": "HQ 7F",
                        "software": "RoomOS 11.0",
                        "serial": "SERIAL1",
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-2",
                        "displayName": "Board Pro Camera",
                        "product": "Quad Camera",
                        "type": "accessory",
                        "permissions": ["xapi"],
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-2b",
                        "displayName": "Board Pro Monitor",
                        "product": "GSM LG TV SSCR",
                        "type": "monitor",
                        "permissions": [],
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-2c",
                        "displayName": "Board Pro Mic",
                        "product": "Cisco Ceiling Microphone Pro",
                        "type": "microphone",
                        "permissions": [],
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-3",
                        "displayName": "Lobby Board",
                        "product": "Cisco Board Pro",
                        "type": "roomdesk",
                        "permissions": ["spark-admin:devices_read"],
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-4",
                        "displayName": "Phone 1",
                        "product": "Cisco Phone",
                        "type": "phone",
                        "permissions": ["xapi"],
                        "connectionStatus": "connected",
                    },
                ]
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    devices = asyncio.run(device_client.list_devices())

    assert [device.display_name for device in devices] == ["Board Pro"]
    assert devices[0].device_type == "roomdesk"
    assert devices[0].permissions == ["xapi", "spark-admin:devices_read"]
    assert devices[0].webex_device_id == "webex-device-1"


def test_device_resolution_candidates_exclude_accessories_and_non_xapi_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup_client = QueuedAsyncClient()
    lookup_client.responses.append(make_response("GET", "/devices", 200, {"items": []}))
    lookup_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "product": "Cisco Board Pro",
                        "type": "roomdesk",
                        "permissions": ["xapi"],
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-2",
                        "displayName": "Board Pro Camera",
                        "product": "Quad Camera",
                        "type": "accessory",
                        "permissions": ["xapi"],
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-2b",
                        "displayName": "Board Pro Monitor",
                        "product": "GSM LG TV SSCR",
                        "type": "monitor",
                        "permissions": [],
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-2c",
                        "displayName": "Board Pro Mic",
                        "product": "Cisco Ceiling Microphone Pro",
                        "type": "microphone",
                        "permissions": [],
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-3",
                        "displayName": "Lobby Board",
                        "product": "Cisco Board Pro",
                        "type": "roomdesk",
                        "permissions": ["spark-admin:devices_read"],
                        "connectionStatus": "connected",
                    },
                ]
            },
        )
    )
    _ = build_client_queue(lookup_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(DeviceResolutionError) as exc_info:
        _ = asyncio.run(device_client.get_status("Unknown Room"))

    assert exc_info.value.reason == "not_found"
    assert [device.display_name for device in exc_info.value.candidate_devices] == [
        "Board Pro"
    ]


def test_device_client_prefers_webex_device_id_for_device_configuration_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_client = QueuedAsyncClient()
    resolve_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "workspace-device-record-1",
                        "webexDeviceId": "webex-device-1",
                        "displayName": "Board Pro",
                        "product": "Cisco Board Pro",
                        "type": "roomdesk",
                        "permissions": ["xapi"],
                        "connectionStatus": "connected",
                    }
                ]
            },
        )
    )
    config_client = QueuedAsyncClient()
    config_client.responses.append(
        make_response("PATCH", "/deviceConfigurations", 200, [])
    )
    _ = build_client_queue(resolve_client, config_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(
        device_client.set_display_role("Board Pro", 2, "presentation-only")
    )

    assert "Board Pro" in result
    assert config_client.requests == [
        (
            "PATCH",
            "/deviceConfigurations",
            {
                "headers": {
                    "Authorization": "Bearer bot-token",
                    "Content-Type": "application/json-patch+json",
                },
                "params": {"deviceId": "webex-device-1"},
                "json": [
                    {
                        "op": "replace",
                        "path": "Video.Output.Connector[2].MonitorRole/sources/configured/value",
                        "value": "PresentationOnly",
                    }
                ],
            },
        )
    ]


def test_device_client_resolves_home_office_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Home Office",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Desk Pro",
                        "place": None,
                        "connectionStatus": "connected",
                    }
                ]
            },
        )
    )
    command_client = QueuedAsyncClient()
    command_client.responses.append(
        make_response("POST", "/xapi/command/Dial", 200, {"status": "OK"})
    )
    _ = build_client_queue(api_client, command_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.dial("홈오피스", "youngcle@cisco.com"))

    assert result == "Dial requested to youngcle@cisco.com on Home Office."
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Home Office"},
            },
        )
    ]
    assert command_client.requests == [
        (
            "POST",
            "/xapi/command/Dial",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "deviceId": "device-1",
                    "arguments": {"Number": "youngcle@cisco.com"},
                },
            },
        )
    ]


def test_device_client_get_camera_mode_uses_official_status_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.get_camera_mode("Board Pro"))

    assert result.current_mode == "frames"
    assert result.effective_mode == "frames"
    assert result.available_modes == ["best_overview", "speaker_closeup", "frames"]
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Audio.Volume"),
                    ("name", "Audio.Microphones.MusicMode"),
                    ("name", "Audio.Microphones.NoiseRemoval"),
                    ("name", "Call[*].Status"),
                    ("name", "Cameras.PresenterTrack.Availability"),
                    ("name", "Cameras.PresenterTrack.Status"),
                    ("name", "Cameras.SpeakerTrack.Availability"),
                    ("name", "Cameras.SpeakerTrack.Closeup.Status"),
                    ("name", "Cameras.SpeakerTrack.Frames.Availability"),
                    ("name", "Cameras.SpeakerTrack.Frames.Status"),
                ),
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Cameras.SpeakerTrack.State"),
                    ("name", "Conference.Presentation.LocalInstance[*].SendingMode"),
                    ("name", "Standby.State"),
                    ("name", "SystemUnit.Hardware.Module.SerialNumber"),
                    ("name", "SystemUnit.ProductId"),
                    ("name", "SystemUnit.Software.Version"),
                    ("name", "SystemUnit.State.NumberOfActiveCalls"),
                    ("name", "Video.Monitors"),
                ),
            },
        ),
    ]


def test_device_client_set_camera_mode_frames_uses_patch_and_activate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                        "Status": "Inactive",
                    },
                }
            },
        )
    )
    api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
    patch_client = QueuedAsyncClient()
    patch_client.responses.append(
        make_response("PATCH", "/deviceConfigurations", 200, [])
    )
    command_client_one = QueuedAsyncClient()
    command_client_one.responses.append(
        make_response(
            "POST", "/xapi/command/Cameras.SpeakerTrack.Activate", 200, {"status": "OK"}
        )
    )
    command_client_two = QueuedAsyncClient()
    command_client_two.responses.append(
        make_response(
            "POST",
            "/xapi/command/Cameras.SpeakerTrack.Frames.Activate",
            200,
            {"status": "OK"},
        )
    )
    _ = build_client_queue(
        api_client,
        patch_client,
        command_client_one,
        command_client_two,
    )
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.set_camera_mode("Board Pro", "frames"))

    assert result == "Set camera mode to frames on Board Pro."
    assert patch_client.requests == [
        (
            "PATCH",
            "/deviceConfigurations",
            {
                "headers": {
                    "Authorization": "Bearer bot-token",
                    "Content-Type": "application/json-patch+json",
                },
                "params": {"deviceId": "device-1"},
                "json": [
                    {
                        "op": "replace",
                        "path": "Cameras.SpeakerTrack.Mode/sources/configured/value",
                        "value": "Auto",
                    },
                    {
                        "op": "replace",
                        "path": "Cameras.SpeakerTrack.Frames.Mode/sources/configured/value",
                        "value": "Auto",
                    },
                ],
            },
        )
    ]
    assert command_client_one.requests == [
        (
            "POST",
            "/xapi/command/Cameras.SpeakerTrack.Activate",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {"deviceId": "device-1"},
            },
        )
    ]
    assert command_client_two.requests == [
        (
            "POST",
            "/xapi/command/Cameras.SpeakerTrack.Frames.Activate",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {"deviceId": "device-1"},
            },
        )
    ]


def test_device_client_set_camera_mode_speaker_closeup_clears_frames_and_activates_closeup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                        "State": "Frames",
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
    patch_client = QueuedAsyncClient()
    patch_client.responses.append(
        make_response("PATCH", "/deviceConfigurations", 200, [])
    )
    command_client_one = QueuedAsyncClient()
    command_client_one.responses.append(
        make_response(
            "POST", "/xapi/command/Cameras.SpeakerTrack.Activate", 200, {"status": "OK"}
        )
    )
    command_client_two = QueuedAsyncClient()
    command_client_two.responses.append(
        make_response(
            "POST",
            "/xapi/command/Cameras.SpeakerTrack.Closeup.Activate",
            200,
            {"status": "OK"},
        )
    )
    _ = build_client_queue(
        api_client,
        patch_client,
        command_client_one,
        command_client_two,
    )
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.set_camera_mode("Board Pro", "speaker_closeup"))

    assert result == "Set camera mode to speaker_closeup on Board Pro."
    assert patch_client.requests == [
        (
            "PATCH",
            "/deviceConfigurations",
            {
                "headers": {
                    "Authorization": "Bearer bot-token",
                    "Content-Type": "application/json-patch+json",
                },
                "params": {"deviceId": "device-1"},
                "json": [
                    {
                        "op": "replace",
                        "path": "Cameras.SpeakerTrack.Mode/sources/configured/value",
                        "value": "Auto",
                    },
                    {
                        "op": "replace",
                        "path": "Cameras.SpeakerTrack.Frames.Mode/sources/configured/value",
                        "value": "Off",
                    },
                ],
            },
        )
    ]
    assert command_client_one.requests == [
        (
            "POST",
            "/xapi/command/Cameras.SpeakerTrack.Activate",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {"deviceId": "device-1"},
            },
        )
    ]
    assert command_client_two.requests == [
        (
            "POST",
            "/xapi/command/Cameras.SpeakerTrack.Closeup.Activate",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {"deviceId": "device-1"},
            },
        )
    ]


def test_device_client_set_camera_mode_rejects_unavailable_mode_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                            "Availability": "Unavailable",
                            "Status": "Inactive",
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
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(
        RuntimeError,
        match="Cannot set camera mode to frames on Board Pro because the device reports available writable camera modes: best_overview, speaker_closeup.",
    ):
        _ = asyncio.run(device_client.set_camera_mode("Board Pro", "frames"))


def test_device_client_get_camera_mode_does_not_infer_effective_mode_when_nothing_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
                        "State": "Off",
                        "Closeup": {"Status": "Inactive"},
                        "Frames": {
                            "Availability": "Available",
                            "Status": "Inactive",
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
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.get_camera_mode("Board Pro"))

    assert result.current_mode is None
    assert result.effective_mode is None
    assert result.available_modes == ["best_overview", "speaker_closeup", "frames"]


def test_device_client_get_environment_info_uses_official_status_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "connectionStatus": "connected",
                    }
                ]
            },
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {
                "RoomAnalytics": {
                    "AmbientTemperature": 22.0,
                    "RelativeHumidity": 41,
                    "AmbientNoise": {"Level": {"A": 36.5}},
                    "PeopleCount": {"Current": 3},
                },
                "Peripherals": {
                    "ConnectedDevice": [
                        {"RoomAnalytics": {"AirQuality": {"Index": 79}}}
                    ]
                },
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.get_environment_info("Board Pro"))

    assert result.temperature_celsius == 22.0
    assert result.relative_humidity_percent == 41.0
    assert result.ambient_noise_db == 36.5
    assert result.people_count == 3
    assert result.air_quality_index == 79
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "RoomAnalytics.AmbientTemperature"),
                    ("name", "RoomAnalytics.RelativeHumidity"),
                    ("name", "RoomAnalytics.AmbientNoise.Level.A"),
                    ("name", "RoomAnalytics.PeopleCount.Current"),
                    (
                        "name",
                        "Peripherals.ConnectedDevice[*].RoomAnalytics.AirQuality.Index",
                    ),
                    (
                        "name",
                        "Peripherals.ConnectedDevice[*].RoomAnalytics.AmbientTemperature",
                    ),
                    (
                        "name",
                        "Peripherals.ConnectedDevice[*].RoomAnalytics.RelativeHumidity",
                    ),
                ),
            },
        ),
    ]


def test_device_client_get_environment_info_uses_peripheral_fallbacks_for_temperature_and_humidity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {
                "Peripherals": {
                    "ConnectedDevice": [
                        {
                            "RoomAnalytics": {
                                "AmbientTemperature": 20.5,
                                "RelativeHumidity": 47,
                            }
                        }
                    ]
                }
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(client.get_environment_info("Desk Pro"))

    assert result.temperature_celsius == 20.5
    assert result.relative_humidity_percent == 47.0
    assert result.ambient_noise_db is None
    assert result.people_count is None
    assert result.air_quality_index is None


def test_device_client_get_environment_info_returns_best_effort_none_for_missing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(client.get_environment_info("Desk Pro"))

    assert result.temperature_celsius is None
    assert result.relative_humidity_percent is None
    assert result.ambient_noise_db is None
    assert result.people_count is None
    assert result.air_quality_index is None


def test_device_client_get_room_booking_uses_official_status_and_list_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                "Bookings": {
                    "Availability": {
                        "Status": "Booked",
                        "TimeStamp": "2026-04-23T09:25:00Z",
                    },
                    "Current": {"Id": "booking-current"},
                }
            },
        )
    )
    api_client.responses.append(
        make_response(
            "POST",
            "/xapi/command/Bookings.List",
            200,
            {
                "Bookings": {
                    "ListResult": {
                        "Booking": [
                            {
                                "Id": "booking-next",
                                "Title": "Weekly Staff Meeting",
                                "StartTime": "2026-04-23T09:30:00Z",
                                "EndTime": "2026-04-23T10:00:00Z",
                                "WebexMeetingNumber": "987654321",
                                "Service": "Webex",
                            }
                        ]
                    }
                }
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(client.get_room_booking("Board Pro"))

    assert result.availability_status == "Booked"
    assert result.availability_timestamp == "2026-04-23T09:25:00Z"
    assert result.current_booking_id == "booking-current"
    assert result.is_booked_now is True
    assert result.next_booking_id == "booking-next"
    assert result.next_meeting_title == "Weekly Staff Meeting"
    assert result.next_meeting_start_time == "2026-04-23T09:30:00Z"
    assert result.next_meeting_end_time == "2026-04-23T10:00:00Z"
    assert result.obtp_available is True
    assert result.obtp_join_method == "webex"
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Bookings.Availability.Status"),
                    ("name", "Bookings.Availability.TimeStamp"),
                    ("name", "Bookings.Current.Id"),
                ),
            },
        ),
        (
            "POST",
            "/xapi/command/Bookings.List",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "deviceId": "device-1",
                    "arguments": {"ScheduleType": "Upcoming"},
                },
            },
        ),
    ]


def test_device_client_get_room_booking_returns_best_effort_none_for_sparse_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
    api_client.responses.append(
        make_response(
            "POST",
            "/xapi/command/Bookings.List",
            200,
            {"Bookings": {"ListResult": {"Booking": []}}},
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(client.get_room_booking("Desk Pro"))

    assert result.availability_status is None
    assert result.availability_timestamp is None
    assert result.current_booking_id is None
    assert result.is_booked_now is None
    assert result.next_booking_id is None
    assert result.next_meeting_title is None
    assert result.next_meeting_start_time is None
    assert result.next_meeting_end_time is None
    assert result.obtp_available is None
    assert result.obtp_join_method is None


def test_device_client_get_room_booking_keeps_next_meeting_when_joinability_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            {"Bookings": {"Availability": {"Status": "Available"}}},
        )
    )
    api_client.responses.append(
        make_response(
            "POST",
            "/xapi/command/Bookings.List",
            200,
            {
                "Bookings": {
                    "ListResult": {
                        "Booking": [
                            {
                                "Id": "booking-next",
                                "Title": "Project Sync",
                                "StartTime": "2026-04-23T10:00:00Z",
                                "EndTime": "2026-04-23T10:30:00Z",
                            }
                        ]
                    }
                }
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(client.get_room_booking("Board Pro"))

    assert result.next_booking_id == "booking-next"
    assert result.next_meeting_title == "Project Sync"
    assert result.obtp_available is None
    assert result.obtp_join_method is None


def test_device_client_get_room_booking_does_not_infer_joinability_from_title_only_mentions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
    api_client.responses.append(
        make_response(
            "POST",
            "/xapi/command/Bookings.List",
            200,
            {
                "Bookings": {
                    "ListResult": {
                        "Booking": [
                            {
                                "Id": "booking-zoom-title",
                                "Title": "Zoom Weekly Sync",
                                "StartTime": "2026-04-23T11:00:00Z",
                                "EndTime": "2026-04-23T11:30:00Z",
                            }
                        ]
                    }
                }
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(client.get_room_booking("Desk Pro"))

    assert result.next_booking_id == "booking-zoom-title"
    assert result.next_meeting_title == "Zoom Weekly Sync"
    assert result.obtp_available is None
    assert result.obtp_join_method is None


def test_device_client_join_obtp_fails_when_booking_has_ambiguous_explicit_join_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    api_client.responses.append(
        make_response(
            "POST",
            "/xapi/command/Bookings.List",
            200,
            {
                "Bookings": {
                    "ListResult": {
                        "Booking": [
                            {
                                "Id": "booking-ambiguous",
                                "Title": "Mixed platform meeting",
                                "StartTime": "2026-04-23T09:30:00Z",
                                "WebexMeetingNumber": "123456789",
                                "ZoomMeetingNumber": "999888777",
                            }
                        ]
                    }
                }
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(
        RuntimeError,
        match="No confidently joinable upcoming booking was found on Desk Pro.",
    ):
        _ = asyncio.run(client.join_obtp("Desk Pro"))


def test_device_client_join_obtp_fails_when_no_confident_joinable_booking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    api_client.responses.append(
        make_response(
            "POST",
            "/xapi/command/Bookings.List",
            200,
            {
                "Bookings": {
                    "ListResult": {
                        "Booking": [
                            {
                                "Id": "booking-1",
                                "Title": "Ambiguous meeting",
                                "StartTime": "2026-04-23T09:30:00Z",
                                "Number": "123456",
                            }
                        ]
                    }
                }
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(
        RuntimeError,
        match="No confidently joinable upcoming booking was found on Desk Pro.",
    ):
        _ = asyncio.run(client.join_obtp("Desk Pro"))


def test_device_client_get_environment_info_retries_status_names_individually_after_batch_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    batch_request = httpx.Request("GET", "https://webexapis.com/v1/xapi/status")
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"RoomAnalytics": {"AmbientTemperature": 23.0}},
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"RoomAnalytics": {"RelativeHumidity": 40}},
        )
    )
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {
                "Peripherals": {
                    "ConnectedDevice": [
                        {"RoomAnalytics": {"AirQuality": {"Index": 67}}}
                    ]
                }
            },
        )
    )
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(client.get_environment_info("Desk Pro"))

    assert result.temperature_celsius == 23.0
    assert result.relative_humidity_percent == 40.0
    assert result.ambient_noise_db is None
    assert result.people_count is None
    assert result.air_quality_index == 67


def test_reconcile_reuses_matching_messages_created_webhook() -> None:
    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            webex_webhook_target_url="https://example.com/webhooks/webex/messages",
            webex_webhook_reconcile_on_startup=True,
        ),
    )
    expected = WebexWebhookRecord(
        id="hook-1",
        name="webex-device-assistant-messages-created-direct",
        targetUrl="https://example.com/webhooks/webex/messages",
        resource="messages",
        event="created",
        filter="roomType=direct",
    )

    expected_group = WebexWebhookRecord(
        id="hook-2",
        name="webex-device-assistant-messages-created-group-mention",
        targetUrl="https://example.com/webhooks/webex/messages",
        resource="messages",
        event="created",
        filter="roomType=group&mentionedPeople=me",
    )

    async def fake_list() -> list[WebexWebhookRecord]:
        return [expected, expected_group]

    async def fake_delete(webhook_id: str) -> None:
        raise AssertionError(f"unexpected delete for {webhook_id}")

    async def fake_create(
        registration: WebexWebhookRegistration,
    ) -> WebexWebhookRecord:
        raise AssertionError(f"unexpected create for {registration.name}")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gateway, "list_webhooks", fake_list)
    monkeypatch.setattr(gateway, "delete_webhook", fake_delete)
    monkeypatch.setattr(gateway, "create_webhook", fake_create)
    try:
        reconciled = asyncio.run(gateway.reconcile_messages_webhook())
    finally:
        monkeypatch.undo()

    assert reconciled == expected


def test_reconcile_replaces_stale_messages_created_webhooks() -> None:
    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            webex_webhook_target_url="https://example.com/webhooks/webex/messages",
            webex_webhook_reconcile_on_startup=True,
        ),
    )
    deleted_ids: list[str] = []

    async def fake_list() -> list[WebexWebhookRecord]:
        return [
            WebexWebhookRecord(
                id="hook-old-direct",
                name="webex-device-assistant-messages-created-direct",
                targetUrl="https://old.example.com/webhooks/webex/messages",
                resource="messages",
                event="created",
                filter="roomType=direct",
            ),
            WebexWebhookRecord(
                id="hook-old-group",
                name="webex-device-assistant-messages-created-group-mention",
                targetUrl="https://old.example.com/webhooks/webex/messages",
                resource="messages",
                event="created",
                filter="roomType=group&mentionedPeople=me",
            ),
        ]

    async def fake_delete(webhook_id: str) -> None:
        deleted_ids.append(webhook_id)

    async def fake_create(
        registration: WebexWebhookRegistration,
    ) -> WebexWebhookRecord:
        assert registration.name in {
            "webex-device-assistant-messages-created-direct",
            "webex-device-assistant-messages-created-group-mention",
        }
        return WebexWebhookRecord(
            id=f"hook-new-{registration.name}",
            name=registration.name,
            targetUrl=registration.target_url,
            resource=registration.resource,
            event=registration.event,
            filter=registration.filter,
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gateway, "list_webhooks", fake_list)
    monkeypatch.setattr(gateway, "delete_webhook", fake_delete)
    monkeypatch.setattr(gateway, "create_webhook", fake_create)
    try:
        reconciled = asyncio.run(gateway.reconcile_messages_webhook())
    finally:
        monkeypatch.undo()

    assert deleted_ids == ["hook-old-direct", "hook-old-group"]
    assert reconciled is not None
    assert reconciled.id == "hook-new-webex-device-assistant-messages-created-direct"


def test_reconcile_preserves_unowned_messages_created_webhooks() -> None:
    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            webex_webhook_target_url="https://example.com/webhooks/webex/messages",
            webex_webhook_reconcile_on_startup=True,
        ),
    )
    deleted_ids: list[str] = []

    async def fake_list() -> list[WebexWebhookRecord]:
        return [
            WebexWebhookRecord(
                id="foreign-hook",
                name="another-app-webhook",
                targetUrl="https://another.example.com/webhooks/webex/messages",
                resource="messages",
                event="created",
                filter="roomType=direct",
            )
        ]

    async def fake_delete(webhook_id: str) -> None:
        deleted_ids.append(webhook_id)

    async def fake_create(
        registration: WebexWebhookRegistration,
    ) -> WebexWebhookRecord:
        return WebexWebhookRecord(
            id="hook-new",
            name=registration.name,
            targetUrl=registration.target_url,
            resource=registration.resource,
            event=registration.event,
            filter=registration.filter,
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gateway, "list_webhooks", fake_list)
    monkeypatch.setattr(gateway, "delete_webhook", fake_delete)
    monkeypatch.setattr(gateway, "create_webhook", fake_create)
    try:
        reconciled = asyncio.run(gateway.reconcile_messages_webhook())
    finally:
        monkeypatch.undo()

    assert deleted_ids == []
    assert reconciled is not None
    assert reconciled.id == "hook-new"


def test_startup_reconcile_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    async def fake_resolve_identity(_self: WebexGateway) -> object:
        return None

    async def fake_reconcile(self: WebexGateway) -> list[WebexWebhookRecord]:
        calls.append(self.config.webex_webhook_reconcile_on_startup)
        return []

    async def fake_reconcile_attachment_actions(
        self: WebexGateway,
    ) -> WebexWebhookRecord | None:
        calls.append(self.config.webex_webhook_reconcile_on_startup)
        return None

    monkeypatch.setattr(WebexGateway, "resolve_bot_identity", fake_resolve_identity)
    monkeypatch.setattr(WebexGateway, "reconcile_messages_webhooks", fake_reconcile)
    monkeypatch.setattr(
        WebexGateway,
        "reconcile_attachment_action_webhook",
        fake_reconcile_attachment_actions,
    )

    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
        }
    ):
        app = build_app()
        with TestClient(app):
            pass

    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
            "WEBEX_WEBHOOK_RECONCILE_ON_STARTUP": "true",
            "WEBEX_WEBHOOK_TARGET_URL": "https://example.com/webhooks/webex/messages",
        }
    ):
        app = build_app()
        with TestClient(app):
            pass

    assert calls == [True, True]


def test_startup_reconcile_failure_does_not_block_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_identity(_self: WebexGateway) -> object:
        return None

    async def fake_reconcile(_self: WebexGateway) -> list[WebexWebhookRecord]:
        raise RuntimeError("rate limited")

    async def fake_reconcile_attachment_actions(
        _self: WebexGateway,
    ) -> WebexWebhookRecord | None:
        raise AssertionError(
            "unexpected attachment-actions reconcile call after failure"
        )

    monkeypatch.setattr(WebexGateway, "resolve_bot_identity", fake_resolve_identity)
    monkeypatch.setattr(WebexGateway, "reconcile_messages_webhooks", fake_reconcile)
    monkeypatch.setattr(
        WebexGateway,
        "reconcile_attachment_action_webhook",
        fake_reconcile_attachment_actions,
    )

    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
            "WEBEX_WEBHOOK_RECONCILE_ON_STARTUP": "true",
            "WEBEX_WEBHOOK_TARGET_URL": "https://example.com/webhooks/webex/messages",
        }
    ):
        with TestClient(build_app()) as client:
            response = client.get("/healthz")

    assert response.status_code == 200


def test_webhook_endpoint_verifies_signature_and_processes_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_replies: list[str] = []

    async def fake_resolve_identity(_self: WebexGateway) -> object:
        return None

    async def fake_reconcile(_self: WebexGateway) -> list[WebexWebhookRecord]:
        return []

    async def fake_fetch(_self: WebexGateway, envelope: WebexWebhookEnvelope) -> object:
        from shared.contracts import InboundUserMessage, MessageSource

        return InboundUserMessage(
            session_id=envelope.data.roomId or envelope.id,
            user_id="person-1",
            text="get status of Board Pro",
            source=MessageSource.WEBEX,
            room_id=envelope.data.roomId,
            person_email="user@example.com",
            event_id=envelope.id,
        )

    async def fake_send(_self: WebexGateway, reply: OutboundReply) -> None:
        sent_replies.append(reply.text)

    monkeypatch.setattr(WebexGateway, "resolve_bot_identity", fake_resolve_identity)
    monkeypatch.setattr(WebexGateway, "reconcile_messages_webhooks", fake_reconcile)
    monkeypatch.setattr(WebexGateway, "fetch_inbound_message", fake_fetch)
    monkeypatch.setattr(WebexGateway, "send_reply", fake_send)

    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
        }
    ):
        with TestClient(build_app()) as client:
            payload = {
                "id": "event-1",
                "resource": "messages",
                "event": "created",
                "data": {"id": "message-1", "roomId": "room-1", "personId": "person-1"},
            }
            raw_body = json.dumps(payload).encode("utf-8")
            signature = hmac.new(b"secret", raw_body, hashlib.sha1).hexdigest()

            response = client.post(
                "/webhooks/webex/messages",
                content=raw_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Spark-Signature": signature,
                },
            )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "event_id": "event-1"}
    assert len(sent_replies) == 1
    assert "Board Pro" in sent_replies[0]


def test_startup_identity_resolution_failure_does_not_block_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_identity(_self: WebexGateway) -> object:
        raise RuntimeError("temporary people/me failure")

    monkeypatch.setattr(WebexGateway, "resolve_bot_identity", fake_resolve_identity)

    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
        }
    ):
        with TestClient(build_app()) as client:
            response = client.get("/healthz")

    assert response.status_code == 200


def test_startup_identity_mismatch_blocks_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_identity(_self: WebexGateway) -> object:
        raise WebexBotIdentityMismatchError("configured mismatch")

    monkeypatch.setattr(WebexGateway, "resolve_bot_identity", fake_resolve_identity)

    with temporary_env(
        {
            "WEBEX_MOCK_MODE": "false",
            "WEBEX_BOT_TOKEN": "bot-token",
            "WEBEX_BOT_PERSON_ID": "bot-person-id",
            "WEBEX_WEBHOOK_SECRET": "secret",
        }
    ):
        with pytest.raises(WebexBotIdentityMismatchError, match="configured mismatch"):
            with TestClient(build_app()):
                pass


def test_process_message_event_retries_same_event_after_send_failure() -> None:
    app = build_app()
    services = app.state.services
    gateway = services.webex_gateway
    controller = services.webhook_controller
    memory_store = services.webhook_controller.memory_store

    send_attempts: list[str] = []

    async def fake_fetch(
        _self: WebexGateway, envelope: WebexWebhookEnvelope
    ) -> InboundUserMessage:
        return InboundUserMessage(
            session_id=envelope.data.roomId or envelope.id,
            user_id="person-1",
            text="hi",
            source=MessageSource.WEBEX,
            room_id=envelope.data.roomId,
            person_email="user@example.com",
            event_id=envelope.id,
        )

    async def fake_send(_self: WebexGateway, reply: OutboundReply) -> None:
        send_attempts.append(reply.text)
        if len(send_attempts) == 1:
            raise RuntimeError("temporary send failure")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        gateway, "fetch_inbound_message", fake_fetch.__get__(gateway, WebexGateway)
    )
    monkeypatch.setattr(gateway, "send_reply", fake_send.__get__(gateway, WebexGateway))
    try:
        event = gateway.parse_webhook_payload(
            {
                "id": "event-retry-1",
                "resource": "messages",
                "event": "created",
                "data": {"id": "message-1", "roomId": "room-1", "personId": "person-1"},
            }
        )

        asyncio.run(controller.process_message_event(event))
        assert memory_store.has_processed_event("message-1") is False

        asyncio.run(controller.process_message_event(event))
        assert memory_store.has_processed_event("message-1") is True
    finally:
        monkeypatch.undo()

    assert len(send_attempts) == 2


def test_process_message_event_uses_message_id_for_dedupe() -> None:
    app = build_app()
    services = app.state.services
    gateway = services.webex_gateway
    controller = services.webhook_controller

    send_attempts: list[str] = []

    async def fake_fetch(
        _self: WebexGateway, envelope: WebexWebhookEnvelope
    ) -> InboundUserMessage:
        return InboundUserMessage(
            session_id=envelope.data.roomId or envelope.id,
            user_id=envelope.data.personId or "person-1",
            text=f"message:{envelope.data.id}",
            source=MessageSource.WEBEX,
            room_id=envelope.data.roomId,
            person_email="user@example.com",
            event_id=envelope.id,
        )

    async def fake_send(_self: WebexGateway, reply: OutboundReply) -> None:
        send_attempts.append(reply.text)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        gateway, "fetch_inbound_message", fake_fetch.__get__(gateway, WebexGateway)
    )
    monkeypatch.setattr(gateway, "send_reply", fake_send.__get__(gateway, WebexGateway))
    try:
        first_event = gateway.parse_webhook_payload(
            {
                "id": "shared-event-id",
                "resource": "messages",
                "event": "created",
                "data": {"id": "message-a", "roomId": "room-1", "personId": "person-1"},
            }
        )
        second_event = gateway.parse_webhook_payload(
            {
                "id": "shared-event-id",
                "resource": "messages",
                "event": "created",
                "data": {"id": "message-b", "roomId": "room-1", "personId": "person-1"},
            }
        )

        asyncio.run(controller.process_message_event(first_event))
        asyncio.run(controller.process_message_event(second_event))
    finally:
        monkeypatch.undo()

    assert len(send_attempts) == 2
    assert send_attempts[0].strip()
    assert send_attempts[1].strip()


def test_gateway_drops_self_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_client = QueuedAsyncClient()
    fetch_client.responses.append(
        make_response(
            "GET",
            "/messages/message-1",
            200,
            {
                "id": "message-1",
                "roomId": "room-1",
                "personId": "bot-person-id",
                "personEmail": "bot@example.com",
                "text": "get status of Board Pro",
            },
        )
    )
    _ = build_client_queue(fetch_client)
    monkeypatch.setattr(
        "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
    )

    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
        ),
    )
    event = gateway.parse_webhook_payload(
        {
            "id": "event-1",
            "resource": "messages",
            "event": "created",
            "data": {"id": "message-1", "roomId": "room-1", "personId": "user-1"},
        }
    )

    inbound = asyncio.run(gateway.fetch_inbound_message(event))

    assert inbound is None


def test_gateway_drops_empty_fetched_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_client = QueuedAsyncClient()
    fetch_client.responses.append(
        make_response(
            "GET",
            "/messages/message-1",
            200,
            {
                "id": "message-1",
                "roomId": "room-1",
                "personId": "user-1",
                "personEmail": "user@example.com",
                "text": "   ",
            },
        )
    )
    _ = build_client_queue(fetch_client)
    monkeypatch.setattr(
        "assistant_app.webex_gateway.httpx.AsyncClient", async_client_factory
    )

    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
        ),
    )
    event = gateway.parse_webhook_payload(
        {
            "id": "event-1",
            "resource": "messages",
            "event": "created",
            "data": {"id": "message-1", "roomId": "room-1", "personId": "user-1"},
        }
    )

    inbound = asyncio.run(gateway.fetch_inbound_message(event))

    assert inbound is None


def test_reconcile_creates_both_desired_webhooks() -> None:
    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            webex_webhook_target_url="https://example.com/webhooks/webex/messages",
            webex_webhook_reconcile_on_startup=True,
        ),
    )
    created_filters: list[str | None] = []

    async def fake_list() -> list[WebexWebhookRecord]:
        return []

    async def fake_delete(webhook_id: str) -> None:
        raise AssertionError(f"unexpected delete for {webhook_id}")

    async def fake_create(
        registration: WebexWebhookRegistration,
    ) -> WebexWebhookRecord:
        created_filters.append(registration.filter)
        return WebexWebhookRecord(
            id=f"hook-{registration.name}",
            name=registration.name,
            targetUrl=registration.target_url,
            resource=registration.resource,
            event=registration.event,
            filter=registration.filter,
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gateway, "list_webhooks", fake_list)
    monkeypatch.setattr(gateway, "delete_webhook", fake_delete)
    monkeypatch.setattr(gateway, "create_webhook", fake_create)
    try:
        reconciled = asyncio.run(gateway.reconcile_messages_webhooks())
    finally:
        monkeypatch.undo()

    assert created_filters == [
        "roomType=direct",
        "roomType=group&mentionedPeople=me",
    ]
    assert [webhook.filter for webhook in reconciled] == created_filters


def test_desired_attachment_action_webhook_targets_attachment_actions_endpoint() -> (
    None
):
    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            webex_webhook_target_url="https://example.com/webhooks/webex/messages",
            webex_webhook_reconcile_on_startup=True,
        ),
    )

    registration = gateway.desired_attachment_action_webhook()

    assert registration.name == "webex-device-assistant-attachment-actions"
    assert registration.resource == "attachmentActions"
    assert registration.event == "created"
    assert registration.filter is None
    assert (
        registration.target_url
        == "https://example.com/webhooks/webex/attachment-actions"
    )


def test_reconcile_creates_attachment_action_webhook() -> None:
    gateway = WebexGateway(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_token="bot-token",
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            webex_webhook_target_url="https://example.com/webhooks/webex/messages",
            webex_webhook_reconcile_on_startup=True,
        ),
    )

    async def fake_list() -> list[WebexWebhookRecord]:
        return []

    async def fake_delete(webhook_id: str) -> None:
        raise AssertionError(f"unexpected delete for {webhook_id}")

    async def fake_create(
        registration: WebexWebhookRegistration,
    ) -> WebexWebhookRecord:
        assert registration.name == "webex-device-assistant-attachment-actions"
        assert registration.resource == "attachmentActions"
        assert registration.event == "created"
        assert registration.filter is None
        assert (
            registration.target_url
            == "https://example.com/webhooks/webex/attachment-actions"
        )
        return WebexWebhookRecord(
            id="hook-attachment-actions",
            name=registration.name,
            targetUrl=registration.target_url,
            resource=registration.resource,
            event=registration.event,
            filter=registration.filter,
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gateway, "list_webhooks", fake_list)
    monkeypatch.setattr(gateway, "delete_webhook", fake_delete)
    monkeypatch.setattr(gateway, "create_webhook", fake_create)
    try:
        reconciled = asyncio.run(gateway.reconcile_attachment_action_webhook())
    finally:
        monkeypatch.undo()

    assert reconciled is not None
    assert reconciled.id == "hook-attachment-actions"


def test_device_client_fetches_webex_cloud_xapi_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                    }
                ]
            },
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {
                "Audio": {
                    "Volume": 55,
                    "VolumeMute": "Off",
                    "Microphones": {"Mute": "On"},
                },
                "Call": [{"Status": "Connected"}],
                "Conference": {
                    "Presentation": {
                        "Mode": "Sending",
                        "LocalInstance": [{"SendingMode": "LocalRemote"}],
                    }
                },
                "Cameras": {
                    "PresenterTrack": {
                        "Availability": "Available",
                        "Status": "Inactive",
                    },
                    "SpeakerTrack": {
                        "Availability": "Available",
                        "Closeup": {"Status": "Inactive"},
                        "Frames": {"Availability": "Available", "Status": "Inactive"},
                        "State": "Active",
                    },
                },
                "Network": [
                    {
                        "ActiveInterface": "ethernet",
                        "IPv4": {"Address": "10.10.10.25"},
                        "Wifi": {"Status": "Connected"},
                    }
                ],
                "Video": {"Selfview": {"Mode": "On", "FullscreenMode": "Current"}},
                "Standby": {"State": "Off"},
                "SystemUnit": {
                    "State": {"NumberOfActiveCalls": 1, "System": "Available"}
                },
            },
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {
                "SystemUnit": {
                    "Hardware": {"Module": {"SerialNumber": "SERIAL-1"}},
                    "ProductPlatform": "RoomOS",
                    "ProductId": "Cisco Board Pro",
                    "Software": {
                        "Version": "RoomOS 11.24",
                        "DisplayName": "RoomOS March 2026",
                    },
                },
                "Video": {"Monitors": "Dual"},
            },
        )
    )
    api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    snapshot = asyncio.run(client.get_status("Board Pro"))

    assert snapshot.source == "webex-cloud-xapi"
    assert snapshot.device_id == "device-1"
    assert snapshot.display_name == "Board Pro"
    assert snapshot.volume == 55
    assert snapshot.call_active is True
    assert snapshot.active_call_count == 1
    assert snapshot.presentation_active is True
    assert snapshot.presentation_mode == "Sending"
    assert snapshot.standby_state == "Off"
    assert snapshot.product_platform == "RoomOS"
    assert snapshot.software_version == "RoomOS 11.24"
    assert snapshot.software_display_name == "RoomOS March 2026"
    assert snapshot.serial_number == "SERIAL-1"
    assert snapshot.system_state == "Available"
    assert snapshot.volume_muted is False
    assert snapshot.microphones_muted is True
    assert snapshot.selfview_mode == "On"
    assert snapshot.selfview_fullscreen == "Current"
    assert snapshot.speakertrack_state == "Active"
    assert snapshot.presentertrack_status == "Inactive"
    assert snapshot.active_interface == "ethernet"
    assert snapshot.ipv4_address == "10.10.10.25"
    assert snapshot.wifi_status == "Connected"
    assert "deviceId=device-1" in (snapshot.detail or "")
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Audio.Volume"),
                    ("name", "Audio.VolumeMute"),
                    ("name", "Audio.Microphones.Mute"),
                    ("name", "Audio.Microphones.MusicMode"),
                    ("name", "Audio.Microphones.NoiseRemoval"),
                    ("name", "Call[*].Status"),
                    ("name", "Cameras.PresenterTrack.Availability"),
                    ("name", "Cameras.PresenterTrack.Status"),
                    ("name", "Cameras.SpeakerTrack.Availability"),
                    ("name", "Cameras.SpeakerTrack.Closeup.Status"),
                ),
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Cameras.SpeakerTrack.Frames.Availability"),
                    ("name", "Cameras.SpeakerTrack.Frames.Status"),
                    ("name", "Cameras.SpeakerTrack.State"),
                    (
                        "name",
                        "Conference.Presentation.Mode",
                    ),
                    (
                        "name",
                        "Conference.Presentation.LocalInstance[*].SendingMode",
                    ),
                    ("name", "Network[1].ActiveInterface"),
                    ("name", "Network[1].IPv4.Address"),
                    ("name", "Network[1].Wifi.Status"),
                    ("name", "Standby.State"),
                    ("name", "SystemUnit.Hardware.Module.SerialNumber"),
                ),
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "SystemUnit.ProductPlatform"),
                    ("name", "SystemUnit.ProductId"),
                    ("name", "SystemUnit.Software.DisplayName"),
                    ("name", "SystemUnit.Software.Version"),
                    ("name", "SystemUnit.State.System"),
                    ("name", "SystemUnit.State.NumberOfActiveCalls"),
                    ("name", "Video.Selfview.Mode"),
                    ("name", "Video.Selfview.FullscreenMode"),
                    ("name", "Video.Monitors"),
                ),
            },
        ),
    ]


def test_device_client_returns_best_effort_none_for_missing_status_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
    api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
    api_client.responses.append(make_response("GET", "/xapi/status", 200, {}))
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    snapshot = asyncio.run(client.get_status("Desk Pro"))

    assert snapshot.volume is None
    assert snapshot.volume_muted is None
    assert snapshot.microphones_muted is None
    assert snapshot.call_active is None
    assert snapshot.presentation_active is None
    assert snapshot.presentation_mode is None
    assert snapshot.product_platform is None
    assert snapshot.software_display_name is None
    assert snapshot.system_state is None
    assert snapshot.selfview_mode is None
    assert snapshot.selfview_fullscreen is None
    assert snapshot.speakertrack_state is None
    assert snapshot.presentertrack_status is None
    assert snapshot.active_interface is None
    assert snapshot.ipv4_address is None
    assert snapshot.wifi_status is None


def test_device_client_retries_status_names_individually_after_batch_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    batch_request = httpx.Request("GET", "https://webexapis.com/v1/xapi/status")
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(
        make_response("GET", "/xapi/status", 200, {"Audio": {"Volume": 42}})
    )
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"Call": [{"Status": "Connected"}]},
        )
    )
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"Standby": {"State": "Off"}},
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"SystemUnit": {"Hardware": {"Module": {"SerialNumber": "SERIAL-2"}}}},
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"SystemUnit": {"ProductId": "Desk Pro"}},
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"SystemUnit": {"Software": {"Version": "RoomOS 11.20"}}},
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"SystemUnit": {"State": {"NumberOfActiveCalls": 1}}},
        )
    )
    api_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"Video": {"Monitors": "Single"}},
        )
    )
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    api_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    snapshot = asyncio.run(client.get_status("Desk Pro"))

    assert snapshot.volume == 42
    assert snapshot.call_active is True
    assert snapshot.active_call_count == 1
    assert snapshot.presentation_active is None
    assert snapshot.presentation_mode is None
    assert snapshot.standby_state == "Off"
    assert snapshot.serial_number == "SERIAL-2"
    assert snapshot.software_version == "RoomOS 11.20"


def test_device_client_reraises_non_400_status_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Desk Pro"}]},
        )
    )
    api_client.responses.append(
        httpx.Response(
            500,
            request=httpx.Request("GET", "https://webexapis.com/v1/xapi/status"),
            json={},
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(httpx.HTTPStatusError):
        _ = asyncio.run(client.get_status("Desk Pro"))


def test_device_client_requires_exact_device_name_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(make_response("GET", "/devices", 200, {"items": []}))
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {"id": "device-1", "displayName": "Board Pro 1"},
                    {"id": "device-2", "displayName": "Board Pro 2"},
                ]
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(DeviceResolutionError) as exc_info:
        _ = asyncio.run(client.get_status("Board Pro"))

    assert str(exc_info.value) == "No Webex device found for target 'Board Pro'."
    assert [device.display_name for device in exc_info.value.candidate_devices] == [
        "Board Pro 1",
        "Board Pro 2",
    ]


def test_device_client_raises_when_no_devices_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                        "displayName": "Home Office",
                        "product": "Cisco Desk Pro",
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-2",
                        "displayName": "Board Pro",
                        "product": "Cisco Board Pro",
                        "connectionStatus": "disconnected",
                    },
                ]
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(DeviceResolutionError) as exc_info:
        _ = asyncio.run(client.get_status("Desk Pro"))

    assert str(exc_info.value) == "No Webex device found for target 'Desk Pro'."
    assert [device.display_name for device in exc_info.value.candidate_devices] == [
        "Home Office",
        "Board Pro",
    ]


def test_device_client_executes_set_volume_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            "/xapi/command/Audio.Volume.Set",
            200,
            {"deviceId": "device-1", "arguments": {"Level": 35}, "result": {}},
        )
    )
    _ = build_client_queue(resolve_client, command_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(client.set_volume("Board Pro", 35))

    assert "Set volume to 35" in result
    assert resolve_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        )
    ]
    assert command_client.requests == [
        (
            "POST",
            "/xapi/command/Audio.Volume.Set",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {"deviceId": "device-1", "arguments": {"Level": 35}},
            },
        )
    ]


def test_device_client_lists_devices_with_token_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "product": "Cisco Board Pro",
                        "connectionStatus": "connected",
                    },
                    {
                        "id": "device-2",
                        "displayName": "Desk Pro",
                        "product": "Cisco Desk Pro",
                        "connectionStatus": "disconnected",
                    },
                ]
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    client = DeviceClient(AppConfig(device_mock_mode=False), StaticTokenProvider())

    devices = asyncio.run(client.list_devices())

    assert [device.display_name for device in devices] == ["Board Pro", "Desk Pro"]
    assert devices[0].connection_status == "connected"
    assert devices[1].connection_status == "disconnected"
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {"headers": {"Authorization": "Bearer bot-token"}},
        )
    ]


def test_device_client_requires_ack_for_factory_reset() -> None:
    client = DeviceClient(AppConfig(device_mock_mode=True), StaticTokenProvider())

    with pytest.raises(
        RuntimeError, match="Factory reset requires explicit acknowledgement."
    ):
        _ = asyncio.run(client.factory_reset("Board Pro", acknowledged=False))


@pytest.mark.parametrize(
    ("method_name", "kwargs", "expected_path", "expected_json"),
    [
        (
            "webex_join",
            {"meeting_identifier": "987654321"},
            "/xapi/command/Webex.Join",
            {"deviceId": "device-1", "arguments": {"Number": "987654321"}},
        ),
        (
            "join_obtp",
            {},
            "/xapi/command/Webex.Join",
            {"deviceId": "device-1", "arguments": {"Number": "987654321"}},
        ),
        (
            "dial",
            {"address": "sip:room@example.com"},
            "/xapi/command/Dial",
            {"deviceId": "device-1", "arguments": {"Number": "sip:room@example.com"}},
        ),
        (
            "hang_up",
            {},
            "/xapi/command/Call.Disconnect",
            {"deviceId": "device-1"},
        ),
        (
            "hang_up",
            {"call_id": 2},
            "/xapi/command/Call.Disconnect",
            {"deviceId": "device-1", "arguments": {"CallId": 2}},
        ),
        (
            "send_dtmf",
            {"tones": "123#", "call_id": 4},
            "/xapi/command/Call.DTMFSend",
            {
                "deviceId": "device-1",
                "arguments": {"DTMFString": "123#", "CallId": 4},
            },
        ),
        (
            "set_microphone_mute",
            {"muted": True},
            "/xapi/command/Audio.Microphones.Mute",
            {"deviceId": "device-1"},
        ),
        (
            "set_microphone_mute",
            {"muted": False},
            "/xapi/command/Audio.Microphones.Unmute",
            {"deviceId": "device-1"},
        ),
        (
            "set_video_mute",
            {"muted": True},
            "/xapi/command/Video.Input.MainVideo.Mute",
            {"deviceId": "device-1"},
        ),
        (
            "set_video_mute",
            {"muted": False},
            "/xapi/command/Video.Input.MainVideo.Unmute",
            {"deviceId": "device-1"},
        ),
        (
            "set_selfview",
            {"enabled": True},
            "/xapi/command/Video.Selfview.Set",
            {"deviceId": "device-1", "arguments": {"Mode": "On"}},
        ),
        (
            "set_presentation",
            {"enabled": True},
            "/xapi/command/Presentation.Start",
            {"deviceId": "device-1"},
        ),
        (
            "set_presentation",
            {"enabled": False},
            "/xapi/command/Presentation.Stop",
            {"deviceId": "device-1"},
        ),
        (
            "switch_input_source",
            {"source_id": "3"},
            "/xapi/command/Video.Input.SetMainVideoSource",
            {"deviceId": "device-1", "arguments": {"ConnectorId": "3"}},
        ),
        (
            "switch_input_source",
            {"source_id": "pc"},
            "/xapi/command/Video.Input.SetMainVideoSource",
            {"deviceId": "device-1", "arguments": {"ConnectorId": "1"}},
        ),
        (
            "switch_input_source",
            {"source_id": "remote"},
            "/xapi/command/Video.Input.SetMainVideoSource",
            {"deviceId": "device-1", "arguments": {"ConnectorId": "3"}},
        ),
        (
            "assign_matrix",
            {
                "output": "HDMI1",
                "mode": "Replace",
                "layout": "Equal",
                "source_id": "3",
                "remote_main": True,
            },
            "/xapi/command/Video.Matrix.Assign",
            {
                "deviceId": "device-1",
                "arguments": {
                    "Output": "HDMI1",
                    "Mode": "Replace",
                    "Layout": "Equal",
                    "SourceId": "3",
                    "RemoteMain": "On",
                },
            },
        ),
        (
            "unassign_matrix",
            {"output": "HDMI1", "source_id": "3", "remote_main": False},
            "/xapi/command/Video.Matrix.Unassign",
            {
                "deviceId": "device-1",
                "arguments": {
                    "Output": "HDMI1",
                    "SourceId": "3",
                    "RemoteMain": "Off",
                },
            },
        ),
        (
            "swap_matrix",
            {"output_a": "HDMI1", "output_b": "HDMI2"},
            "/xapi/command/Video.Matrix.Swap",
            {
                "deviceId": "device-1",
                "arguments": {"OutputA": "HDMI1", "OutputB": "HDMI2"},
            },
        ),
        (
            "activate_camera_preset",
            {"preset_id": "5"},
            "/xapi/command/Camera.Preset.Activate",
            {"deviceId": "device-1", "arguments": {"PresetId": "5"}},
        ),
        (
            "adjust_camera_position",
            {"camera_id": "2", "pan": 1000, "tilt": -1000, "zoom": -700},
            "/xapi/command/Camera.PositionSet",
            {
                "deviceId": "device-1",
                "arguments": {
                    "CameraId": 2,
                    "Pan": 1000,
                    "Tilt": -1000,
                    "Zoom": 0,
                },
            },
        ),
        (
            "set_speakertrack",
            {"enabled": True},
            "/xapi/command/Cameras.SpeakerTrack.Activate",
            {"deviceId": "device-1"},
        ),
        (
            "set_speakertrack",
            {"enabled": False},
            "/xapi/command/Cameras.SpeakerTrack.Deactivate",
            {"deviceId": "device-1"},
        ),
        (
            "set_standby",
            {"enabled": True},
            "/xapi/command/Standby.Activate",
            {"deviceId": "device-1"},
        ),
        (
            "set_standby",
            {"enabled": False},
            "/xapi/command/Standby.Deactivate",
            {"deviceId": "device-1"},
        ),
        (
            "reboot",
            {},
            "/xapi/command/SystemUnit.Boot",
            {"deviceId": "device-1"},
        ),
        (
            "factory_reset",
            {"acknowledged": True},
            "/xapi/command/SystemUnit.FactoryReset",
            {"deviceId": "device-1", "arguments": {"Confirm": "Yes"}},
        ),
    ],
)
def test_device_client_executes_supported_cloud_xapi_commands(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    kwargs: dict[str, object],
    expected_path: str,
    expected_json: dict[str, object],
) -> None:
    resolve_client = QueuedAsyncClient()
    resolve_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
        )
    )
    if method_name == "adjust_camera_position":
        resolve_client.responses.append(
            make_response(
                "GET",
                "/xapi/status",
                200,
                {
                    "Cameras": {
                        "Camera": [
                            {},
                            {"Position": {"Pan": 0, "Tilt": 0, "Zoom": 700}},
                        ]
                    }
                },
            )
        )
    if method_name == "join_obtp":
        resolve_client.responses.append(
            make_response(
                "POST",
                "/xapi/command/Bookings.List",
                200,
                {
                    "Bookings": {
                        "ListResult": {
                            "Booking": [
                                {
                                    "Id": "booking-next",
                                    "Title": "Weekly Staff Meeting",
                                    "StartTime": "2026-04-23T09:30:00Z",
                                    "WebexMeetingNumber": "987654321",
                                    "Service": "Webex",
                                }
                            ]
                        }
                    }
                },
            )
        )
    command_client = QueuedAsyncClient()
    command_client.responses.append(
        make_response("POST", expected_path, 200, {"status": "ok"})
    )
    _ = build_client_queue(resolve_client, command_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    method = getattr(device_client, method_name)
    if method_name in {"reboot", "hang_up", "factory_reset"}:
        result = asyncio.run(method("Board Pro", **kwargs))
    elif method_name in {
        "webex_join",
        "dial",
        "set_microphone_mute",
        "set_video_mute",
        "set_selfview",
        "set_layout",
        "set_presentation",
        "switch_input_source",
        "assign_matrix",
        "unassign_matrix",
        "swap_matrix",
        "activate_camera_preset",
        "set_speakertrack",
        "set_standby",
    }:
        result = asyncio.run(method("Board Pro", **kwargs))
    else:
        result = asyncio.run(method("Board Pro", **kwargs))

    assert isinstance(result, str)
    assert "Board Pro" in result
    expected_resolve_requests: list[tuple[str, str, dict[str, object]]] = [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        )
    ]
    if method_name == "adjust_camera_position":
        expected_resolve_requests.append(
            (
                "GET",
                "/xapi/status",
                {
                    "headers": {"Authorization": "Bearer bot-token"},
                    "params": (
                        ("deviceId", "device-1"),
                        ("name", "Cameras.Camera[2].Position.Pan"),
                        ("name", "Cameras.Camera[2].Position.Tilt"),
                        ("name", "Cameras.Camera[2].Position.Zoom"),
                    ),
                },
            )
        )
    if method_name == "join_obtp":
        expected_resolve_requests.append(
            (
                "POST",
                "/xapi/command/Bookings.List",
                {
                    "headers": {"Authorization": "Bearer bot-token"},
                    "json": {
                        "deviceId": "device-1",
                        "arguments": {"ScheduleType": "Upcoming"},
                    },
                },
            )
        )
    assert resolve_client.requests == expected_resolve_requests
    assert command_client.requests == [
        (
            "POST",
            expected_path,
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": expected_json,
            },
        )
    ]


def test_device_client_adjust_camera_position_retries_status_names_individually_after_batch_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_client = QueuedAsyncClient()
    resolve_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
        )
    )
    batch_request = httpx.Request("GET", "https://webexapis.com/v1/xapi/status")
    resolve_client.responses.append(httpx.Response(400, request=batch_request, json={}))
    resolve_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"Cameras": {"Camera": [{}, {"Position": {"Pan": 0}}]}},
        )
    )
    resolve_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"Cameras": {"Camera": [{}, {"Position": {"Tilt": 0}}]}},
        )
    )
    resolve_client.responses.append(
        make_response(
            "GET",
            "/xapi/status",
            200,
            {"Cameras": {"Camera": [{}, {"Position": {"Zoom": 700}}]}},
        )
    )
    command_client = QueuedAsyncClient()
    command_client.responses.append(
        make_response("POST", "/xapi/command/Camera.PositionSet", 200, {"status": "ok"})
    )
    _ = build_client_queue(resolve_client, command_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(
        device_client.adjust_camera_position(
            "Board Pro",
            camera_id="2",
            pan=1000,
            tilt=-1000,
            zoom=-700,
        )
    )

    assert result == "Adjusted camera 2 on Board Pro (pan=1000, tilt=-1000, zoom=-700)."
    assert resolve_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Cameras.Camera[2].Position.Pan"),
                    ("name", "Cameras.Camera[2].Position.Tilt"),
                    ("name", "Cameras.Camera[2].Position.Zoom"),
                ),
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Cameras.Camera[2].Position.Pan"),
                ),
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Cameras.Camera[2].Position.Tilt"),
                ),
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Cameras.Camera[2].Position.Zoom"),
                ),
            },
        ),
    ]
    assert command_client.requests == [
        (
            "POST",
            "/xapi/command/Camera.PositionSet",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "deviceId": "device-1",
                    "arguments": {
                        "CameraId": 2,
                        "Pan": 1000,
                        "Tilt": -1000,
                        "Zoom": 0,
                    },
                },
            },
        )
    ]


@pytest.mark.parametrize(
    ("mode", "expected_path", "expected_message"),
    [
        (
            "noise-reduction",
            "/xapi/command/Audio.Microphones.NoiseRemoval.Activate",
            "Activated noise reduction on Board Pro. Exact configurable microphone mode values reported by Webex: Focused, Wide.",
        ),
        (
            "music-mode",
            "/xapi/command/Audio.Microphones.MusicMode.Start",
            "Started music mode on Board Pro. Exact configurable microphone mode values reported by Webex: Focused, Wide.",
        ),
    ],
)
def test_device_client_command_backed_microphone_modes_include_exact_config_guidance(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_path: str,
    expected_message: str,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
    command_client = QueuedAsyncClient()
    command_client.responses.append(
        make_response("POST", expected_path, 200, {"status": "ok"})
    )
    _ = build_client_queue(api_client, command_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.set_microphone_mode("Board Pro", mode))

    assert result == expected_message
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        ),
        (
            "GET",
            "/deviceConfigurations",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {
                    "deviceId": "device-1",
                    "key": "Audio.Input.MicrophoneMode",
                },
            },
        ),
    ]
    assert command_client.requests == [
        (
            "POST",
            expected_path,
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {"deviceId": "device-1"},
            },
        )
    ]


def test_device_client_accepts_object_response_from_device_configuration_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_client = QueuedAsyncClient()
    resolve_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Board Pro"}]},
        )
    )
    resolve_client.responses.append(
        make_response(
            "GET",
            "/deviceConfigurations",
            200,
            {
                "items": [
                    {
                        "key": "Video.Monitors",
                        "valueSpace": {"enum": ["Auto", "Dual", "Single"]},
                    }
                ]
            },
        )
    )
    config_client = QueuedAsyncClient()
    config_client.responses.append(
        httpx.Response(
            200,
            json={"items": []},
            request=httpx.Request(
                "PATCH", "https://webexapis.com/v1/deviceConfigurations"
            ),
        )
    )
    _ = build_client_queue(resolve_client, config_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )
    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.set_display_mode("Board Pro", "left-video-right-video"))

    assert "Set display mode to left-video-right-video on Board Pro" in result


@pytest.mark.parametrize(
    ("method_name", "kwargs", "expected_path", "expected_json"),
    [
        (
            "set_display_mode",
            {"mode": "left-video-right-video"},
            "/deviceConfigurations",
            [
                {
                    "op": "replace",
                    "path": "Video.Output.Connector[1].MonitorRole/sources/configured/value",
                    "value": "First",
                },
                {
                    "op": "replace",
                    "path": "Video.Output.Connector[2].MonitorRole/sources/configured/value",
                    "value": "Second",
                },
            ],
        ),
        (
            "set_display_role",
            {"connector_id": 2, "role": "presentation-only"},
            "/deviceConfigurations",
            [
                {
                    "op": "replace",
                    "path": "Video.Output.Connector[2].MonitorRole/sources/configured/value",
                    "value": "PresentationOnly",
                }
            ],
        ),
    ],
)
def test_device_client_patches_supported_device_configurations(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    kwargs: dict[str, object],
    expected_path: str,
    expected_json: list[dict[str, object]],
) -> None:
    resolve_client = QueuedAsyncClient()
    resolve_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
        )
    )
    if method_name == "set_display_mode":
        resolve_client.responses.append(
            make_response(
                "GET",
                "/deviceConfigurations",
                200,
                {
                    "items": [
                        {
                            "key": "Video.Monitors",
                            "valueSpace": {"enum": ["Auto", "Dual", "Single"]},
                        }
                    ]
                },
            )
        )
    config_client = QueuedAsyncClient()
    config_client.responses.append(
        httpx.Response(
            200,
            json=[],
            request=httpx.Request("PATCH", f"https://webexapis.com/v1{expected_path}"),
        )
    )
    _ = build_client_queue(resolve_client, config_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(getattr(device_client, method_name)("Board Pro", **kwargs))

    assert isinstance(result, str)
    assert "Board Pro" in result
    expected_resolve_requests: list[tuple[str, str, dict[str, object]]] = [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        )
    ]
    if False and method_name == "set_display_mode":
        expected_resolve_requests.append(
            (
                "GET",
                "/deviceConfigurations",
                {
                    "headers": {"Authorization": "Bearer bot-token"},
                    "params": {
                        "deviceId": "device-1",
                        "key": "Video.Monitors",
                    },
                },
            )
        )
    assert resolve_client.requests == expected_resolve_requests
    assert config_client.requests == [
        (
            "PATCH",
            expected_path,
            {
                "headers": {
                    "Authorization": "Bearer bot-token",
                    "Content-Type": "application/json-patch+json",
                },
                "params": {"deviceId": "device-1"},
                "json": expected_json,
            },
        )
    ]


def test_device_client_config_backed_microphone_mode_uses_exact_webex_values_before_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
    _ = build_client_queue(api_client, config_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(
        device_client.set_microphone_mode("Board Pro", "voice-optimized")
    )

    assert result == (
        "Set microphone mode to voice optimized on Board Pro. Exact configurable "
        "microphone mode values reported by Webex: Focused, Wide."
    )
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        ),
        (
            "GET",
            "/deviceConfigurations",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {
                    "deviceId": "device-1",
                    "key": "Audio.Input.MicrophoneMode",
                },
            },
        ),
    ]
    assert config_client.requests == [
        (
            "PATCH",
            "/deviceConfigurations",
            {
                "headers": {
                    "Authorization": "Bearer bot-token",
                    "Content-Type": "application/json-patch+json",
                },
                "params": {"deviceId": "device-1"},
                "json": [
                    {
                        "op": "replace",
                        "path": "Audio.Input.MicrophoneMode/sources/configured/value",
                        "value": "Focused",
                    }
                ],
            },
        )
    ]


def test_device_client_config_backed_microphone_mode_fails_before_mutation_when_value_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Cannot set microphone mode to voice optimized on Board Pro because "
            "Webex reports configurable microphone values: Wide\\."
        ),
    ):
        _ = asyncio.run(
            device_client.set_microphone_mode("Board Pro", "voice-optimized")
        )

    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        ),
        (
            "GET",
            "/deviceConfigurations",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {
                    "deviceId": "device-1",
                    "key": "Audio.Input.MicrophoneMode",
                },
            },
        ),
    ]


def test_device_client_config_backed_display_mode_uses_exact_webex_values_before_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Codec Pro G2",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Codec Pro G2",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
                        "key": "Video.Monitors",
                        "valueSpace": {"enum": ["Auto", "Dual", "Single"]},
                    }
                ]
            },
        )
    )
    config_client = QueuedAsyncClient()
    config_client.responses.append(
        make_response("PATCH", "/deviceConfigurations", 200, [])
    )
    _ = build_client_queue(api_client, config_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.set_display_mode("Codec Pro G2", "left-video-right-video"))

    assert result == (
        "Set display mode to left-video-right-video on Codec Pro G2 "
        "(connector 1: First, connector 2: Second)."
    )
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Codec Pro G2"},
            },
        )
    ]
    assert config_client.requests == [
        (
            "PATCH",
            "/deviceConfigurations",
            {
                "headers": {
                    "Authorization": "Bearer bot-token",
                    "Content-Type": "application/json-patch+json",
                },
                "params": {"deviceId": "device-1"},
                "json": [
                    {
                        "op": "replace",
                        "path": "Video.Output.Connector[1].MonitorRole/sources/configured/value",
                        "value": "First",
                    },
                    {
                        "op": "replace",
                        "path": "Video.Output.Connector[2].MonitorRole/sources/configured/value",
                        "value": "Second",
                    },
                ],
            },
        )
    ]


def test_device_client_config_backed_display_mode_accepts_empty_success_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Codec Pro G2",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Codec Pro G2",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
                        "key": "Video.Monitors",
                        "valueSpace": {"enum": ["Auto", "Dual", "Single"]},
                    }
                ]
            },
        )
    )
    config_client = QueuedAsyncClient()
    config_client.responses.append(
        httpx.Response(
            200,
            content=b"",
            request=httpx.Request(
                "PATCH", "https://webexapis.com/v1/deviceConfigurations"
            ),
        )
    )
    _ = build_client_queue(api_client, config_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.set_display_mode("Codec Pro G2", "left-video-right-video"))

    assert result == (
        "Set display mode to left-video-right-video on Codec Pro G2 "
        "(connector 1: First, connector 2: Second)."
    )


def test_device_client_display_mode_preflight_accepts_empty_configuration_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Codec Pro G2",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Codec Pro G2",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
        )
    )
    api_client.responses.append(
        httpx.Response(
            200,
            content=b"",
            request=httpx.Request(
                "GET", "https://webexapis.com/v1/deviceConfigurations"
            ),
        )
    )
    config_client = QueuedAsyncClient()
    config_client.responses.append(
        make_response("PATCH", "/deviceConfigurations", 200, [])
    )
    _ = build_client_queue(api_client, config_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.set_display_mode("Codec Pro G2", "left-video-right-video"))

    assert result == (
        "Set display mode to left-video-right-video on Codec Pro G2 "
        "(connector 1: First, connector 2: Second)."
    )


def test_device_client_display_mode_empty_devices_body_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": []},
        )
    )
    api_client.responses.append(
        httpx.Response(
            200,
            content=b"",
            request=httpx.Request("GET", "https://webexapis.com/v1/devices"),
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"No Webex device found for target 'Codec Pro G2'\.",
    ):
        _ = asyncio.run(device_client.set_display_mode("Codec Pro G2", "left-video-right-video"))


def test_device_client_config_backed_display_mode_fails_before_mutation_when_value_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Codec Pro G2",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Codec Pro G2",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
                        "key": "Video.Monitors",
                        "valueSpace": {"enum": ["Auto", "Single"]},
                    }
                ]
            },
        )
    )
    _ = build_client_queue(api_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(
        RuntimeError,
        match="Unsupported display mode: unsupported-display-mode",
    ):
        _ = asyncio.run(
            device_client.set_display_mode("Codec Pro G2", "unsupported-display-mode")
        )

    assert api_client.requests == []


def test_device_client_set_layout_includes_current_layout_and_documented_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_client = QueuedAsyncClient()
    api_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
    _ = build_client_queue(api_client, command_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.set_layout("Board Pro", "Prominent"))

    assert result == (
        "Set layout to Prominent on Board Pro. Current layout reported by Webex "
        "before the change: Equal. Documented candidate layouts (best-effort "
        "guidance, not device-reported support): Equal, Overlay, Prominent, "
        "Single, SpeakerOnly."
    )
    assert api_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Video.Layout.CurrentLayout"),
                ),
            },
        ),
        (
            "GET",
            "/xapi/status",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": (
                    ("deviceId", "device-1"),
                    ("name", "Video.Layout.LayoutFamily.Local"),
                ),
            },
        ),
    ]
    assert command_client.requests == [
        (
            "POST",
            "/xapi/command/Video.Layout.SetLayout",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "deviceId": "device-1",
                    "arguments": {"LayoutName": "Prominent"},
                },
            },
        )
    ]


def test_device_client_switch_input_source_400_returns_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_client = QueuedAsyncClient()
    resolve_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {"items": [{"id": "device-1", "displayName": "Room Bar"}]},
        )
    )
    command_client = QueuedAsyncClient()
    command_client.responses.append(
        make_response(
            "POST",
            "/xapi/command/Video.Input.SetMainVideoSource",
            400,
            {"message": "Bad Request"},
        )
    )
    _ = build_client_queue(resolve_client, command_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )
    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    with pytest.raises(RuntimeError, match="source is connected and supported"):
        asyncio.run(device_client.switch_input_source("Room Bar", "pc"))


def test_device_client_switch_input_source_resolves_remote_alias_to_connector_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_client = QueuedAsyncClient()
    resolve_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "place": "HQ 7F",
                        "connectionStatus": "connected",
                    }
                ]
            },
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
    _ = build_client_queue(resolve_client, command_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.switch_input_source("Board Pro", "remote"))

    assert result == "Switched input source to remote on Board Pro."
    assert resolve_client.requests == [
        (
            "GET",
            "/devices",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "params": {"displayName": "Board Pro"},
            },
        )
    ]
    assert command_client.requests == [
        (
            "POST",
            "/xapi/command/Video.Input.SetMainVideoSource",
            {
                "headers": {"Authorization": "Bearer bot-token"},
                "json": {
                    "deviceId": "device-1",
                    "arguments": {"ConnectorId": "3"},
                },
            },
        )
    ]


def test_token_manager_provider_fetches_current_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_client = QueuedAsyncClient()
    token_client.responses.append(
        httpx.Response(
            200,
            json={"accessToken": "fresh-token"},
            request=httpx.Request("GET", "http://127.0.0.1:3000/api/tokens/current"),
        )
    )
    _ = build_client_queue(token_client)
    monkeypatch.setattr(
        "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
    )

    provider = TokenManagerTokenProvider(
        base_url="http://127.0.0.1:3000",
        api_key="token-manager-key",
    )

    token = asyncio.run(provider.get_bearer_token())

    assert token == "fresh-token"
    assert token_client.requests == [
        (
            "GET",
            "/api/tokens/current",
            {"headers": {"x-api-key": "token-manager-key"}},
        )
    ]


def test_token_manager_provider_falls_back_to_bot_token_on_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_client = QueuedAsyncClient()
    token_client.responses.append(
        httpx.Response(
            500,
            json={"detail": "token service unavailable"},
            request=httpx.Request("GET", "http://127.0.0.1:3000/api/tokens/current"),
        )
    )
    _ = build_client_queue(token_client)
    monkeypatch.setattr(
        "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
    )

    provider = TokenManagerTokenProvider(
        base_url="http://127.0.0.1:3000",
        api_key="token-manager-key",
        fallback_token="bot-token-fallback",
    )

    token = asyncio.run(provider.get_bearer_token())

    assert token == "bot-token-fallback"


def test_token_manager_provider_raises_clean_error_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_client = QueuedAsyncClient()
    token_client.responses.append(
        httpx.Response(
            500,
            json={"detail": "token service unavailable"},
            request=httpx.Request("GET", "http://127.0.0.1:3000/api/tokens/current"),
        )
    )
    _ = build_client_queue(token_client)
    monkeypatch.setattr(
        "assistant_app.token_provider.httpx.AsyncClient", async_client_factory
    )

    provider = TokenManagerTokenProvider(
        base_url="http://127.0.0.1:3000",
        api_key="token-manager-key",
    )

    with pytest.raises(
        RuntimeError,
        match=(
            r"Failed to retrieve a Webex access token from the token manager\. "
            r"Check the token service health or configure WEBEX_BOT_TOKEN fallback\."
        ),
    ):
        _ = asyncio.run(provider.get_bearer_token())


def test_device_client_set_display_mode_configures_two_monitor_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_client = QueuedAsyncClient()
    resolve_client.responses.append(
        make_response(
            "GET",
            "/devices",
            200,
            {
                "items": [
                    {
                        "id": "device-1",
                        "displayName": "Board Pro",
                        "workspaceId": "workspace-1",
                        "product": "Cisco Board Pro",
                        "type": "roomdesk",
                        "permissions": ["xapi"],
                        "connectionStatus": "connected",
                    }
                ]
            },
        )
    )
    config_client = QueuedAsyncClient()
    config_client.responses.append(make_response("PATCH", "/deviceConfigurations", 200, []))
    _ = build_client_queue(resolve_client, config_client)
    monkeypatch.setattr(
        "device_executor.device_client.httpx.AsyncClient", async_client_factory
    )

    device_client = DeviceClient(
        AppConfig(
            webex_mock_mode=False,
            webex_bot_person_id="bot-person-id",
            webex_webhook_secret="secret",
            device_mock_mode=False,
        ),
        StaticTokenProvider(),
    )

    result = asyncio.run(device_client.set_display_mode("Board Pro", "left-video-right-presentation"))

    assert result == (
        "Set display mode to left-video-right-presentation on Board Pro "
        "(connector 1: First, connector 2: PresentationOnly)."
    )
    assert config_client.requests == [
        (
            "PATCH",
            "/deviceConfigurations",
            {
                "headers": {
                    "Authorization": "Bearer bot-token",
                    "Content-Type": "application/json-patch+json",
                },
                "params": {"deviceId": "device-1"},
                "json": [
                    {
                        "op": "replace",
                        "path": "Video.Output.Connector[1].MonitorRole/sources/configured/value",
                        "value": "First",
                    },
                    {
                        "op": "replace",
                        "path": "Video.Output.Connector[2].MonitorRole/sources/configured/value",
                        "value": "PresentationOnly",
                    },
                ],
            },
        )
    ]
