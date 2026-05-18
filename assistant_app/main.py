from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import ClassVar

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict

from admin_page import router as admin_page_router
from assistant_app.action_registry import build_default_action_registry
from assistant_app.admin_service import AdminService
from assistant_app.agentic_tool_runtime import AllLlmToolRuntime
from assistant_app.approval_manager import ApprovalManager
from assistant_app.config import AppConfig
from assistant_app.logging_config import (
    bind_request_context,
    clear_request_context,
    configure_logging,
)
from assistant_app.memory_store import InMemorySessionStore
from assistant_app.metrics import approvals_pending
from assistant_app.mode_router import ModeRouter
from assistant_app.orchestrator import Orchestrator
from assistant_app.policy_evaluator import PolicyEvaluator
from assistant_app.provider_registry import ProviderRegistry
from assistant_app.routes.admin import router as admin_router
from assistant_app.routes.debug import router as debug_router
from assistant_app.routes.health import router as health_router
from assistant_app.routes.metrics import router as metrics_router
from assistant_app.routes.webhooks import router as webhooks_router
from assistant_app.state_store import InMemoryStateStore, build_state_store
from assistant_app.token_provider import TokenManagerTokenProvider
from assistant_app.tracing import configure_tracing
from assistant_app.webex_gateway import WebexBotIdentityMismatchError, WebexGateway
from assistant_app.webhook_controller import WebhookController
from device_executor.device_client import DeviceClient
from device_executor.executor import DeviceExecutor
from device_executor.handlers import ExecutionHandlers
from direct_tool_adapter.adapter import DirectToolAdapter
from direct_tool_adapter.tools import DirectToolSet
from shared.contracts import (
    ApprovalStatus,
    MaskedSecret,
    ProviderSettings,
    RuntimeAdminSettings,
    StartupConfigStatus,
)

logger = logging.getLogger(__name__)


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
    device_client: DeviceClient
    all_llm_tool_runtime: AllLlmToolRuntime


def _serialize_provider_settings(settings: ProviderSettings) -> dict[str, object]:
    payload = settings.model_dump()
    payload["api_key"] = None
    return payload


def _configure_logging() -> None:
    configure_logging()


def build_app() -> FastAPI:
    _configure_logging()
    config = AppConfig.from_env()
    memory_store = InMemorySessionStore()
    state_store = build_state_store(config.admin_state_path)

    # Wire the approvals_pending gauge to the state store so /metrics
    # reports the true count on every scrape (no event-based inc/dec to
    # drift over time).
    approvals_pending.set_function(
        lambda: float(
            sum(
                1
                for approval in state_store.list_approval_requests()
                if approval.status == ApprovalStatus.PENDING
            )
        )
    )
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
                masked_value=("***configured***" if config.webex_bot_token is not None else None),
                field_state="restart_required",
            ),
            webhook_secret=MaskedSecret(
                present=bool(config.webex_webhook_secret),
                masked_value=(
                    "***configured***" if config.webex_webhook_secret is not None else None
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
    if not state_store.is_provider_settings_persisted():
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
    provider_registry = ProviderRegistry(default_target_device=config.default_target_device)
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
    mode_router = ModeRouter(device_executor, direct_tool_adapter, all_llm_tool_runtime)
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
    configure_tracing(app)

    @app.middleware("http")
    async def _request_context_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        bind_request_context(request_id=request_id, path=request.url.path, method=request.method)
        try:
            response = await call_next(request)
        finally:
            clear_request_context()
        response.headers["x-request-id"] = request_id
        return response

    app.state.services = AppServices(
        config=config,
        orchestrator=orchestrator,
        webhook_controller=webhook_controller,
        webex_gateway=webex_gateway,
        approval_manager=approval_manager,
        admin_service=admin_service,
        state_store=state_store,
        provider_registry=provider_registry,
        device_client=device_client,
        all_llm_tool_runtime=all_llm_tool_runtime,
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
                logger.exception("Startup webhook reconciliation failed; continuing startup.")
        yield

    app.router.lifespan_context = lifespan

    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(webhooks_router)
    app.include_router(debug_router)
    app.include_router(admin_router)
    app.include_router(admin_page_router)

    return app


app = build_app()
