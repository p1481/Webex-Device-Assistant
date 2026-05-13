from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import HTTPException, Request, Response

from shared.contracts import AdminAuthSession, ApprovalStatus


ADMIN_SESSION_COOKIE = "wda_admin_session"


def attach_admin_session_cookie(
    response: Response, request: Request, session_id: str
) -> None:
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        _sign_session_id(session_id, _cookie_secret(request)),
        httponly=True,
        samesite="lax",
        secure=not request.app.state.services.config.webex_mock_mode,
        path="/",
    )


def clear_admin_session_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")


def get_authenticated_admin_session(request: Request) -> AdminAuthSession:
    cookie_value = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not isinstance(cookie_value, str) or not cookie_value:
        raise HTTPException(status_code=401, detail="Admin login is required.")
    session_id = _verify_session_cookie(cookie_value, _cookie_secret(request))
    if session_id is None:
        raise HTTPException(status_code=401, detail="Admin session is invalid.")
    session = request.app.state.services.admin_service.get_admin_auth_session(
        session_id
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Admin session was not found.")
    if _is_expired(session):
        raise HTTPException(status_code=401, detail="Admin session expired.")
    approval = request.app.state.services.state_store.get_approval_request(
        session.approval_request_id
    )
    if approval is None or approval.status not in {
        ApprovalStatus.APPROVED,
        ApprovalStatus.EXECUTED,
    }:
        raise HTTPException(status_code=401, detail="Admin session is not approved.")
    if approval.requested_by_email != session.email:
        raise HTTPException(status_code=401, detail="Admin session email mismatch.")
    return session


def _cookie_secret(request: Request) -> str:
    configured = request.app.state.services.config.webex_webhook_secret
    return configured or "device-assistant-dev-admin-cookie-secret"


def _sign_session_id(session_id: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256
    )
    signature = base64.urlsafe_b64encode(digest.digest()).decode("ascii").rstrip("=")
    return f"{session_id}.{signature}"


def _verify_session_cookie(cookie_value: str, secret: str) -> str | None:
    session_id, separator, signature = cookie_value.partition(".")
    if not separator or not session_id or not signature:
        return None
    expected = _sign_session_id(session_id, secret)
    if not hmac.compare_digest(expected, cookie_value):
        return None
    return session_id


def _is_expired(session: AdminAuthSession) -> bool:
    if session.expires_at is None:
        return False
    return session.expires_at <= datetime.now(timezone.utc)
