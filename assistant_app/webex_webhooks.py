"""Webex webhook reconciliation helpers extracted from :mod:`webex_gateway`.

These functions take the :class:`WebexGateway` instance as the first argument so
that they can be called from thin instance-method wrappers on the gateway. This
keeps monkeypatch-based tests (which patch ``WebexGateway.list_webhooks`` etc.)
working unchanged while moving the actual logic out of the gateway module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qsl

import httpx

if TYPE_CHECKING:
    from assistant_app.webex_gateway import (
        WebexGateway,
        WebexWebhookRecord,
        WebexWebhookRegistration,
    )


def desired_messages_webhooks(
    gateway: WebexGateway,
) -> list[WebexWebhookRegistration]:
    from assistant_app.webex_gateway import WebexWebhookRegistration

    if not gateway.config.webex_webhook_target_url:
        raise RuntimeError(
            "WEBEX_WEBHOOK_TARGET_URL is required for webhook lifecycle operations."
        )
    if not gateway.config.webex_webhook_secret:
        raise RuntimeError(
            "WEBEX_WEBHOOK_SECRET is required for webhook lifecycle operations."
        )
    return [
        WebexWebhookRegistration(
            name=gateway.config.webex_webhook_direct_name,
            targetUrl=gateway.config.webex_webhook_target_url,
            resource=gateway.config.webex_webhook_resource,
            event=gateway.config.webex_webhook_event,
            filter=gateway.DIRECT_WEBHOOK_FILTER,
            secret=gateway.config.webex_webhook_secret,
        ),
        WebexWebhookRegistration(
            name=gateway.config.webex_webhook_group_name,
            targetUrl=gateway.config.webex_webhook_target_url,
            resource=gateway.config.webex_webhook_resource,
            event=gateway.config.webex_webhook_event,
            filter=gateway.GROUP_WEBHOOK_FILTER,
            secret=gateway.config.webex_webhook_secret,
        ),
    ]


def desired_attachment_action_webhook(
    gateway: WebexGateway,
) -> WebexWebhookRegistration:
    from assistant_app.webex_gateway import WebexWebhookRegistration

    if not gateway.config.webex_webhook_target_url:
        raise RuntimeError(
            "WEBEX_WEBHOOK_TARGET_URL is required for webhook lifecycle operations."
        )
    if not gateway.config.webex_webhook_secret:
        raise RuntimeError(
            "WEBEX_WEBHOOK_SECRET is required for webhook lifecycle operations."
        )
    attachment_target_url = gateway.config.webex_webhook_target_url.replace(
        "/webhooks/webex/messages",
        "/webhooks/webex/attachment-actions",
    )
    return WebexWebhookRegistration(
        name=gateway.ATTACHMENT_ACTIONS_WEBHOOK_NAME,
        targetUrl=attachment_target_url,
        resource="attachmentActions",
        event="created",
        filter=None,
        secret=gateway.config.webex_webhook_secret,
    )


async def list_webhooks(gateway: WebexGateway) -> list[WebexWebhookRecord]:
    from assistant_app.webex_gateway import WebexWebhookRecord

    if gateway.config.webex_mock_mode:
        return []

    async with httpx.AsyncClient(
        base_url=gateway.config.webex_api_base, timeout=10.0
    ) as client:
        response = await client.get("/webhooks", headers=await gateway._auth_headers())
        _ = response.raise_for_status()

    response_payload = cast(object, response.json())
    if not isinstance(response_payload, dict):
        raise RuntimeError("Unexpected Webex webhooks response shape.")

    response_payload_dict = cast(dict[str, object], response_payload)
    items = response_payload_dict.get("items", [])
    if not isinstance(items, list):
        raise RuntimeError("Unexpected Webex webhooks response shape.")
    item_list = cast(list[object], items)

    records: list[WebexWebhookRecord] = []
    for raw_item in item_list:
        if not isinstance(raw_item, dict):
            raise RuntimeError("Unexpected Webex webhooks response shape.")
        item_dict = cast(dict[str, object], raw_item)
        records.append(WebexWebhookRecord.model_validate(item_dict))

    return records


async def create_webhook(
    gateway: WebexGateway, registration: WebexWebhookRegistration
) -> WebexWebhookRecord:
    from assistant_app.webex_gateway import WebexWebhookRecord

    if gateway.config.webex_mock_mode:
        raise RuntimeError(
            "Webhook lifecycle operations are disabled in mock mode."
        )

    async with httpx.AsyncClient(
        base_url=gateway.config.webex_api_base, timeout=10.0
    ) as client:
        response = await client.post(
            "/webhooks",
            headers=await gateway._auth_headers(),
            json=registration.model_dump(by_alias=True, exclude_none=True),
        )
        _ = response.raise_for_status()

    return WebexWebhookRecord.model_validate(response.json())


async def ensure_webhook(
    gateway: WebexGateway,
    desired: WebexWebhookRegistration,
    owned_candidates: list[WebexWebhookRecord],
) -> WebexWebhookRecord:
    current = next(
        (
            webhook
            for webhook in owned_candidates
            if webhook_matches(gateway, webhook, desired)
        ),
        None,
    )
    if current is not None:
        return current

    for stale in owned_candidates:
        await gateway.delete_webhook(stale.id)

    try:
        return await gateway.create_webhook(desired)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 409:
            raise

    refreshed = await gateway.list_webhooks()
    refreshed_candidates = [
        webhook
        for webhook in refreshed
        if webhook.resource == desired.resource
        and webhook.event == desired.event
        and filters_match(gateway, webhook.filter, desired.filter)
        and webhook_looks_app_owned(gateway, webhook, desired)
    ]
    recovered = next(
        (
            webhook
            for webhook in refreshed_candidates
            if webhook_matches(gateway, webhook, desired)
        ),
        None,
    )
    if recovered is not None:
        return recovered

    raise RuntimeError(
        "Webhook reconciliation hit a conflict and could not recover the desired webhook state."
    )


async def delete_webhook(gateway: WebexGateway, webhook_id: str) -> None:
    if gateway.config.webex_mock_mode:
        raise RuntimeError(
            "Webhook lifecycle operations are disabled in mock mode."
        )

    async with httpx.AsyncClient(
        base_url=gateway.config.webex_api_base, timeout=10.0
    ) as client:
        response = await client.delete(
            f"/webhooks/{webhook_id}", headers=await gateway._auth_headers()
        )
        _ = response.raise_for_status()


async def reconcile_messages_webhooks(
    gateway: WebexGateway,
) -> list[WebexWebhookRecord]:
    if (
        gateway.config.webex_mock_mode
        or not gateway.config.webex_webhook_reconcile_on_startup
    ):
        return []

    desired_webhooks = gateway.desired_messages_webhooks()
    existing = await gateway.list_webhooks()
    matching = [
        webhook
        for webhook in existing
        if webhook.resource == gateway.config.webex_webhook_resource
        and webhook.event == gateway.config.webex_webhook_event
    ]
    reconciled: list[WebexWebhookRecord] = []
    owned_by_filter = {
        desired.filter: [
            webhook
            for webhook in matching
            if filters_match(gateway, webhook.filter, desired.filter)
            and webhook_looks_app_owned(gateway, webhook, desired)
        ]
        for desired in desired_webhooks
    }

    for desired in desired_webhooks:
        reconciled.append(
            await gateway.ensure_webhook(
                desired, owned_by_filter.get(desired.filter, [])
            )
        )

    return reconciled


async def reconcile_attachment_action_webhook(
    gateway: WebexGateway,
) -> WebexWebhookRecord | None:
    if (
        gateway.config.webex_mock_mode
        or not gateway.config.webex_webhook_reconcile_on_startup
    ):
        return None

    desired = gateway.desired_attachment_action_webhook()
    existing = await gateway.list_webhooks()
    owned_candidates = [
        webhook
        for webhook in existing
        if webhook.resource == desired.resource
        and webhook.event == desired.event
        and webhook_looks_app_owned(gateway, webhook, desired)
    ]
    return await gateway.ensure_webhook(desired, owned_candidates)


async def reconcile_messages_webhook(
    gateway: WebexGateway,
) -> WebexWebhookRecord | None:
    reconciled = await gateway.reconcile_messages_webhooks()
    return reconciled[0] if reconciled else None


def webhook_matches(
    gateway: WebexGateway,
    current: WebexWebhookRecord,
    desired: WebexWebhookRegistration,
) -> bool:
    secret_matches = current.secret in {None, desired.secret}
    return (
        current.name == desired.name
        and current.target_url == desired.target_url
        and current.resource == desired.resource
        and current.event == desired.event
        and filters_match(gateway, current.filter, desired.filter)
        and secret_matches
    )


def filters_match(
    gateway: WebexGateway, current: str | None, desired: str | None
) -> bool:
    return normalize_filter(gateway, current) == normalize_filter(gateway, desired)


def normalize_filter(
    gateway: WebexGateway, raw_filter: str | None
) -> tuple[tuple[str, str], ...] | None:
    if raw_filter is None:
        return None

    normalized_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(raw_filter, keep_blank_values=True):
        if key == "mentionedPeople" and value == "me":
            value = (
                gateway.bot_person_id or gateway.config.webex_bot_person_id or value
            )
        normalized_pairs.append((key, value))
    normalized_pairs.sort()
    return tuple(normalized_pairs)


def webhook_looks_app_owned(
    gateway: WebexGateway,
    webhook: WebexWebhookRecord,
    desired: WebexWebhookRegistration | None = None,
) -> bool:
    target_name = desired.name if desired is not None else None
    return (
        webhook.name
        in {
            gateway.config.webex_webhook_name,
            gateway.config.webex_webhook_direct_name,
            gateway.config.webex_webhook_group_name,
            target_name,
        }
        or webhook.target_url == gateway.config.webex_webhook_target_url
    )
