from __future__ import annotations

import hashlib
import hmac
import json
import logging

from shared.contracts import ApprovalDecision, ApprovalStatus

from assistant_app.memory_store import InMemorySessionStore
from assistant_app.state_store import InMemoryStateStore
from assistant_app.approval_manager import ApprovalManager
from assistant_app.orchestrator import Orchestrator
from assistant_app.webex_gateway import WebexGateway, WebexWebhookEnvelope


logger = logging.getLogger(__name__)


class WebhookController:
    def __init__(
        self,
        webhook_secret: str | None,
        gateway: WebexGateway,
        orchestrator: Orchestrator,
        approval_manager: ApprovalManager,
        memory_store: InMemorySessionStore,
        processed_event_store: InMemoryStateStore | None = None,
    ) -> None:
        self.webhook_secret: str | None = webhook_secret
        self.gateway: WebexGateway = gateway
        self.orchestrator: Orchestrator = orchestrator
        self.approval_manager: ApprovalManager = approval_manager
        self.memory_store: InMemorySessionStore = memory_store
        self.processed_event_store: InMemoryStateStore | None = processed_event_store

    def prepare_event(
        self, raw_body: bytes, signature: str | None
    ) -> dict[str, object]:
        self._verify_signature(raw_body, signature)
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Webhook payload must be a JSON object.")
        return payload

    async def process_message_event(self, event: WebexWebhookEnvelope) -> None:
        event_key = self._message_event_key(event)
        if self._has_processed_event(event_key):
            logger.info(
                "Skipping already-processed Webex event_key=%s raw_event_id=%s",
                event_key,
                event.id,
            )
            return
        phase = "fetch_inbound_message"
        try:
            logger.info(
                "Processing Webex message event_key=%s raw_event_id=%s room_id=%s person_id=%s",
                event_key,
                event.id,
                event.data.roomId,
                event.data.personId,
            )
            message = await self.gateway.fetch_inbound_message(event)
            if message is None:
                self._mark_processed_event(event_key)
                logger.info(
                    "Finished Webex event_key=%s raw_event_id=%s with no actionable inbound message",
                    event_key,
                    event.id,
                )
                return

            phase = "handle_message"
            reply = await self.orchestrator.handle_message(message)

            logger.info(
                "Built Webex reply event_id=%s room_id=%s text_preview=%r skip_send=%s",
                event.id,
                reply.room_id,
                self.gateway._preview_text(reply.text),
                reply.skip_send,
            )

            phase = "send_reply"
            await self.gateway.send_reply(reply)
            self._mark_processed_event(event_key)
            logger.info(
                "Completed Webex message event_key=%s raw_event_id=%s",
                event_key,
                event.id,
            )
        except Exception:
            logger.exception(
                "Failed to process Webex message event key=%s raw_event_id=%s during %s.",
                event_key,
                event.id,
                phase,
            )

    async def process_attachment_action_event(self, payload: dict[str, object]) -> None:
        raw_event_id = payload.get("id")
        if not isinstance(raw_event_id, str):
            raise ValueError("Attachment action event id is required.")

        phase = "read_event"
        try:
            data = payload.get("data")
            if not isinstance(data, dict):
                raise ValueError("Attachment action event data is required.")

            action_id = data.get("id")
            if not isinstance(action_id, str):
                raise ValueError("Attachment action id is required.")

            logger.info(
                "Processing attachment action raw_event_id=%s action_id=%s",
                raw_event_id,
                action_id,
            )
            if self._has_processed_event(action_id):
                logger.info(
                    "Skipping already-processed attachment action raw_event_id=%s action_id=%s",
                    raw_event_id,
                    action_id,
                )
                return

            phase = "fetch_action_details"
            details = await self.gateway.fetch_attachment_action_details(action_id)

            phase = "fetch_person_email"
            try:
                decided_by_email = await self.gateway.fetch_person_email(
                    details.personId
                )
            except Exception:
                logger.exception(
                    "Failed to fetch person email for attachment action raw_event_id=%s action_id=%s person_id=%s",
                    raw_event_id,
                    action_id,
                    details.personId,
                )
                decided_by_email = None

            kind = details.inputs.get("kind")
            if kind == "entity_selection":
                pending_action_id = details.inputs.get("pendingActionId")
                field_name = details.inputs.get("fieldName")
                selection_decision = details.inputs.get("selectionDecision")
                selected_value = details.inputs.get("selectedValue")
                if not isinstance(pending_action_id, str) or not isinstance(
                    field_name, str
                ):
                    raise ValueError(
                        "Entity selection inputs must include pendingActionId and fieldName."
                    )
                phase = "resume_selection"
                (
                    reply,
                    resolved,
                ) = await self.orchestrator.resume_pending_action_selection(
                    pending_action_id=pending_action_id,
                    field_name=field_name,
                    selected_value=selected_value
                    if isinstance(selected_value, str)
                    else None,
                    user_id=details.personId,
                    room_id=details.roomId,
                    person_email=decided_by_email,
                    cancel=(
                        isinstance(selection_decision, str)
                        and selection_decision.lower() == "cancel"
                    ),
                )
                if resolved and details.messageId:
                    phase = "delete_selection_card"
                    try:
                        await self.gateway.delete_message(details.messageId)
                    except Exception:
                        logger.exception(
                            "Failed to delete resolved selection card message_id=%s pending_action_id=%s",
                            details.messageId,
                            pending_action_id,
                        )
                phase = "send_selection_reply"
                await self.gateway.send_reply(reply)
                self._mark_processed_event(action_id)
                return

            request_id = details.inputs.get("requestId")
            decision = details.inputs.get("decision")
            admin_session_id = details.inputs.get("adminSessionId")
            if not isinstance(request_id, str) or not isinstance(decision, str):
                raise ValueError(
                    "Attachment action inputs must include requestId and decision."
                )

            phase = "resolve_approval"
            resolved = self.approval_manager.approve_or_reject(
                ApprovalDecision(
                    request_id=request_id,
                    approved=decision.lower() == "approve",
                    decided_by=details.personId,
                    decided_by_email=decided_by_email,
                    admin_session_id=(
                        admin_session_id if isinstance(admin_session_id, str) else None
                    ),
                    attachment_action_id=details.id,
                )
            )
            if resolved is not None and details.messageId:
                phase = "delete_approval_card"
                try:
                    await self.gateway.delete_message(details.messageId)
                except Exception:
                    logger.exception(
                        "Failed to delete resolved approval card message_id=%s request_id=%s",
                        details.messageId,
                        request_id,
                    )
            if (
                resolved is None
                or resolved.status != ApprovalStatus.APPROVED
                or resolved.execution_request is None
            ):
                self._mark_processed_event(action_id)
                return

            phase = "execute_approved_request"
            reply = await self.orchestrator.execute_approved_request(resolved)
            phase = "send_approval_reply"
            await self.gateway.send_reply(reply)
            self._mark_processed_event(action_id)
        except Exception:
            logger.exception(
                "Failed to process attachment action raw_event_id=%s during %s.",
                raw_event_id,
                phase,
            )

    def _has_processed_event(self, event_id: str) -> bool:
        return self.memory_store.has_processed_event(event_id) or (
            self.processed_event_store is not None
            and self.processed_event_store.has_processed_webhook_event(event_id)
        )

    def _mark_processed_event(self, event_id: str) -> None:
        self.memory_store.mark_processed_event(event_id)
        if self.processed_event_store is not None:
            self.processed_event_store.mark_processed_webhook_event(event_id)

    def _verify_signature(self, raw_body: bytes, signature: str | None) -> None:
        if not self.webhook_secret:
            return
        if not signature:
            raise ValueError("Missing X-Spark-Signature header.")

        digest = hmac.new(
            self.webhook_secret.encode("utf-8"), raw_body, hashlib.sha1
        ).hexdigest()
        if not hmac.compare_digest(digest, signature):
            raise ValueError("Invalid X-Spark-Signature header.")

    def _message_event_key(self, event: WebexWebhookEnvelope) -> str:
        return event.data.id or event.id
