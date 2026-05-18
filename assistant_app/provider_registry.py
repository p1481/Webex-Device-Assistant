from __future__ import annotations

from typing import Protocol

import httpx

from assistant_app.ollama_support import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
)
from assistant_app.providers.ollama import OllamaProvider
from assistant_app.providers.rule_based import RuleBasedProvider
from shared.contracts import (
    ChatRequest,
    ChatResponse,
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderKind,
    ProviderSettings,
    ToolCall,
)


class ChatProvider(Protocol):
    async def generate(self, request: ChatRequest) -> ChatResponse: ...


class RuleBasedChatProvider:
    def __init__(self, default_target_device: str) -> None:
        self.default_target_device = default_target_device

    async def generate(self, request: ChatRequest) -> ChatResponse:
        text = request.messages[-1].content if request.messages else ""
        if "execute_device_action" in request.tools:
            return ChatResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        name="execute_device_action",
                        arguments="{}",
                    )
                ],
                raw={"provider": ProviderKind.RULE_BASED.value},
            )
        return ChatResponse(text=text, raw={"provider": ProviderKind.RULE_BASED.value})


class OllamaChatProvider:
    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings.model_copy(deep=True)
        if self.settings.model is None:
            self.settings.model = DEFAULT_OLLAMA_MODEL
        if self.settings.base_url is None:
            self.settings.base_url = DEFAULT_OLLAMA_BASE_URL

    async def generate(self, request: ChatRequest) -> ChatResponse:
        messages: list[dict[str, str]] = [
            {"role": message.role, "content": message.content} for message in request.messages
        ]
        if request.system is not None:
            messages = [
                {"role": "system", "content": request.system},
                *messages,
            ]
        payload: dict[str, object] = {
            "model": request.model,
            "stream": request.stream,
            "messages": messages,
        }
        if request.temperature is not None:
            payload["options"] = {"temperature": request.temperature}
        if "execute_device_action" in request.tools:
            payload["tools"] = [_execute_device_action_tool_schema()]

        async with httpx.AsyncClient(
            base_url=self.settings.base_url or DEFAULT_OLLAMA_BASE_URL,
            timeout=60.0,
        ) as client:
            response = await client.post("/chat", json=payload)
            response.raise_for_status()

        raw: object = response.json()
        if not isinstance(raw, dict):
            return ChatResponse(text="", raw={"error": "unexpected-response-shape"})
        raw_message = raw.get("message")
        if not isinstance(raw_message, dict):
            return ChatResponse(text="", raw=raw)

        content = raw_message.get("content")
        tool_calls = _parse_ollama_tool_calls(raw_message.get("tool_calls"))
        return ChatResponse(
            text=content if isinstance(content, str) else "",
            tool_calls=tool_calls,
            raw=raw,
        )


def _execute_device_action_tool_schema() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "execute_device_action",
            "description": "Execute the supplied canonical, policy-approved Webex device action request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "intent": {"type": "string"},
                    "target_device": {"type": ["string", "null"]},
                },
                "required": ["request_id", "intent"],
            },
        },
    }


def _parse_ollama_tool_calls(raw_tool_calls: object) -> list[ToolCall]:
    if not isinstance(raw_tool_calls, list):
        return []

    parsed: list[ToolCall] = []
    for raw_call in raw_tool_calls:
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str):
            continue
        if isinstance(arguments, str):
            arguments_json = arguments
        else:
            import json

            arguments_json = json.dumps(arguments if isinstance(arguments, dict) else {})
        parsed.append(ToolCall(name=name, arguments=arguments_json))
    return parsed


class ProviderRegistry:
    def __init__(self, default_target_device: str) -> None:
        self.default_target_device = default_target_device
        self._descriptors = [
            ProviderDescriptor(
                provider=ProviderKind.RULE_BASED,
                label="Rule-based MVP",
                capabilities=ProviderCapabilities(
                    supports_tools=False,
                    supports_streaming=False,
                    supports_structured_output=False,
                ),
                default_model="rule-based-default",
            ),
            ProviderDescriptor(
                provider=ProviderKind.OPENAI,
                label="OpenAI",
                capabilities=ProviderCapabilities(
                    supports_tools=True,
                    supports_streaming=True,
                    supports_structured_output=True,
                ),
            ),
            ProviderDescriptor(
                provider=ProviderKind.GEMINI,
                label="Gemini",
                capabilities=ProviderCapabilities(
                    supports_tools=True,
                    supports_streaming=True,
                    supports_structured_output=True,
                ),
            ),
            ProviderDescriptor(
                provider=ProviderKind.ANTHROPIC,
                label="Anthropic",
                capabilities=ProviderCapabilities(
                    supports_tools=True,
                    supports_streaming=True,
                    supports_structured_output=False,
                ),
            ),
            ProviderDescriptor(
                provider=ProviderKind.OLLAMA,
                label="Ollama",
                capabilities=ProviderCapabilities(
                    supports_tools=True,
                    supports_streaming=True,
                    supports_structured_output=False,
                ),
                default_model=DEFAULT_OLLAMA_MODEL,
            ),
        ]

    def descriptors(self) -> list[ProviderDescriptor]:
        return list(self._descriptors)

    def build_chat_provider(self, settings: ProviderSettings) -> ChatProvider:
        if settings.provider == ProviderKind.OLLAMA:
            return OllamaChatProvider(
                settings.model_copy(
                    update={
                        "model": settings.model or DEFAULT_OLLAMA_MODEL,
                        "base_url": settings.base_url or DEFAULT_OLLAMA_BASE_URL,
                    }
                )
            )
        return RuleBasedChatProvider(default_target_device=self.default_target_device)

    def build_analysis_provider(
        self, settings: ProviderSettings
    ) -> RuleBasedProvider | OllamaProvider:
        if settings.provider == ProviderKind.RULE_BASED:
            provider = RuleBasedProvider(default_target_device=self.default_target_device)
            provider.bind_settings(settings)
            return provider

        if settings.provider == ProviderKind.OLLAMA:
            provider = OllamaProvider(default_target_device=self.default_target_device)
            provider.bind_settings(
                settings.model_copy(
                    update={
                        "model": settings.model or DEFAULT_OLLAMA_MODEL,
                        "base_url": settings.base_url or DEFAULT_OLLAMA_BASE_URL,
                    }
                )
            )
            return provider

        raise ValueError(
            f"Provider {settings.provider.value} is not implemented for runtime analysis yet."
        )
