from __future__ import annotations

from datetime import datetime, timedelta, timezone

from shared.contracts import (
    ApprovalChannel,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalState,
    ApprovalStatus,
    ApprovalSubjectType,
    AuditEventType,
    AuditRecord,
    ExecutionRequest,
    Intent,
    InboundUserMessage,
)

from .memory_store import InMemorySessionStore
from .state_store import InMemoryStateStore


class ApprovalManager:
    def __init__(
        self,
        memory_store: InMemorySessionStore,
        state_store: InMemoryStateStore,
    ) -> None:
        self.memory_store = memory_store
        self.state_store = state_store

    def create_action_approval(
        self,
        message: InboundUserMessage,
        execution_request: ExecutionRequest,
        prompt: str,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            session_id=message.session_id,
            subject_type=ApprovalSubjectType.ACTION,
            channel=(
                ApprovalChannel.WEBEX_CARD
                if message.source.value == "webex"
                else ApprovalChannel.DEBUG
            ),
            requested_by=message.user_id,
            requested_by_email=message.person_email,
            room_id=message.room_id,
            title=f"Approve {execution_request.intent.value}",
            prompt=prompt,
            execution_request=execution_request,
        )
        stored = self.state_store.create_approval_request(request)
        session = self.memory_store.get_or_create(message.session_id)
        session.pending_approval_request_id = stored.request_id
        _ = self.state_store.append_audit_record(
            AuditRecord(
                event_type=AuditEventType.APPROVAL_REQUESTED,
                outcome=ApprovalStatus.PENDING.value,
                detail=prompt,
                session_id=message.session_id,
                actor_user_id=message.user_id,
                actor_email=message.person_email,
                intent=execution_request.intent,
                execution_mode=execution_request.execution_mode,
            )
        )
        return stored

    def create_admin_auth_request(
        self,
        message: InboundUserMessage,
        *,
        admin_session_id: str | None = None,
    ) -> ApprovalRequest:
        normalized_email = (
            message.person_email.strip().lower()
            if isinstance(message.person_email, str) and message.person_email.strip()
            else None
        )
        if normalized_email is None and message.source.value == "debug":
            runtime_email = (
                self.state_store.get_runtime_admin_settings()
                .default_user_email.strip()
                .lower()
            )
            normalized_email = runtime_email or None
        if normalized_email is None:
            raise RuntimeError("Admin login requires a requester email.")
        request = ApprovalRequest(
            session_id=message.session_id,
            subject_type=ApprovalSubjectType.ADMIN_LOGIN,
            channel=(
                ApprovalChannel.WEBEX_CARD
                if message.source.value == "webex"
                else ApprovalChannel.DEBUG
            ),
            requested_by=message.user_id,
            requested_by_email=normalized_email,
            room_id=message.room_id,
            title="Approve admin login",
            prompt="Approve this admin login request to unlock administrative actions.",
            admin_session_id=admin_session_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        stored = self.state_store.create_approval_request(request)
        session = self.memory_store.get_or_create(message.session_id)
        session.pending_admin_auth_request_id = stored.request_id
        _ = self.state_store.append_audit_record(
            AuditRecord(
                event_type=AuditEventType.ADMIN_AUTH_REQUESTED,
                outcome=ApprovalStatus.PENDING.value,
                detail=stored.prompt,
                session_id=message.session_id,
                actor_user_id=message.user_id,
                actor_email=message.person_email,
            )
        )
        return stored

    def approve_or_reject(self, decision: ApprovalDecision) -> ApprovalRequest | None:
        request = self.state_store.resolve_approval_request(decision)
        if request is None:
            return None
        if (
            request.subject_type == ApprovalSubjectType.ADMIN_LOGIN
            and decision.approved
            and not self._admin_login_identity_matches(request, decision)
        ):
            request.status = ApprovalStatus.REJECTED
            request.resolved_at = decision.decided_at
            _ = self.state_store.create_approval_request(request)
            _ = self.state_store.append_audit_record(
                AuditRecord(
                    event_type=AuditEventType.ADMIN_AUTH_RESOLVED,
                    outcome=ApprovalState.REJECTED.value,
                    detail="Admin login approval rejected because the approving identity did not match the requested email.",
                    session_id=request.session_id,
                    actor_user_id=decision.decided_by,
                    actor_email=decision.decided_by_email,
                    intent=Intent.CHAT,
                )
            )
            session = self.memory_store.get_or_create(request.session_id)
            session.pending_admin_auth_request_id = None
            return request
        session = self.memory_store.get_or_create(request.session_id)
        if request.subject_type == ApprovalSubjectType.ACTION:
            session.pending_approval_request_id = None
        else:
            session.pending_admin_auth_request_id = None
            if decision.approved:
                session.admin_authenticated = True
                session.admin_session_id = request.request_id

        _ = self.state_store.append_audit_record(
            AuditRecord(
                event_type=(
                    AuditEventType.APPROVAL_RESOLVED
                    if request.subject_type == ApprovalSubjectType.ACTION
                    else AuditEventType.ADMIN_AUTH_RESOLVED
                ),
                outcome=(
                    ApprovalState.APPROVED.value
                    if decision.approved
                    else ApprovalState.REJECTED.value
                ),
                detail=request.prompt,
                session_id=request.session_id,
                actor_user_id=decision.decided_by,
                actor_email=decision.decided_by_email,
                intent=request.execution_request.intent
                if request.execution_request is not None
                else Intent.CHAT,
                execution_mode=request.execution_request.execution_mode
                if request.execution_request is not None
                else None,
            )
        )
        return request

    def _admin_login_identity_matches(
        self, request: ApprovalRequest, decision: ApprovalDecision
    ) -> bool:
        requested_email = (
            request.requested_by_email.strip().lower()
            if isinstance(request.requested_by_email, str)
            and request.requested_by_email.strip()
            else None
        )
        decided_email = (
            decision.decided_by_email.strip().lower()
            if isinstance(decision.decided_by_email, str)
            and decision.decided_by_email.strip()
            else None
        )
        if requested_email is None or decided_email is None:
            return False
        if decided_email != requested_email:
            return False
        if request.admin_session_id is None:
            return True
        return decision.admin_session_id == request.admin_session_id

    def find_pending_by_request_id(self, request_id: str) -> ApprovalRequest | None:
        return self.state_store.get_approval_request(request_id)
