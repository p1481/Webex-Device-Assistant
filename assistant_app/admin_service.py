from __future__ import annotations

from assistant_app.ollama_support import check_ollama_availability
from shared.contracts import (
    ActionRegistryItem,
    AdminAuthSession,
    AdminStats,
    ApprovalRequest,
    AuditEventType,
    AuditRecord,
    CommandPolicy,
    Intent,
    OrganizationDeviceRecord,
    ProviderDescriptor,
    ProviderSettings,
    RuntimeAdminSettings,
    RuntimeAdminSettingsUpdate,
    StartupConfigStatus,
)

from .state_store import InMemoryStateStore


class AdminService:
    def __init__(self, state_store: InMemoryStateStore) -> None:
        self.state_store = state_store

    def list_provider_descriptors(self) -> list[ProviderDescriptor]:
        return self.state_store.list_provider_descriptors()

    def get_provider_settings(self) -> ProviderSettings:
        return self.state_store.get_provider_settings()

    def update_provider_settings(self, settings: ProviderSettings) -> ProviderSettings:
        updated = self.state_store.update_provider_settings(settings)
        _ = self.state_store.append_audit_record(
            AuditRecord(
                event_type=AuditEventType.PROVIDER_UPDATED,
                outcome="updated",
                detail=(
                    f"Provider set to {updated.provider.value}"
                    + (f" with model {updated.model}." if updated.model is not None else ".")
                ),
            )
        )
        return updated

    def list_policies(self) -> dict[Intent, CommandPolicy]:
        return self.state_store.list_policies()

    def update_policy(self, intent: Intent, policy: CommandPolicy) -> CommandPolicy:
        updated = self.state_store.update_policy(intent, policy)
        _ = self.state_store.append_audit_record(
            AuditRecord(
                event_type=AuditEventType.POLICY_UPDATED,
                outcome="updated",
                detail=f"Policy updated for {intent.value}.",
                intent=intent,
            )
        )
        return updated

    def list_approval_requests(self) -> list[ApprovalRequest]:
        return self.state_store.list_approval_requests()

    def get_runtime_admin_settings(self) -> RuntimeAdminSettings:
        return self.state_store.get_runtime_admin_settings()

    def update_runtime_admin_settings(
        self, update: RuntimeAdminSettingsUpdate
    ) -> RuntimeAdminSettings:
        return self.state_store.update_runtime_admin_settings(update)

    def create_admin_auth_session(self, session: AdminAuthSession) -> AdminAuthSession:
        return self.state_store.create_admin_auth_session(session)

    def get_admin_auth_session(self, session_id: str) -> AdminAuthSession | None:
        return self.state_store.get_admin_auth_session(session_id)

    def update_admin_auth_session(self, session: AdminAuthSession) -> AdminAuthSession:
        return self.state_store.update_admin_auth_session(session)

    def delete_admin_auth_session(self, session_id: str) -> None:
        self.state_store.delete_admin_auth_session(session_id)

    def get_startup_config_status(self) -> StartupConfigStatus:
        return self.state_store.get_startup_config_status()

    def list_action_registry(self) -> list[ActionRegistryItem]:
        return self.state_store.list_action_registry()

    def list_organization_devices(self) -> list[OrganizationDeviceRecord]:
        return self.state_store.list_organization_devices()

    def get_stats(self) -> AdminStats:
        return self.state_store.get_stats()

    async def can_apply_provider_live(self, settings: ProviderSettings) -> tuple[bool, str | None]:
        if settings.provider.value == "rule_based":
            return True, None
        if settings.provider.value == "ollama":
            return await check_ollama_availability(settings)
        return (
            False,
            f"Provider {settings.provider.value} is not implemented for live runtime application.",
        )
