from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .policy import ExecutionMode
from .provider import ProviderKind

AdminFieldState = Literal["live", "read_only", "restart_required"]


def _normalize_email_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        candidate = value.strip().lower()
        if candidate and candidate not in normalized:
            normalized.append(candidate)
    return normalized


class MaskedSecret(BaseModel):
    present: bool = False
    masked_value: str | None = None
    field_state: AdminFieldState = "restart_required"


class RuntimeAdminSettings(BaseModel):
    access_token: MaskedSecret = Field(default_factory=MaskedSecret)
    bot_token: MaskedSecret = Field(default_factory=MaskedSecret)
    webhook_secret: MaskedSecret = Field(default_factory=MaskedSecret)
    webhook_url: str | None = None
    default_space_id: str | None = None
    default_space_title: str | None = None
    default_user_email: str = "youngcle@cisco.com"
    allowed_webex_user_emails: list[str] = Field(default_factory=list)
    allowed_admin_emails: list[str] = Field(default_factory=list)
    default_execution_mode: ExecutionMode = ExecutionMode.SEPARATED
    selected_provider: ProviderKind = ProviderKind.RULE_BASED
    selected_provider_model: str | None = "rule-based-default"
    selected_device_id: str | None = None
    selected_device_name: str | None = None
    webex_mock_mode: bool = True
    device_mock_mode: bool = True

    @model_validator(mode="after")
    def normalize_lists(self) -> RuntimeAdminSettings:
        self.allowed_webex_user_emails = _normalize_email_list(
            self.allowed_webex_user_emails
        )
        self.allowed_admin_emails = _normalize_email_list(self.allowed_admin_emails)
        self.default_user_email = self.default_user_email.strip().lower()
        return self


class RuntimeAdminSettingsUpdate(BaseModel):
    default_space_id: str | None = None
    default_space_title: str | None = None
    default_user_email: str | None = None
    allowed_webex_user_emails: list[str] | None = None
    allowed_admin_emails: list[str] | None = None
    default_execution_mode: ExecutionMode | None = None
    selected_provider: ProviderKind | None = None
    selected_provider_model: str | None = None
    selected_device_id: str | None = None
    selected_device_name: str | None = None

    @model_validator(mode="after")
    def normalize_lists(self) -> RuntimeAdminSettingsUpdate:
        if self.default_user_email is not None:
            self.default_user_email = self.default_user_email.strip().lower()
        if self.allowed_webex_user_emails is not None:
            self.allowed_webex_user_emails = _normalize_email_list(
                self.allowed_webex_user_emails
            )
        if self.allowed_admin_emails is not None:
            self.allowed_admin_emails = _normalize_email_list(self.allowed_admin_emails)
        return self


class AdminAuthSession(BaseModel):
    session_id: str
    email: str
    approval_request_id: str
    approved: bool = False
    consumed: bool = False
    expires_at: datetime | None = None
    approved_at: datetime | None = None


class AdminAuthRequest(BaseModel):
    email: str

    @model_validator(mode="after")
    def normalize_email(self) -> AdminAuthRequest:
        self.email = self.email.strip().lower()
        return self


class AdminAuthStartResponse(BaseModel):
    session_id: str
    status: str


class AdminAuthStatusResponse(BaseModel):
    session_id: str
    status: str
    email: str | None = None


class StartupConfigStatus(BaseModel):
    webhook_url: str | None = None
    webex_token_manager_base_url: str | None = None
    webex_bot_person_id: str | None = None
    webex_mock_mode: bool
    device_mock_mode: bool
    reconcile_on_startup: bool
    required_restart_fields: list[str] = Field(default_factory=list)


class AdminFieldDescriptor(BaseModel):
    key: str
    label: str
    field_state: AdminFieldState
    description: str


class ActionRegistryItem(BaseModel):
    intent: str
    label: str
    description: str
    supported_modes: list[ExecutionMode]
    approval_required_by_default: bool
    enabled: bool = True


class AdminStats(BaseModel):
    approvals_total: int = 0
    approvals_pending: int = 0
    approvals_approved: int = 0
    approvals_rejected: int = 0
    audit_total: int = 0
    sessions_total: int = 0
    processed_webhook_events: int = 0
    note: str = "process-local stats since start"


class OrganizationDeviceRecord(BaseModel):
    device_id: str
    display_name: str
    workspace_id: str | None = None
    product: str | None = None
    device_type: str | None = None
    permissions: list[str] | None = None
    webex_device_id: str | None = None
    place: str | None = None
    software_version: str | None = None
    serial_number: str | None = None
    online: bool | None = None
    connection_status: str | None = None
