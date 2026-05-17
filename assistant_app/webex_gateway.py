from __future__ import annotations

import logging
from base64 import b64decode
from typing import ClassVar, cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from assistant_app import webex_webhooks
from assistant_app.config import AppConfig
from assistant_app.token_provider import WebexTokenProvider
from shared.contracts import InboundUserMessage, MessageSource, OutboundReply

logger = logging.getLogger(__name__)


class WebexBotIdentityMismatchError(RuntimeError):
    pass


class WebexWebhookData(BaseModel):
    id: str
    roomId: str | None = None
    personId: str | None = None
    personEmail: str | None = None


class WebexWebhookEnvelope(BaseModel):
    id: str
    resource: str
    event: str
    data: WebexWebhookData
    mock_text: str | None = Field(default=None, alias="mockText")

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)


class WebexMessageDetails(BaseModel):
    id: str
    roomId: str
    personId: str
    personEmail: str | None = None
    text: str | None = None
    parentId: str | None = None


class WebexAttachmentActionDetails(BaseModel):
    id: str
    type: str
    messageId: str
    personId: str
    roomId: str
    inputs: dict[str, object] = Field(default_factory=dict)


class WebexWebhookRegistration(BaseModel):
    name: str
    target_url: str = Field(alias="targetUrl")
    resource: str
    event: str
    filter: str | None = None
    secret: str

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)


class WebexWebhookRecord(BaseModel):
    id: str
    name: str
    target_url: str = Field(alias="targetUrl")
    resource: str
    event: str
    filter: str | None = None
    secret: str | None = None

    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)


class WebexBotIdentity(BaseModel):
    id: str
    emails: list[str] = Field(default_factory=list)


class WebexGateway:
    DIRECT_WEBHOOK_FILTER: ClassVar[str] = "roomType=direct"
    GROUP_WEBHOOK_FILTER: ClassVar[str] = "roomType=group&mentionedPeople=me"
    ATTACHMENT_ACTIONS_WEBHOOK_NAME: ClassVar[str] = (
        "webex-device-assistant-attachment-actions"
    )
    STATUS_PATHS: ClassVar[tuple[str, ...]] = (
        "Audio.Volume",
        "Call[*].Status",
        "Conference.Presentation.LocalInstance[*].SendingMode",
        "Standby.State",
        "SystemUnit.State.NumberOfActiveCalls",
    )

    def __init__(
        self,
        config: AppConfig,
        token_provider: WebexTokenProvider | None = None,
        runtime_settings_provider: object | None = None,
    ) -> None:
        self.config: AppConfig = config
        self._token_provider: WebexTokenProvider | None = token_provider
        self.bot_person_id: str | None = config.webex_bot_person_id
        self.bot_emails: set[str] = set()
        self._runtime_settings_provider = runtime_settings_provider

    def _canonical_person_id(self, person_id: str | None) -> str | None:
        if not person_id:
            return None

        padded = person_id + ("=" * (-len(person_id) % 4))
        try:
            decoded = b64decode(padded).decode("utf-8")
        except Exception:
            return person_id

        prefix = "ciscospark://us/"
        if not decoded.startswith(prefix):
            return person_id

        _, _, tail = decoded.partition(prefix)
        _, _, entity_id = tail.partition("/")
        return entity_id or person_id

    def _person_ids_match(self, left: str | None, right: str | None) -> bool:
        if left is None or right is None:
            return False
        if left == right:
            return True
        return self._canonical_person_id(left) == self._canonical_person_id(right)

    def parse_webhook_payload(self, payload: dict[str, object]) -> WebexWebhookEnvelope:
        envelope = WebexWebhookEnvelope.model_validate(payload)
        if envelope.resource != "messages" or envelope.event != "created":
            raise ValueError("Only messages.created webhooks are supported in the MVP.")
        logger.info(
            "Parsed Webex webhook event_id=%s resource=%s event=%s room_id=%s person_id=%s",
            envelope.id,
            envelope.resource,
            envelope.event,
            envelope.data.roomId,
            envelope.data.personId,
        )
        return envelope

    async def resolve_bot_identity(self) -> WebexBotIdentity | None:
        if self.config.webex_mock_mode:
            return None

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            response = await client.get("/people/me", headers=await self._auth_headers())
            _ = response.raise_for_status()

        identity = WebexBotIdentity.model_validate(response.json())
        configured_person_id = self.config.webex_bot_person_id
        if configured_person_id is not None and not self._person_ids_match(
            configured_person_id, identity.id
        ):
            raise WebexBotIdentityMismatchError(
                "WEBEX_BOT_PERSON_ID does not match the bot identity returned by people/me."
            )

        self.bot_person_id = identity.id
        self.bot_emails = {email.lower() for email in identity.emails}
        logger.info(
            "Resolved Webex bot identity person_id=%s emails=%s",
            identity.id,
            sorted(self.bot_emails),
        )
        return identity

    def desired_messages_webhooks(self) -> list[WebexWebhookRegistration]:
        return webex_webhooks.desired_messages_webhooks(self)

    def desired_attachment_action_webhook(self) -> WebexWebhookRegistration:
        return webex_webhooks.desired_attachment_action_webhook(self)

    async def _resolve_bearer_token(self) -> str:
        if self._token_provider is not None:
            token = await self._token_provider.get_bearer_token()
            if token and token.strip():
                return token.strip()
        if self.config.webex_bot_token:
            return self.config.webex_bot_token
        raise RuntimeError(
            "WEBEX_BOT_TOKEN or a working WebexTokenProvider is required "
            "when WEBEX_MOCK_MODE=false."
        )

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._resolve_bearer_token()
        return {"Authorization": f"Bearer {token}"}

    async def list_webhooks(self) -> list[WebexWebhookRecord]:
        return await webex_webhooks.list_webhooks(self)

    async def create_webhook(
        self, registration: WebexWebhookRegistration
    ) -> WebexWebhookRecord:
        return await webex_webhooks.create_webhook(self, registration)

    async def ensure_webhook(
        self,
        desired: WebexWebhookRegistration,
        owned_candidates: list[WebexWebhookRecord],
    ) -> WebexWebhookRecord:
        return await webex_webhooks.ensure_webhook(self, desired, owned_candidates)

    async def delete_webhook(self, webhook_id: str) -> None:
        await webex_webhooks.delete_webhook(self, webhook_id)

    async def reconcile_messages_webhooks(self) -> list[WebexWebhookRecord]:
        return await webex_webhooks.reconcile_messages_webhooks(self)

    async def reconcile_attachment_action_webhook(self) -> WebexWebhookRecord | None:
        return await webex_webhooks.reconcile_attachment_action_webhook(self)

    async def reconcile_messages_webhook(self) -> WebexWebhookRecord | None:
        return await webex_webhooks.reconcile_messages_webhook(self)

    def _webhook_matches(
        self,
        current: WebexWebhookRecord,
        desired: WebexWebhookRegistration,
    ) -> bool:
        return webex_webhooks.webhook_matches(self, current, desired)

    def _filters_match(self, current: str | None, desired: str | None) -> bool:
        return webex_webhooks.filters_match(self, current, desired)

    def _normalize_filter(
        self, raw_filter: str | None
    ) -> tuple[tuple[str, str], ...] | None:
        return webex_webhooks.normalize_filter(self, raw_filter)

    def _webhook_looks_app_owned(
        self,
        webhook: WebexWebhookRecord,
        desired: WebexWebhookRegistration | None = None,
    ) -> bool:
        return webex_webhooks.webhook_looks_app_owned(self, webhook, desired)

    async def fetch_inbound_message(
        self, envelope: WebexWebhookEnvelope
    ) -> InboundUserMessage | None:
        if self._is_self_authored(
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

        if self.config.webex_mock_mode:
            text = envelope.mock_text or "show device status"
            if not self._is_actionable_text(text):
                return None
            if not self._is_allowed_webex_sender(envelope.data.personEmail):
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
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            response = await client.get(
                f"/messages/{envelope.data.id}",
                headers=await self._auth_headers(),
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
            self._preview_text(details.text),
        )

        if self._is_self_authored(
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

        if not self._is_allowed_webex_sender(details.personEmail):
            logger.info(
                "Dropping disallowed Webex sender event_id=%s message_id=%s person_email=%s",
                envelope.id,
                details.id,
                details.personEmail,
            )
            return None

        if not self._is_actionable_text(details.text):
            logger.info(
                "Dropping non-actionable Webex message event_id=%s message_id=%s text_preview=%r",
                envelope.id,
                details.id,
                self._preview_text(details.text),
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
            self._preview_text(text),
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

    async def send_reply(self, reply: OutboundReply) -> None:
        if reply.skip_send:
            logger.info(
                "Skipping Webex reply send room_id=%s text_preview=%r",
                reply.room_id,
                self._preview_text(reply.text),
            )
            return

        if self.config.webex_mock_mode:
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
            self._preview_text(reply.text),
            reply.markdown is not None,
            len(reply.attachments),
        )

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            response = await client.post(
                "/messages",
                headers=await self._auth_headers(),
                json=payload,
            )
            _ = response.raise_for_status()
        logger.info(
            "Sent Webex reply room_id=%s status_code=%s",
            reply.room_id,
            response.status_code,
        )

    async def fetch_attachment_action_details(
        self, action_id: str
    ) -> WebexAttachmentActionDetails:
        if self.config.webex_mock_mode:
            return WebexAttachmentActionDetails(
                id=action_id,
                type="submit",
                messageId="mock-message-id",
                personId="mock-user",
                roomId="mock-room",
                inputs={},
            )

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            response = await client.get(
                f"/attachment/actions/{action_id}",
                headers=await self._auth_headers(),
            )
            _ = response.raise_for_status()
            return WebexAttachmentActionDetails.model_validate(response.json())

    async def send_direct_card_to_email(
        self,
        email: str,
        title: str,
        prompt: str,
        request_id: str,
        admin_session_id: str,
    ) -> None:
        if self.config.webex_mock_mode:
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
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            response = await client.post(
                "/messages",
                headers=await self._auth_headers(),
                json=payload,
            )
            _ = response.raise_for_status()

    async def fetch_person_email(self, person_id: str) -> str | None:
        if self.config.webex_mock_mode:
            return None
        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            response = await client.get(
                f"/people/{quote(person_id, safe='')}",
                headers=await self._auth_headers(),
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

    async def delete_message(self, message_id: str) -> None:
        if self.config.webex_mock_mode:
            logger.info("Mock Webex delete message: %s", message_id)
            return

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            response = await client.delete(
                f"/messages/{message_id}",
                headers=await self._auth_headers(),
            )
            _ = response.raise_for_status()
        logger.info("Deleted Webex message message_id=%s", message_id)

    def _is_actionable_text(self, text: str | None) -> bool:
        if text is None:
            return False

        normalized = text.strip()
        return bool(normalized)

    def _preview_text(self, text: str | None, limit: int = 120) -> str | None:
        if text is None:
            return None
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit]}…"

    def _is_self_authored(
        self,
        webhook_person_id: str | None = None,
        webhook_person_email: str | None = None,
        fetched_person_id: str | None = None,
        fetched_person_email: str | None = None,
    ) -> bool:
        if any(
            self._person_ids_match(self.bot_person_id, candidate_person_id)
            for candidate_person_id in (webhook_person_id, fetched_person_id)
        ):
            return True

        candidate_emails = {
            email.lower()
            for email in (webhook_person_email, fetched_person_email)
            if isinstance(email, str)
        }
        return bool(self.bot_emails.intersection(candidate_emails))

    def _is_allowed_webex_sender(self, person_email: str | None) -> bool:
        runtime_settings_provider = self._runtime_settings_provider
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
