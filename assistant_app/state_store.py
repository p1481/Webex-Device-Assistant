from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from pydantic import BaseModel, Field

from assistant_app.ollama_support import DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_MODEL
from shared.contracts import (
    ActionRegistryItem,
    AdminAuthSession,
    AdminStats,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    AuditRecord,
    CommandPolicy,
    Intent,
    OrganizationDeviceRecord,
    ProviderDescriptor,
    ProviderKind,
    ProviderSettings,
    RuntimeAdminSettings,
    RuntimeAdminSettingsUpdate,
    SessionContext,
    StartupConfigStatus,
)
from shared.policy_defaults import DEFAULT_COMMAND_POLICIES


class PersistedProviderSettings(BaseModel):
    provider: ProviderKind = ProviderKind.OLLAMA
    model: str | None = DEFAULT_OLLAMA_MODEL
    base_url: str | None = DEFAULT_OLLAMA_BASE_URL
    temperature: float | None = None
    max_tokens: int | None = None
    enabled: bool = True
    render_execution_replies: bool = False


class PersistedControlPlaneState(BaseModel):
    schema_version: int = 1
    runtime_admin_overrides: RuntimeAdminSettingsUpdate = Field(
        default_factory=RuntimeAdminSettingsUpdate
    )
    provider_settings: PersistedProviderSettings | None = None
    policies: dict[str, CommandPolicy] = Field(default_factory=dict)
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    audit: list[AuditRecord] = Field(default_factory=list)
    admin_auth_sessions: list[AdminAuthSession] = Field(default_factory=list)
    processed_webhook_event_ids: list[str] = Field(default_factory=list)


class InMemoryStateStore:
    def __init__(self) -> None:
        self._approval_requests: dict[str, ApprovalRequest] = {}
        self._audit_records: list[AuditRecord] = []
        self._policy_settings: dict[Intent, CommandPolicy] = dict(DEFAULT_COMMAND_POLICIES)
        self._provider_settings = ProviderSettings(
            provider=ProviderKind.OLLAMA,
            model=DEFAULT_OLLAMA_MODEL,
            base_url=DEFAULT_OLLAMA_BASE_URL,
        )
        self._provider_descriptors: list[ProviderDescriptor] = []
        self._runtime_admin_settings = RuntimeAdminSettings()
        self._startup_config_status = StartupConfigStatus(
            webhook_url=None,
            webex_bot_person_id=None,
            webex_mock_mode=True,
            device_mock_mode=True,
            reconcile_on_startup=False,
        )
        self._action_registry: dict[str, ActionRegistryItem] = {}
        self._organization_devices: list[OrganizationDeviceRecord] = []
        self._processed_webhook_events: set[str] = set()
        self._session_count = 0
        self._admin_auth_sessions: dict[str, AdminAuthSession] = {}
        self._provider_settings_persisted: bool = False

    def is_provider_settings_persisted(self) -> bool:
        return self._provider_settings_persisted

    def set_runtime_admin_settings(self, settings: RuntimeAdminSettings) -> RuntimeAdminSettings:
        self._runtime_admin_settings = settings.model_copy(deep=True)
        return self.get_runtime_admin_settings()

    def get_runtime_admin_settings(self) -> RuntimeAdminSettings:
        return self._runtime_admin_settings.model_copy(deep=True)

    def update_runtime_admin_settings(
        self, update: RuntimeAdminSettingsUpdate
    ) -> RuntimeAdminSettings:
        current = self._runtime_admin_settings.model_copy(deep=True)
        changes = update.model_dump(exclude_none=True)
        for key, value in changes.items():
            setattr(current, key, value)
        self._runtime_admin_settings = current
        return self.get_runtime_admin_settings()

    def set_startup_config_status(self, status: StartupConfigStatus) -> StartupConfigStatus:
        self._startup_config_status = status.model_copy(deep=True)
        return self.get_startup_config_status()

    def get_startup_config_status(self) -> StartupConfigStatus:
        return self._startup_config_status.model_copy(deep=True)

    def set_action_registry(self, items: list[ActionRegistryItem]) -> None:
        self._action_registry = {item.intent: item.model_copy(deep=True) for item in items}

    def list_action_registry(self) -> list[ActionRegistryItem]:
        return [item.model_copy(deep=True) for item in self._action_registry.values()]

    def set_organization_devices(
        self, devices: list[OrganizationDeviceRecord]
    ) -> list[OrganizationDeviceRecord]:
        self._organization_devices = [device.model_copy(deep=True) for device in devices]
        return self.list_organization_devices()

    def list_organization_devices(self) -> list[OrganizationDeviceRecord]:
        return [device.model_copy(deep=True) for device in self._organization_devices]

    def has_processed_webhook_event(self, event_id: str) -> bool:
        return event_id in self._processed_webhook_events

    def mark_processed_webhook_event(self, event_id: str) -> None:
        self._processed_webhook_events.add(event_id)

    def mark_session_seen(self) -> None:
        self._session_count += 1

    def get_stats(self) -> AdminStats:
        approvals = list(self._approval_requests.values())
        return AdminStats(
            approvals_total=len(approvals),
            approvals_pending=sum(
                1 for approval in approvals if approval.status == ApprovalStatus.PENDING
            ),
            approvals_approved=sum(
                1 for approval in approvals if approval.status == ApprovalStatus.APPROVED
            ),
            approvals_rejected=sum(
                1 for approval in approvals if approval.status == ApprovalStatus.REJECTED
            ),
            audit_total=len(self._audit_records),
            sessions_total=self._session_count,
            processed_webhook_events=len(self._processed_webhook_events),
        )

    def register_provider_descriptors(self, descriptors: list[ProviderDescriptor]) -> None:
        self._provider_descriptors = descriptors

    def list_provider_descriptors(self) -> list[ProviderDescriptor]:
        return list(self._provider_descriptors)

    def get_provider_settings(self) -> ProviderSettings:
        return self._provider_settings.model_copy(deep=True)

    def update_provider_settings(self, settings: ProviderSettings) -> ProviderSettings:
        self._provider_settings = settings.model_copy(deep=True)
        return self.get_provider_settings()

    def get_policy(self, intent: Intent) -> CommandPolicy | None:
        policy = self._policy_settings.get(intent)
        return policy.model_copy(deep=True) if policy else None

    def list_policies(self) -> dict[Intent, CommandPolicy]:
        return {
            intent: policy.model_copy(deep=True) for intent, policy in self._policy_settings.items()
        }

    def update_policy(self, intent: Intent, policy: CommandPolicy) -> CommandPolicy:
        self._policy_settings[intent] = policy.model_copy(deep=True)
        return self._policy_settings[intent].model_copy(deep=True)

    def create_approval_request(self, request: ApprovalRequest) -> ApprovalRequest:
        stored = request.model_copy(deep=True)
        self._approval_requests[stored.request_id] = stored
        return stored.model_copy(deep=True)

    def get_approval_request(self, request_id: str) -> ApprovalRequest | None:
        request = self._approval_requests.get(request_id)
        return request.model_copy(deep=True) if request else None

    def list_approval_requests(self) -> list[ApprovalRequest]:
        return [request.model_copy(deep=True) for request in self._approval_requests.values()]

    def resolve_approval_request(self, decision: ApprovalDecision) -> ApprovalRequest | None:
        request = self._approval_requests.get(decision.request_id)
        if request is None:
            return None
        if request.status != ApprovalStatus.PENDING:
            return None

        request.status = ApprovalStatus.APPROVED if decision.approved else ApprovalStatus.REJECTED
        request.resolved_at = decision.decided_at
        self._approval_requests[decision.request_id] = request
        return request.model_copy(deep=True)

    def mark_approval_executed(self, request_id: str) -> ApprovalRequest | None:
        request = self._approval_requests.get(request_id)
        if request is None:
            return None

        request.status = ApprovalStatus.EXECUTED
        request.resolved_at = datetime.now(UTC)
        self._approval_requests[request_id] = request
        return request.model_copy(deep=True)

    def append_audit_record(self, record: AuditRecord) -> AuditRecord:
        stored = record.model_copy(deep=True)
        self._audit_records.append(stored)
        return stored.model_copy(deep=True)

    def create_admin_auth_session(self, session: AdminAuthSession) -> AdminAuthSession:
        stored = session.model_copy(deep=True)
        self._admin_auth_sessions[stored.session_id] = stored
        return stored.model_copy(deep=True)

    def get_admin_auth_session(self, session_id: str) -> AdminAuthSession | None:
        session = self._admin_auth_sessions.get(session_id)
        return session.model_copy(deep=True) if session is not None else None

    def update_admin_auth_session(self, session: AdminAuthSession) -> AdminAuthSession:
        stored = session.model_copy(deep=True)
        self._admin_auth_sessions[stored.session_id] = stored
        return stored.model_copy(deep=True)

    def delete_admin_auth_session(self, session_id: str) -> None:
        _ = self._admin_auth_sessions.pop(session_id, None)

    def list_audit_records(self) -> list[AuditRecord]:
        return [record.model_copy(deep=True) for record in self._audit_records]

    def clear_session_bindings(self, session: SessionContext) -> None:
        session.pending_approval_request_id = None
        session.pending_admin_auth_request_id = None
        session.admin_authenticated = False
        session.admin_session_id = None


class FileBackedStateStore(InMemoryStateStore):
    def __init__(self, file_path: str | Path) -> None:
        super().__init__()
        self._state_path = Path(file_path)
        self._persist_lock = RLock()
        self._runtime_admin_overrides = RuntimeAdminSettingsUpdate()
        self._load_persisted_state()

    def set_runtime_admin_settings(self, settings: RuntimeAdminSettings) -> RuntimeAdminSettings:
        runtime_settings = settings.model_copy(deep=True)
        changes = self._runtime_admin_overrides.model_dump(exclude_none=True)
        for key, value in changes.items():
            setattr(runtime_settings, key, value)
        self._runtime_admin_settings = runtime_settings
        return self.get_runtime_admin_settings()

    def update_runtime_admin_settings(
        self, update: RuntimeAdminSettingsUpdate
    ) -> RuntimeAdminSettings:
        updated = super().update_runtime_admin_settings(update)
        override_changes = update.model_dump(exclude_none=True)
        current_overrides = self._runtime_admin_overrides.model_copy(deep=True)
        for key, value in override_changes.items():
            setattr(current_overrides, key, value)
        self._runtime_admin_overrides = current_overrides
        self._persist_state()
        return updated

    def update_provider_settings(self, settings: ProviderSettings) -> ProviderSettings:
        updated = super().update_provider_settings(settings)
        self._provider_settings_persisted = True
        self._persist_state()
        return updated

    def update_policy(self, intent: Intent, policy: CommandPolicy) -> CommandPolicy:
        updated = super().update_policy(intent, policy)
        self._persist_state()
        return updated

    def create_approval_request(self, request: ApprovalRequest) -> ApprovalRequest:
        created = super().create_approval_request(request)
        self._persist_state()
        return created

    def create_admin_auth_session(self, session: AdminAuthSession) -> AdminAuthSession:
        created = super().create_admin_auth_session(session)
        self._persist_state()
        return created

    def update_admin_auth_session(self, session: AdminAuthSession) -> AdminAuthSession:
        updated = super().update_admin_auth_session(session)
        self._persist_state()
        return updated

    def delete_admin_auth_session(self, session_id: str) -> None:
        super().delete_admin_auth_session(session_id)
        self._persist_state()

    def resolve_approval_request(self, decision: ApprovalDecision) -> ApprovalRequest | None:
        resolved = super().resolve_approval_request(decision)
        if resolved is not None:
            self._persist_state()
        return resolved

    def mark_approval_executed(self, request_id: str) -> ApprovalRequest | None:
        updated = super().mark_approval_executed(request_id)
        if updated is not None:
            self._persist_state()
        return updated

    def append_audit_record(self, record: AuditRecord) -> AuditRecord:
        appended = super().append_audit_record(record)
        self._persist_state()
        return appended

    def mark_processed_webhook_event(self, event_id: str) -> None:
        super().mark_processed_webhook_event(event_id)
        self._persist_state()

    def _load_persisted_state(self) -> None:
        if not self._state_path.exists():
            return

        document = PersistedControlPlaneState.model_validate_json(
            self._state_path.read_text(encoding="utf-8")
        )
        if document.schema_version != 1:
            raise ValueError(
                f"Unsupported persisted state schema version: {document.schema_version}."
            )

        self._runtime_admin_overrides = document.runtime_admin_overrides.model_copy(deep=True)
        if document.provider_settings is not None:
            self._provider_settings_persisted = True
            self._provider_settings = ProviderSettings(
                provider=document.provider_settings.provider,
                model=document.provider_settings.model,
                base_url=document.provider_settings.base_url,
                api_key=None,
                temperature=document.provider_settings.temperature,
                max_tokens=document.provider_settings.max_tokens,
                enabled=document.provider_settings.enabled,
                render_execution_replies=document.provider_settings.render_execution_replies,
            )

        self._policy_settings = dict(DEFAULT_COMMAND_POLICIES)
        for intent_name, policy in document.policies.items():
            self._policy_settings[Intent(intent_name)] = policy.model_copy(deep=True)

        self._approval_requests = {
            request.request_id: request.model_copy(deep=True) for request in document.approvals
        }
        self._audit_records = [record.model_copy(deep=True) for record in document.audit]
        self._admin_auth_sessions = {
            session.session_id: session.model_copy(deep=True)
            for session in document.admin_auth_sessions
        }
        self._processed_webhook_events = set(document.processed_webhook_event_ids)

    def _persist_state(self) -> None:
        persisted_policies = {
            intent.value: policy.model_copy(deep=True)
            for intent, policy in self._policy_settings.items()
            if policy.model_dump(mode="json")
            != DEFAULT_COMMAND_POLICIES[intent].model_dump(mode="json")
        }
        document = PersistedControlPlaneState(
            runtime_admin_overrides=self._runtime_admin_overrides.model_copy(deep=True),
            provider_settings=PersistedProviderSettings(
                provider=self._provider_settings.provider,
                model=self._provider_settings.model,
                base_url=self._provider_settings.base_url,
                temperature=self._provider_settings.temperature,
                max_tokens=self._provider_settings.max_tokens,
                enabled=self._provider_settings.enabled,
                render_execution_replies=self._provider_settings.render_execution_replies,
            ),
            policies=persisted_policies,
            approvals=self.list_approval_requests(),
            audit=self.list_audit_records(),
            admin_auth_sessions=[
                session.model_copy(deep=True) for session in self._admin_auth_sessions.values()
            ],
            processed_webhook_event_ids=sorted(self._processed_webhook_events),
        )

        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            document.model_dump(mode="json", exclude_none=True),
            indent=2,
            sort_keys=True,
        )
        with self._persist_lock:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._state_path.parent,
                prefix=f"{self._state_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(payload)
                temp_path = Path(temp_file.name)
            temp_path.replace(self._state_path)


def build_state_store(state_path: str | None) -> InMemoryStateStore:
    if state_path is None:
        return InMemoryStateStore()
    return FileBackedStateStore(state_path)
