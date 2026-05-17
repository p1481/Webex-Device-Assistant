from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ProviderKind(str, Enum):
    RULE_BASED = "rule_based"
    OPENAI = "openai"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ToolCall(BaseModel):
    name: str
    arguments: str


class ProviderCapabilities(BaseModel):
    supports_tools: bool = False
    supports_streaming: bool = False
    supports_structured_output: bool = False


class ProviderSettings(BaseModel):
    provider: ProviderKind = ProviderKind.RULE_BASED
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    enabled: bool = True
    render_execution_replies: bool = False


class ProviderDescriptor(BaseModel):
    provider: ProviderKind
    label: str
    capabilities: ProviderCapabilities
    default_model: str | None = None


class ChatRequest(BaseModel):
    model: str
    system: str | None = None
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False
    tools: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    text: str
    stop_reason: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, int] | None = None
    raw: dict[str, object] | None = None
