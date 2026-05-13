from __future__ import annotations

from typing import Protocol

from shared.contracts import (
    ExecutionResult,
    InboundUserMessage,
    OrchestrationDecision,
    ProviderSettings,
    SessionContext,
)


class LLMProvider(Protocol):
    def bind_settings(self, settings: ProviderSettings) -> None: ...

    async def analyze_message(
        self,
        message: InboundUserMessage,
        session: SessionContext,
    ) -> OrchestrationDecision: ...

    async def render_execution_reply(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
        canonical_text: str,
    ) -> str | None: ...
