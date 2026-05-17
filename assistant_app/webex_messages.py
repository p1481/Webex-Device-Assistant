"""Webex Messages API helpers extracted from :mod:`webex_gateway`.

These functions take the :class:`WebexGateway` instance as the first argument so
that they can be called from thin instance-method wrappers on the gateway. This
mirrors the pattern used in :mod:`webex_webhooks` and keeps monkeypatch-based
tests working unchanged while moving the actual logic out of the gateway module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

import httpx

from shared.contracts import InboundUserMessage, MessageSource, OutboundReply

if TYPE_CHECKING:
    from assistant_app.webex_gateway import (
        WebexAttachmentActionDetails,
        WebexGateway,
        WebexWebhookEnvelope,
    )

logger = logging.getLogger(__name__)


async def fetch_inbound_message(
    gateway: WebexGateway, envelope: WebexWebhookEnvelope
) -> InboundUserMessage | None:
    from assistant_app.webex_gateway import WebexMessageDetails

    if is_self_authored(
        gateway,
        webhook_person_id=envelope.data.personId,
        webhook_person_email=envelope.data.personEmail,
    ):
        logger.info(
            "Dropping self-authored webhook envelope event_id=%s envelope_person_id=%s envelope_person_email=%s",
            envelope.id,
            envelope.data.personId,
            envelope.data.personEmail,
        )
        return None

    if gateway.config.webex_mock_mode:
        text = envelope.mock_text or "show device status"
        if not is_actionable_text(text):
            return None
        if not is_allowed_webex_sender(gateway, envelope.data.personEmail):
            return None
        return InboundUserMessage(
            session_id=envelope.data.roomId
            or envelope.data.personId
            or envelope.id,
            user_id=envelope.data.personId or "mock-user",
            text=text,
            source=MessageSource.WEBEX,
            room_id=envelope.data.roomId,
            person_email=envelope.data.personEmail,
            event_id=envelope.id,
        )

    async with httpx.AsyncClient(
        base_url=gateway.config.webex_api_base, timeout=10.0
    ) as client:
        response = await client.get(
            f"/messages/{envelope.data.id}",
            headers=await gateway._auth_headers(),
        )
        _ = response.raise_for_status()
        response_payload = response.json()
        details = WebexMessageDetails.model_validate(response_payload)

    logger.info(
        "Fetched Webex message event_id=%s message_id=%s room_id=%s parent_id=%s person_id=%s text_preview=%r",
        envelope.id,
        details.id,
        details.roomId,
        details.parentId,
        details.personId,
        preview_text(details.text),
    )

    if is_self_authored(
        gateway,
        fetched_person_id=details.personId,
        fetched_person_email=details.personEmail,
    ):
        logger.info(
            "Dropping fetched Webex self-message event_id=%s message_id=%s person_id=%s person_email=%s",
            envelope.id,
            details.id,
            details.personId,
            details.personEmail,
        )
        return None

    if not is_allowed_webex_sender(gateway, details.personEmail):
        logger.info(
            "Dropping disallowed Webex sender event_id=%s message_id=%s person_email=%s",
            envelope.id,
            details.id,
            details.personEmail,
        )
        return None

    if not is_actionable_text(details.text):
        logger.info(
            "Dropping non-actionable Webex message event_id=%s message_id=%s text_preview=%r",
            envelope.id,
            details.id,
            preview_text(details.text),
        )
        return None

    text = details.text
    if text is None:
        logger.info(
            "Dropping fetched Webex message with null text event_id=%s message_id=%s",
            envelope.id,
            details.id,
        )
        return None

    logger.info(
        "Normalized inbound Webex message event_id=%s session_id=%s room_id=%s text_preview=%r",
        envelope.id,
        details.roomId,
        details.roomId,
        preview_text(text),
    )
    return InboundUserMessage(
        session_id=details.roomId,
        user_id=details.personId,
        text=text.strip(),
        source=MessageSource.WEBEX,
        room_id=details.roomId,
        person_email=details.personEmail,
        event_id=envelope.id,
    )


async def send_reply(gateway: WebexGateway, reply: OutboundReply) -> None:
    if reply.skip_send:
        logger.info(
            "Skipping Webex reply send room_id=%s text_preview=%r",
            reply.room_id,
            preview_text(reply.text),
        )
        return

    if gateway.config.webex_mock_mode:
        logger.info("Mock Webex reply: %s", reply.text)
        return

    if not reply.room_id:
        raise RuntimeError("room_id is required to send a real Webex reply.")

    payload: dict[str, object] = {"roomId": reply.room_id, "text": reply.text}
    if reply.markdown:
        payload["markdown"] = reply.markdown
    if reply.attachments:
        payload["attachments"] = cast(list[dict[str, object]], reply.attachments)

    logger.info(
        "Sending Webex reply room_id=%s text_preview=%r markdown=%s attachments=%s",
        reply.room_id,
        preview_text(reply.text),
        reply.markdown is not None,
        len(reply.attachments),
    )

    async with httpx.AsyncClient(
        base_url=gateway.config.webex_api_base, timeout=10.0
    ) as client:
        response = await client.post(
            "/messages",
            headers=await gateway._auth_headers(),
            json=payload,
        )
        _ = response.raise_for_status()
    logger.info(
        "Sent Webex reply room_id=%s status_code=%s",
        reply.room_id,
        response.status_code,
    )


async def fetch_attachment_action_details(
    gateway: WebexGateway, action_id: str
) -> WebexAttachmentActionDetails:
    from assistant_app.webex_gateway import WebexAttachmentActionDetails

    if gateway.config.webex_mock_mode:
        return WebexAttachmentActionDetails(
            id=action_id,
            type="submit",
            messageId="mock-message-id",
            personId="mock-user",
            roomId="mock-room",
            inputs={},
        )

    async with httpx.AsyncClient(
        base_url=gateway.config.webex_api_base, timeout=10.0
    ) as client:
        response = await client.get(
            f"/attachment/actions/{action_id}",
            headers=await gateway._auth_headers(),
        )
        _ = response.raise_for_status()
        return WebexAttachmentActionDetails.model_validate(response.json())


async def send_direct_card_to_email(
    gateway: WebexGateway,
    email: str,
    title: str,
    prompt: str,
    request_id: str,
    admin_session_id: str,
) -> None:
    if gateway.config.webex_mock_mode:
        logger.info("Mock Webex direct admin card email=%s title=%s", email, title)
        return

    card: dict[str, object] = {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.0",
            "body": [
                {"type": "TextBlock", "weight": "Bolder", "text": title},
                {"type": "TextBlock", "wrap": True, "text": prompt},
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "Approve",
                    "data": {
                        "requestId": request_id,
                        "decision": "approve",
                        "adminSessionId": admin_session_id,
                    },
                },
                {
                    "type": "Action.Submit",
                    "title": "Reject",
                    "data": {
                        "requestId": request_id,
                        "decision": "reject",
                        "adminSessionId": admin_session_id,
                    },
                },
            ],
        },
    }
    payload = {
        "toPersonEmail": email,
        "text": f"Approval required: {title}",
        "markdown": f"**Approval required**\n\n{prompt}",
        "attachments": [card],
    }
    async with httpx.AsyncClient(
        base_url=gateway.config.webex_api_base, timeout=10.0
    ) as client:
        response = await client.post(
            "/messages",
            headers=await gateway._auth_headers(),
            json=payload,
        )
        _ = response.raise_for_status()


async def fetch_person_email(gateway: WebexGateway, person_id: str) -> str | None:
    if gateway.config.webex_mock_mode:
        return None
    async with httpx.AsyncClient(
        base_url=gateway.config.webex_api_base, timeout=10.0
    ) as client:
        response = await client.get(
            f"/people/{quote(person_id, safe='')}",
            headers=await gateway._auth_headers(),
        )
        _ = response.raise_for_status()
    payload = cast(object, response.json())
    if not isinstance(payload, dict):
        return None
    emails = cast(dict[str, object], payload).get("emails")
    if not isinstance(emails, list):
        return None
    for email in emails:
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
    return None


async def delete_message(gateway: WebexGateway, message_id: str) -> None:
    if gateway.config.webex_mock_mode:
        logger.info("Mock Webex delete message: %s", message_id)
        return

    async with httpx.AsyncClient(
        base_url=gateway.config.webex_api_base, timeout=10.0
    ) as client:
        response = await client.delete(
            f"/messages/{message_id}",
            headers=await gateway._auth_headers(),
        )
        _ = response.raise_for_status()
    logger.info("Deleted Webex message message_id=%s", message_id)


def is_actionable_text(text: str | None) -> bool:
    if text is None:
        return False

    normalized = text.strip()
    return bool(normalized)


def preview_text(text: str | None, limit: int = 120) -> str | None:
    if text is None:
        return None
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}…"


def is_self_authored(
    gateway: WebexGateway,
    webhook_person_id: str | None = None,
    webhook_person_email: str | None = None,
    fetched_person_id: str | None = None,
    fetched_person_email: str | None = None,
) -> bool:
    if any(
        gateway._person_ids_match(gateway.bot_person_id, candidate_person_id)
        for candidate_person_id in (webhook_person_id, fetched_person_id)
    ):
        return True

    candidate_emails = {
        email.lower()
        for email in (webhook_person_email, fetched_person_email)
        if isinstance(email, str)
    }
    return bool(gateway.bot_emails.intersection(candidate_emails))


def is_allowed_webex_sender(
    gateway: WebexGateway, person_email: str | None
) -> bool:
    runtime_settings_provider = gateway._runtime_settings_provider
    if not callable(runtime_settings_provider):
        return True
    settings = runtime_settings_provider()
    allowed = getattr(settings, "allowed_webex_user_emails", [])
    if not isinstance(allowed, list) or not allowed:
        return True
    if not isinstance(person_email, str) or not person_email.strip():
        return False
    return person_email.strip().lower() in {
        email for email in allowed if isinstance(email, str)
    }
