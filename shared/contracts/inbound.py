from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .policy import ExecutionMode


class MessageSource(str, Enum):
    WEBEX = "webex"
    DEBUG = "debug"


class InboundUserMessage(BaseModel):
    session_id: str
    user_id: str
    text: str
    source: MessageSource = MessageSource.DEBUG
    room_id: str | None = None
    person_email: str | None = None
    event_id: str | None = None
    preferred_mode: ExecutionMode | None = None
    target_device: str | None = None


class OutboundReply(BaseModel):
    text: str
    room_id: str | None = None
    markdown: str | None = None
    skip_send: bool = False
    attachments: list[dict[str, Any]] = Field(default_factory=list)
