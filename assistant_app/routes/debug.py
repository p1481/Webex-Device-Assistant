"""Debug routes for development and manual testing."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from shared.contracts import (
    ApprovalDecision,
    ExecutionMode,
    InboundUserMessage,
    MessageSource,
)

router = APIRouter()


class DebugMessageRequest(BaseModel):
    text: str
    session_id: str = "debug-session"
    user_id: str = "debug-user"
    room_id: str | None = "debug-room"
    preferred_mode: ExecutionMode | None = None
    target_device: str | None = None


class WebexSimulateMessageRequest(BaseModel):
    text: str = "show device status"
    room_id: str = "mock-room"
    person_id: str = "mock-person"
    person_email: str | None = "user@example.com"


@router.get("/debug/webex/runtime")
async def debug_webex_runtime(request: Request) -> dict[str, object]:
    services = request.app.state.services
    config = services.config
    runtime_settings = services.state_store.get_runtime_admin_settings()
    return {
        "webex_mock_mode": config.webex_mock_mode,
        "device_mock_mode": config.device_mock_mode,
        "default_execution_mode": config.default_execution_mode.value,
        "webex_api_base": config.webex_api_base,
        "webex_bot_person_id": config.webex_bot_person_id,
        "webex_bot_token_present": bool(config.webex_bot_token),
        "webex_webhook_secret_present": bool(config.webex_webhook_secret),
        "webex_webhook_target_url": config.webex_webhook_target_url,
        "webex_webhook_reconcile_on_startup": config.webex_webhook_reconcile_on_startup,
        "webex_token_manager_base_url": config.webex_token_manager_base_url,
        "webex_token_manager_api_key_present": bool(config.webex_token_manager_api_key),
        "default_user_email": runtime_settings.default_user_email,
        "allowed_webex_user_emails": list(runtime_settings.allowed_webex_user_emails),
    }


@router.post("/debug/webex/simulate-message", status_code=202)
async def debug_webex_simulate_message(
    request: Request,
    payload: WebexSimulateMessageRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    services = request.app.state.services
    config = services.config
    webex_gateway = services.webex_gateway
    webhook_controller = services.webhook_controller
    if not config.webex_mock_mode:
        raise HTTPException(
            status_code=409,
            detail="Webex webhook simulation requires WEBEX_MOCK_MODE=true.",
        )
    envelope_payload: dict[str, object] = {
        "id": f"mock-event-{uuid4()}",
        "resource": "messages",
        "event": "created",
        "data": {
            "id": f"mock-message-{uuid4()}",
            "roomId": payload.room_id,
            "personId": payload.person_id,
            "personEmail": payload.person_email,
        },
        "mockText": payload.text,
    }
    try:
        prepared_event = webex_gateway.parse_webhook_payload(envelope_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(webhook_controller.process_message_event, prepared_event)
    return {
        "status": "accepted",
        "event_id": prepared_event.id,
        "simulated_text": payload.text,
        "room_id": payload.room_id,
        "person_email": payload.person_email,
    }


@router.post("/debug/messages")
async def debug_message(request: Request, payload: DebugMessageRequest) -> dict[str, object]:
    orchestrator = request.app.state.services.orchestrator
    source = MessageSource.WEBEX if payload.target_device is not None else MessageSource.DEBUG
    inbound = InboundUserMessage(
        session_id=payload.session_id,
        user_id=payload.user_id,
        text=payload.text,
        source=source,
        room_id=payload.room_id,
        preferred_mode=payload.preferred_mode,
        target_device=payload.target_device,
    )
    reply = await orchestrator.handle_message(inbound)
    return {"reply": reply.model_dump()}


@router.post("/debug/approvals/{request_id}")
async def debug_approval_decision(
    request: Request,
    request_id: str,
    approved: bool,
    user_id: str = "debug-admin",
    email: str | None = "debug-admin@example.com",
    admin_session_id: str | None = None,
) -> dict[str, object]:
    services = request.app.state.services
    approval_manager = services.approval_manager
    orchestrator = services.orchestrator
    state_store = services.state_store
    resolved = approval_manager.approve_or_reject(
        ApprovalDecision(
            request_id=request_id,
            approved=approved,
            decided_by=user_id,
            decided_by_email=email,
            admin_session_id=admin_session_id,
        )
    )
    if resolved is None:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if approved and resolved.execution_request is not None:
        reply = await orchestrator.execute_approved_request(resolved)
        refreshed = state_store.get_approval_request(request_id) or resolved
        return {"approval": refreshed.model_dump(), "reply": reply.model_dump()}
    return {"approval": resolved.model_dump()}
