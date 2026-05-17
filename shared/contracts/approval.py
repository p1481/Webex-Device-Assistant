from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from .execution import ExecutionRequest


class ApprovalSubjectType(str, Enum):
    ACTION = "action"
    ADMIN_LOGIN = "admin_login"


class ApprovalChannel(str, Enum):
    WEBEX_CARD = "webex_card"
    DEBUG = "debug"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    subject_type: ApprovalSubjectType
    channel: ApprovalChannel = ApprovalChannel.WEBEX_CARD
    requested_by: str
    requested_by_email: str | None = None
    room_id: str | None = None
    title: str
    prompt: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    execution_request: ExecutionRequest | None = None
    admin_session_id: str | None = None
    correlation_id: str | None = None
    expires_at: datetime | None = None
    consumed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None


class ApprovalDecision(BaseModel):
    request_id: str
    approved: bool
    decided_by: str
    decided_by_email: str | None = None
    admin_session_id: str | None = None
    attachment_action_id: str | None = None
    correlation_id: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
