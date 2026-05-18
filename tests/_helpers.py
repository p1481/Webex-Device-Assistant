"""Shared test helpers for the Device Assistant test suite.

Extracted from the monolithic ``tests/test_app.py`` to enable domain-based
test file splits without duplicating fixture wiring.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from os import environ
from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from assistant_app.admin_auth import ADMIN_SESSION_COOKIE, _sign_session_id
from assistant_app.main import build_app
from shared.contracts import (
    AdminAuthSession,
    ApprovalDecision,
    InboundUserMessage,
    MessageSource,
)


def build_authenticated_client(app_instance: FastAPI | None = None) -> TestClient:
    scoped_app = app_instance or build_app()
    scoped_client = TestClient(scoped_app)
    session_id = f"test-admin-session-{uuid4()}"
    email = scoped_app.state.services.admin_service.get_runtime_admin_settings().default_user_email
    auth_session = scoped_app.state.services.admin_service.create_admin_auth_session(
        AdminAuthSession(
            session_id=session_id,
            email=email,
            approval_request_id="",
            approved=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            approved_at=datetime.now(UTC),
        )
    )
    approval_request = scoped_app.state.services.approval_manager.create_admin_auth_request(
        InboundUserMessage(
            session_id=f"admin-auth:{session_id}",
            user_id=email,
            person_email=email,
            text="admin login",
            source=MessageSource.WEBEX,
            room_id=None,
        ),
        admin_session_id=session_id,
    )
    auth_session.approval_request_id = approval_request.request_id
    _ = scoped_app.state.services.admin_service.update_admin_auth_session(auth_session)
    resolved = scoped_app.state.services.approval_manager.approve_or_reject(
        ApprovalDecision(
            request_id=approval_request.request_id,
            approved=True,
            decided_by="person-1",
            decided_by_email=email,
            admin_session_id=session_id,
        )
    )
    assert resolved is not None
    cookie_secret = (
        getattr(scoped_app.state.services.config, "admin_cookie_secret", None)
        or scoped_app.state.services.config.webex_webhook_secret
        or "device-assistant-dev-admin-cookie-secret"
    )
    scoped_client.cookies.set(
        ADMIN_SESSION_COOKIE,
        _sign_session_id(session_id, cookie_secret),
    )
    return scoped_client


def build_unauthenticated_client(app_instance: FastAPI | None = None) -> TestClient:
    scoped_app = app_instance or build_app()
    return TestClient(scoped_app)


@contextmanager
def temporary_env(updates: dict[str, str | None]) -> Iterator[None]:
    original = {key: environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                _ = environ.pop(key, None)
            else:
                environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                _ = environ.pop(key, None)
            else:
                environ[key] = value


def as_mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def as_sequence(value: object) -> Sequence[object]:
    assert isinstance(value, list)
    return cast(list[object], value)
