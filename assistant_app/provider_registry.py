from __future__ import annotations

from typing import Protocol

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
)


class ChatProvider(Protocol):
    async def generate(self, request: ChatRequest) -> ChatResponse: ...


class RuleBasedChatProvider:
    def __init__(self, default_target_device: str) -> None:
        self.default_target_device = default_target_device

    async def generate(self, request: ChatRequest) -> ChatResponse:
        text = request.messages[-1].content if request.messages else ""
        return ChatResponse(text=text, raw={"provider": ProviderKind.RULE_BASED.value})


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

    def build_analysis_provider(
        self, settings: ProviderSettings
    ) -> RuleBasedProvider | OllamaProvider:
        if settings.provider == ProviderKind.RULE_BASED:
            provider = RuleBasedProvider(
                default_target_device=self.default_target_device
            )
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
