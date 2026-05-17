"""Webex webhook routes."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

router = APIRouter(prefix="/webhooks/webex")


@router.post("/messages", status_code=202)
async def webex_messages(
    request: Request,
    background_tasks: BackgroundTasks,
    x_spark_signature: Annotated[
        str | None, Header(alias="X-Spark-Signature")
    ] = None,
) -> dict[str, str]:
    services = request.app.state.services
    webhook_controller = services.webhook_controller
    webex_gateway = services.webex_gateway
    raw_body = await request.body()
    try:
        payload = webhook_controller.prepare_event(raw_body, x_spark_signature)
        prepared_event = webex_gateway.parse_webhook_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    background_tasks.add_task(
        webhook_controller.process_message_event, prepared_event
    )
    return {"status": "accepted", "event_id": prepared_event.id}


@router.post("/attachment-actions", status_code=202)
async def webex_attachment_actions(
    request: Request,
    background_tasks: BackgroundTasks,
    x_spark_signature: Annotated[
        str | None, Header(alias="X-Spark-Signature")
    ] = None,
) -> dict[str, str]:
    services = request.app.state.services
    webhook_controller = services.webhook_controller
    raw_body = await request.body()
    try:
        payload = webhook_controller.prepare_event(raw_body, x_spark_signature)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    background_tasks.add_task(
        webhook_controller.process_attachment_action_event, payload
    )
    raw_event_id = payload.get("id")
    event_id = raw_event_id if isinstance(raw_event_id, str) else "unknown"
    return {"status": "accepted", "event_id": event_id}
