from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from .actions import Intent
from .policy import ExecutionMode


class AuditEventType(StrEnum):
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    EXECUTION_REQUESTED = "execution_requested"
    EXECUTION_COMPLETED = "execution_completed"
    ADMIN_AUTH_REQUESTED = "admin_auth_requested"
    ADMIN_AUTH_RESOLVED = "admin_auth_resolved"
    POLICY_UPDATED = "policy_updated"
    PROVIDER_UPDATED = "provider_updated"


class AuditRecord(BaseModel):
    audit_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: AuditEventType
    outcome: str
    detail: str
    session_id: str | None = None
    actor_user_id: str | None = None
    actor_email: str | None = None
    intent: Intent | None = None
    execution_mode: ExecutionMode | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
