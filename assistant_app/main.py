from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, ClassVar
from typing import cast

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, ConfigDict

from admin_page import router as admin_page_router
from assistant_app.action_registry import build_default_action_registry
from assistant_app.agentic_tool_runtime import AllLlmToolRuntime
from assistant_app.admin_auth import (
    attach_admin_session_cookie,
    clear_admin_session_cookie,
    get_authenticated_admin_session,
)
from assistant_app.admin_service import AdminService
from assistant_app.approval_manager import ApprovalManager
from assistant_app.config import AppConfig
from assistant_app.memory_store import InMemorySessionStore
from assistant_app.mode_router import ModeRouter
from assistant_app.orchestrator import Orchestrator
from assistant_app.policy_evaluator import PolicyEvaluator
from assistant_app.provider_registry import ProviderRegistry
from assistant_app.state_store import InMemoryStateStore, build_state_store
from assistant_app.token_provider import TokenManagerTokenProvider
from assistant_app.webex_gateway import WebexBotIdentityMismatchError, WebexGateway
from assistant_app.webhook_controller import WebhookController
from device_executor.device_client import DeviceClient
from device_executor.executor import DeviceExecutor
from device_executor.handlers import ExecutionHandlers
from direct_tool_adapter.adapter import DirectToolAdapter
from direct_tool_adapter.tools import DirectToolSet
from shared.contracts import (
    AdminAuthRequest,
    AdminAuthSession,
    AdminAuthStartResponse,
    AdminAuthStatusResponse,
    ApprovalDecision,
    CommandPolicy,
    ExecutionMode,
    InboundUserMessage,
    Intent,
    MaskedSecret,
    MessageSource,
    ProviderKind,
    ProviderSettings,
    RuntimeAdminSettings,
    RuntimeAdminSettingsUpdate,
    StartupConfigStatus,
)


logger = logging.getLogger(__name__)


def _is_allowed_admin_login(runtime_settings: RuntimeAdminSettings, email: str) -> bool:
    if email in runtime_settings.allowed_admin_emails:
        return True
    return (
        not runtime_settings.allowed_admin_emails
        and email == runtime_settings.default_user_email
    )


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


class AppServices(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)

    config: AppConfig
    orchestrator: Orchestrator
    webhook_controller: WebhookController
    webex_gateway: WebexGateway
    approval_manager: ApprovalManager
    admin_service: AdminService
    state_store: InMemoryStateStore
    provider_registry: ProviderRegistry


def _serialize_provider_settings(settings: ProviderSettings) -> dict[str, object]:
    payload = settings.model_dump()
    payload["api_key"] = None
    return payload


def _configure_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)

    has_assistant_handler = any(
        cast(bool, getattr(handler, "_assistant_app_handler", False))
        for handler in root_logger.handlers
    )
    if not has_assistant_handler:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        setattr(handler, "_assistant_app_handler", True)
        root_logger.addHandler(handler)

    for logger_name in (
        "assistant_app.main",
        "assistant_app.webex_gateway",
        "assistant_app.webhook_controller",
    ):
        logging.getLogger(logger_name).setLevel(logging.INFO)


def build_app() -> FastAPI:
    _configure_logging()
    config = AppConfig.from_env()
    memory_store = InMemorySessionStore()
    state_store = build_state_store(config.admin_state_path)
    token_provider = TokenManagerTokenProvider(
        base_url=config.webex_token_manager_base_url,
        api_key=config.webex_token_manager_api_key or "",
        fallback_token=config.webex_bot_token,
    )
    _ = state_store.set_runtime_admin_settings(
        RuntimeAdminSettings(
            access_token=MaskedSecret(
                present=(
                    not config.webex_mock_mode
                    and not config.device_mock_mode
                    and bool(config.webex_token_manager_api_key)
                ),
                masked_value=(
                    "***token-manager-configured***"
                    if (
                        not config.webex_mock_mode
                        and not config.device_mock_mode
                        and bool(config.webex_token_manager_api_key)
                    )
                    else None
                ),
                field_state="restart_required",
            ),
            bot_token=MaskedSecret(
                present=bool(config.webex_bot_token),
                masked_value=(
                    "***configured***" if config.webex_bot_token is not None else None
                ),
                field_state="restart_required",
            ),
            webhook_secret=MaskedSecret(
                present=bool(config.webex_webhook_secret),
                masked_value=(
                    "***configured***"
                    if config.webex_webhook_secret is not None
                    else None
                ),
                field_state="restart_required",
            ),
            webhook_url=config.webex_webhook_target_url,
            default_user_email="youngcle@cisco.com",
            default_execution_mode=config.default_execution_mode,
            selected_provider=config.default_provider,
            selected_provider_model=config.default_provider_model,
            selected_device_name=config.default_target_device,
            webex_mock_mode=config.webex_mock_mode,
            device_mock_mode=config.device_mock_mode,
        )
    )
    current_provider_settings = state_store.get_provider_settings()
    if (
        current_provider_settings.provider == ProviderKind.RULE_BASED
        and current_provider_settings.model == "rule-based-default"
        and current_provider_settings.base_url is None
    ):
        _ = state_store.update_provider_settings(
            ProviderSettings(
                provider=config.default_provider,
                model=config.default_provider_model,
                base_url=config.default_provider_base_url,
                enabled=True,
            )
        )
    _ = state_store.set_startup_config_status(
        StartupConfigStatus(
            webhook_url=config.webex_webhook_target_url,
            webex_token_manager_base_url=config.webex_token_manager_base_url,
            webex_bot_person_id=config.webex_bot_person_id,
            webex_mock_mode=config.webex_mock_mode,
            device_mock_mode=config.device_mock_mode,
            reconcile_on_startup=config.webex_webhook_reconcile_on_startup,
            required_restart_fields=[
                "access_token",
                "bot_token",
                "webhook_secret",
                "webhook_url",
                "webex_mock_mode",
                "device_mock_mode",
            ],
        )
    )
    state_store.set_action_registry(build_default_action_registry())
    provider_registry = ProviderRegistry(
        default_target_device=config.default_target_device
    )
    state_store.register_provider_descriptors(provider_registry.descriptors())
    provider_settings = state_store.get_provider_settings()
    provider = provider_registry.build_analysis_provider(provider_settings)
    policy_evaluator = PolicyEvaluator(
        default_mode=config.default_execution_mode,
        state_store=state_store,
    )
    device_client = DeviceClient(config, token_provider)
    device_executor = DeviceExecutor(ExecutionHandlers(device_client))
    direct_tool_adapter = DirectToolAdapter(DirectToolSet(device_client))
    all_llm_tool_runtime = AllLlmToolRuntime(
        provider_registry.build_chat_provider(provider_settings),
        direct_tool_adapter,
        model=provider_settings.model or config.default_provider_model or "rule-based-default",
    )
    mode_router = ModeRouter(
        device_executor, direct_tool_adapter, all_llm_tool_runtime
    )
    approval_manager = ApprovalManager(memory_store, state_store)
    admin_service = AdminService(state_store)
    orchestrator = Orchestrator(
        provider,
        memory_store,
        policy_evaluator,
        mode_router,
        approval_manager,
        device_lister=device_client.list_devices,
        camera_mode_lister=device_client.list_supported_camera_modes,
    )
    webex_gateway = WebexGateway(
        config,
        runtime_settings_provider=state_store.get_runtime_admin_settings,
    )

    webhook_controller = WebhookController(
        webhook_secret=config.webex_webhook_secret,
        gateway=webex_gateway,
        orchestrator=orchestrator,
        approval_manager=approval_manager,
        memory_store=memory_store,
        processed_event_store=state_store,
    )

    app = FastAPI(title=config.app_name, version="0.1.0")
    app.state.services = AppServices(
        config=config,
        orchestrator=orchestrator,
        webhook_controller=webhook_controller,
        webex_gateway=webex_gateway,
        approval_manager=approval_manager,
        admin_service=admin_service,
        state_store=state_store,
        provider_registry=provider_registry,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if not config.webex_mock_mode:
            try:
                _ = await webex_gateway.resolve_bot_identity()
            except WebexBotIdentityMismatchError:
                logger.exception(
                    "Startup bot identity verification failed due to configured person-id mismatch."
                )
                raise
            except Exception:
                logger.exception(
                    "Startup bot identity resolution failed; continuing startup without resolved identity."
                )
        if config.webex_webhook_reconcile_on_startup:
            try:
                reconciled_webhooks = await webex_gateway.reconcile_messages_webhooks()
                reconciled_attachment_actions = (
                    await webex_gateway.reconcile_attachment_action_webhook()
                )
                _ = reconciled_webhooks
                _ = reconciled_attachment_actions
            except Exception:
                logger.exception(
                    "Startup webhook reconciliation failed; continuing startup."
                )
        yield

    app.router.lifespan_context = lifespan

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "default_execution_mode": config.default_execution_mode.value,
            "webex_mock_mode": str(config.webex_mock_mode).lower(),
            "device_mock_mode": str(config.device_mock_mode).lower(),
        }

    @app.get("/debug/webex/runtime")
    async def debug_webex_runtime() -> dict[str, object]:
        runtime_settings = state_store.get_runtime_admin_settings()
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
            "webex_token_manager_api_key_present": bool(
                config.webex_token_manager_api_key
            ),
            "default_user_email": runtime_settings.default_user_email,
            "allowed_webex_user_emails": list(
                runtime_settings.allowed_webex_user_emails
            ),
        }

    @app.post("/debug/webex/simulate-message", status_code=202)
    async def debug_webex_simulate_message(
        payload: WebexSimulateMessageRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
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
        background_tasks.add_task(
            webhook_controller.process_message_event, prepared_event
        )
        return {
            "status": "accepted",
            "event_id": prepared_event.id,
            "simulated_text": payload.text,
            "room_id": payload.room_id,
            "person_email": payload.person_email,
        }

    @app.post("/debug/messages")
    async def debug_message(payload: DebugMessageRequest) -> dict[str, object]:
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

    @app.post("/webhooks/webex/messages", status_code=202)
    async def webex_messages(
        request: Request,
        background_tasks: BackgroundTasks,
        x_spark_signature: Annotated[
            str | None, Header(alias="X-Spark-Signature")
        ] = None,
    ) -> dict[str, str]:
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

    @app.post("/webhooks/webex/attachment-actions", status_code=202)
    async def webex_attachment_actions(
        request: Request,
        background_tasks: BackgroundTasks,
        x_spark_signature: Annotated[
            str | None, Header(alias="X-Spark-Signature")
        ] = None,
    ) -> dict[str, str]:
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

    @app.post("/debug/approvals/{request_id}")
    async def debug_approval_decision(
        request_id: str,
        approved: bool,
        user_id: str = "debug-admin",
        email: str | None = "debug-admin@example.com",
        admin_session_id: str | None = None,
    ) -> dict[str, object]:
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

    def require_admin_session(request: Request) -> AdminAuthSession:
        return get_authenticated_admin_session(request)

    @app.post("/admin/auth/start")
    async def admin_auth_start(payload: AdminAuthRequest) -> dict[str, object]:
        runtime_settings = admin_service.get_runtime_admin_settings()
        if not _is_allowed_admin_login(runtime_settings, payload.email):
            raise HTTPException(status_code=403, detail="Admin email is not allowed.")

        auth_session = admin_service.create_admin_auth_session(
            AdminAuthSession(
                session_id=str(uuid4()),
                email=payload.email,
                approval_request_id="",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
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

    @app.get("/admin/auth/status/{session_id}")
    async def admin_auth_status(
        session_id: str,
        request: Request,
        response: Response,
    ) -> dict[str, object]:
        auth_session = admin_service.get_admin_auth_session(session_id)
        if auth_session is None:
            raise HTTPException(status_code=404, detail="Admin auth session not found.")
        if (
            auth_session.expires_at is not None
            and auth_session.expires_at <= datetime.now(timezone.utc)
        ):
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
                auth_session.approved_at = datetime.now(timezone.utc)
                _ = admin_service.update_admin_auth_session(auth_session)
            attach_admin_session_cookie(response, request, auth_session.session_id)
        return AdminAuthStatusResponse(
            session_id=session_id,
            status=status,
            email=auth_session.email,
        ).model_dump()

    @app.post("/admin/auth/logout")
    async def admin_auth_logout(request: Request, response: Response) -> dict[str, str]:
        try:
            auth_session = get_authenticated_admin_session(request)
        except HTTPException:
            auth_session = None
        if auth_session is not None:
            admin_service.delete_admin_auth_session(auth_session.session_id)
        clear_admin_session_cookie(response)
        return {"status": "logged_out"}

    @app.get("/admin/providers")
    async def list_provider_descriptors(
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        return {
            "providers": [
                descriptor.model_dump()
                for descriptor in admin_service.list_provider_descriptors()
            ],
            "active": _serialize_provider_settings(
                admin_service.get_provider_settings()
            ),
        }

    @app.get("/admin/settings")
    async def get_admin_settings(
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        return {
            "runtime": admin_service.get_runtime_admin_settings().model_dump(),
            "startup": admin_service.get_startup_config_status().model_dump(),
        }

    @app.put("/admin/settings")
    async def update_admin_settings(
        payload: RuntimeAdminSettingsUpdate,
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        updated = admin_service.update_runtime_admin_settings(payload)
        return {"runtime": updated.model_dump()}

    @app.put("/admin/providers")
    async def update_provider_settings(
        payload: ProviderSettings,
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
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

    @app.get("/admin/policies")
    async def list_policies(
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        return {
            "policies": {
                intent.value: policy.model_dump()
                for intent, policy in admin_service.list_policies().items()
            }
        }

    @app.put("/admin/policies/{intent_name}")
    async def update_policy(
        intent_name: str,
        payload: CommandPolicy,
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        intent = Intent(intent_name)
        updated = admin_service.update_policy(intent, payload)
        return {"intent": intent.value, "policy": updated.model_dump()}

    @app.get("/admin/approvals")
    async def list_approvals(
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        return {
            "approvals": [
                request.model_dump()
                for request in admin_service.list_approval_requests()
            ]
        }

    @app.get("/admin/audit")
    async def list_audit(
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        return {
            "audit": [
                record.model_dump() for record in state_store.list_audit_records()
            ]
        }

    @app.get("/admin/actions")
    async def list_actions(
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        return {
            "actions": [
                action.model_dump() for action in admin_service.list_action_registry()
            ]
        }

    @app.get("/admin/devices")
    async def list_devices(
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        devices = await device_client.list_devices()
        stored = state_store.set_organization_devices(devices)
        return {"devices": [device.model_dump() for device in stored]}

    @app.get("/admin/stats")
    async def get_stats(
        _admin_session: AdminAuthSession = Depends(require_admin_session),
    ) -> dict[str, object]:
        return {"stats": admin_service.get_stats().model_dump()}

    app.include_router(admin_page_router)

    return app


app = build_app()
