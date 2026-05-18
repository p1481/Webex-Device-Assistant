from __future__ import annotations

import logging
from base64 import b64decode
from typing import ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, Field

from assistant_app import webex_messages, webex_webhooks
from assistant_app.config import AppConfig
from assistant_app.token_provider import WebexTokenProvider
from shared.contracts import InboundUserMessage, OutboundReply

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
    ATTACHMENT_ACTIONS_WEBHOOK_NAME: ClassVar[str] = "webex-device-assistant-attachment-actions"
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

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
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

    async def create_webhook(self, registration: WebexWebhookRegistration) -> WebexWebhookRecord:
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

    def _normalize_filter(self, raw_filter: str | None) -> tuple[tuple[str, str], ...] | None:
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
        return await webex_messages.fetch_inbound_message(self, envelope)

    async def send_reply(self, reply: OutboundReply) -> None:
        await webex_messages.send_reply(self, reply)

    async def fetch_attachment_action_details(self, action_id: str) -> WebexAttachmentActionDetails:
        return await webex_messages.fetch_attachment_action_details(self, action_id)

    async def send_direct_card_to_email(
        self,
        email: str,
        title: str,
        prompt: str,
        request_id: str,
        admin_session_id: str,
    ) -> None:
        await webex_messages.send_direct_card_to_email(
            self, email, title, prompt, request_id, admin_session_id
        )

    async def fetch_person_email(self, person_id: str) -> str | None:
        return await webex_messages.fetch_person_email(self, person_id)

    async def delete_message(self, message_id: str) -> None:
        await webex_messages.delete_message(self, message_id)

    def _is_actionable_text(self, text: str | None) -> bool:
        return webex_messages.is_actionable_text(text)

    def _preview_text(self, text: str | None, limit: int = 120) -> str | None:
        return webex_messages.preview_text(text, limit)

    def _is_self_authored(
        self,
        webhook_person_id: str | None = None,
        webhook_person_email: str | None = None,
        fetched_person_id: str | None = None,
        fetched_person_email: str | None = None,
    ) -> bool:
        return webex_messages.is_self_authored(
            self,
            webhook_person_id=webhook_person_id,
            webhook_person_email=webhook_person_email,
            fetched_person_id=fetched_person_id,
            fetched_person_email=fetched_person_email,
        )

    def _is_allowed_webex_sender(self, person_email: str | None) -> bool:
        return webex_messages.is_allowed_webex_sender(self, person_email)
