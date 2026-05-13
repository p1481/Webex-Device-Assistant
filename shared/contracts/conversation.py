from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from .actions import Intent


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    text: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionContext(BaseModel):
    session_id: str
    turns: list[ConversationTurn] = Field(default_factory=list)
    last_intent: Intent | None = None
    pending_approval_request_id: str | None = None
    pending_admin_auth_request_id: str | None = None
    admin_authenticated: bool = False
    admin_session_id: str | None = None
