"""Admin API routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from assistant_app.admin_auth import (
    attach_admin_session_cookie,
    clear_admin_session_cookie,
    get_authenticated_admin_session,
)
from shared.contracts import (
    AdminAuthRequest,
    AdminAuthSession,
    AdminAuthStartResponse,
    AdminAuthStatusResponse,
    CommandPolicy,
    InboundUserMessage,
    Intent,
    MessageSource,
    ProviderSettings,
    RuntimeAdminSettings,
    RuntimeAdminSettingsUpdate,
)

router = APIRouter()


def _is_allowed_admin_login(runtime_settings: RuntimeAdminSettings, email: str) -> bool:
    if email in runtime_settings.allowed_admin_emails:
        return True
    return (
        not runtime_settings.allowed_admin_emails and email == runtime_settings.default_user_email
    )


def _serialize_provider_settings(settings: ProviderSettings) -> dict[str, object]:
    payload = settings.model_dump()
    payload["api_key"] = None
    return payload


def require_admin_session(request: Request) -> AdminAuthSession:
    return get_authenticated_admin_session(request)


@router.post("/admin/auth/start")
async def admin_auth_start(payload: AdminAuthRequest, request: Request) -> dict[str, object]:
    services = request.app.state.services
    admin_service = services.admin_service
    approval_manager = services.approval_manager
    webex_gateway = services.webex_gateway

    runtime_settings = admin_service.get_runtime_admin_settings()
    if not _is_allowed_admin_login(runtime_settings, payload.email):
        raise HTTPException(status_code=403, detail="Admin email is not allowed.")

    auth_session = admin_service.create_admin_auth_session(
        AdminAuthSession(
            session_id=str(uuid4()),
            email=payload.email,
            approval_request_id="",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    approval_request = approval_manager.create_admin_auth_request(
        InboundUserMessage(
            session_id=f"admin-auth:{auth_session.session_id}",
            user_id=payload.email,
            person_email=payload.email,
            text="admin login",
            source=MessageSource.WEBEX,
            room_id=None,
        ),
        admin_session_id=auth_session.session_id,
    )
    auth_session.approval_request_id = approval_request.request_id
    _ = admin_service.update_admin_auth_session(auth_session)
    await webex_gateway.send_direct_card_to_email(
        payload.email,
        approval_request.title,
        approval_request.prompt,
        approval_request.request_id,
        auth_session.session_id,
    )
    return AdminAuthStartResponse(
        session_id=auth_session.session_id,
        status="pending",
    ).model_dump()


@router.get("/admin/auth/status/{session_id}")
async def admin_auth_status(
    session_id: str,
    request: Request,
    response: Response,
) -> dict[str, object]:
    services = request.app.state.services
    admin_service = services.admin_service
    state_store = services.state_store

    auth_session = admin_service.get_admin_auth_session(session_id)
    if auth_session is None:
        raise HTTPException(status_code=404, detail="Admin auth session not found.")
    if auth_session.expires_at is not None and auth_session.expires_at <= datetime.now(UTC):
        admin_service.delete_admin_auth_session(session_id)
        clear_admin_session_cookie(response)
        return AdminAuthStatusResponse(
            session_id=session_id,
            status="expired",
            email=auth_session.email,
        ).model_dump()

    approval = state_store.get_approval_request(auth_session.approval_request_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    status = approval.status.value
    if status in {"approved", "executed"}:
        if not auth_session.approved:
            auth_session.approved = True
            auth_session.approved_at = datetime.now(UTC)
            _ = admin_service.update_admin_auth_session(auth_session)
        attach_admin_session_cookie(response, request, auth_session.session_id)
    return AdminAuthStatusResponse(
        session_id=session_id,
        status=status,
        email=auth_session.email,
    ).model_dump()


@router.post("/admin/auth/logout")
async def admin_auth_logout(request: Request, response: Response) -> dict[str, str]:
    services = request.app.state.services
    admin_service = services.admin_service
    try:
        auth_session = get_authenticated_admin_session(request)
    except HTTPException:
        auth_session = None
    if auth_session is not None:
        admin_service.delete_admin_auth_session(auth_session.session_id)
    clear_admin_session_cookie(response)
    return {"status": "logged_out"}


@router.get("/admin/providers")
async def list_provider_descriptors(
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    admin_service = request.app.state.services.admin_service
    return {
        "providers": [
            descriptor.model_dump() for descriptor in admin_service.list_provider_descriptors()
        ],
        "active": _serialize_provider_settings(admin_service.get_provider_settings()),
    }


@router.get("/admin/settings")
async def get_admin_settings(
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    admin_service = request.app.state.services.admin_service
    return {
        "runtime": admin_service.get_runtime_admin_settings().model_dump(),
        "startup": admin_service.get_startup_config_status().model_dump(),
    }


@router.put("/admin/settings")
async def update_admin_settings(
    payload: RuntimeAdminSettingsUpdate,
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    admin_service = request.app.state.services.admin_service
    updated = admin_service.update_runtime_admin_settings(payload)
    return {"runtime": updated.model_dump()}


@router.put("/admin/providers")
async def update_provider_settings(
    payload: ProviderSettings,
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    services = request.app.state.services
    admin_service = services.admin_service
    provider_registry = services.provider_registry
    orchestrator = services.orchestrator
    all_llm_tool_runtime = services.all_llm_tool_runtime
    config = services.config

    can_apply, reason = await admin_service.can_apply_provider_live(payload)
    if not can_apply:
        raise HTTPException(status_code=409, detail=reason)
    updated = admin_service.update_provider_settings(payload)
    new_provider = provider_registry.build_analysis_provider(updated)
    orchestrator.provider = new_provider
    all_llm_tool_runtime.provider = provider_registry.build_chat_provider(updated)
    all_llm_tool_runtime.model = (
        updated.model or config.default_provider_model or "rule-based-default"
    )
    return {"provider": _serialize_provider_settings(updated)}


@router.get("/admin/policies")
async def list_policies(
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    admin_service = request.app.state.services.admin_service
    return {
        "policies": {
            intent.value: policy.model_dump()
            for intent, policy in admin_service.list_policies().items()
        }
    }


@router.put("/admin/policies/{intent_name}")
async def update_policy(
    intent_name: str,
    payload: CommandPolicy,
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    admin_service = request.app.state.services.admin_service
    intent = Intent(intent_name)
    updated = admin_service.update_policy(intent, payload)
    return {"intent": intent.value, "policy": updated.model_dump()}


@router.get("/admin/approvals")
async def list_approvals(
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    admin_service = request.app.state.services.admin_service
    return {"approvals": [req.model_dump() for req in admin_service.list_approval_requests()]}


@router.get("/admin/audit")
async def list_audit(
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    state_store = request.app.state.services.state_store
    return {"audit": [record.model_dump() for record in state_store.list_audit_records()]}


@router.get("/admin/actions")
async def list_actions(
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    admin_service = request.app.state.services.admin_service
    return {"actions": [action.model_dump() for action in admin_service.list_action_registry()]}


@router.get("/admin/devices")
async def list_devices(
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    services = request.app.state.services
    device_client = services.device_client
    state_store = services.state_store
    devices = await device_client.list_devices()
    stored = state_store.set_organization_devices(devices)
    return {"devices": [device.model_dump() for device in stored]}


@router.get("/admin/stats")
async def get_stats(
    request: Request,
    _admin_session: AdminAuthSession = Depends(require_admin_session),
) -> dict[str, object]:
    admin_service = request.app.state.services.admin_service
    return {"stats": admin_service.get_stats().model_dump()}
