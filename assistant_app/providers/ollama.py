from __future__ import annotations

import httpx

from assistant_app.ollama_support import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
)
from assistant_app.providers import ollama_normalizers, ollama_prompts
from assistant_app.providers.ollama_normalizers import CAMERA_MODE_LAYOUT_ALIASES
from assistant_app.providers.rule_based import RuleBasedProvider
from shared.contracts import (
    ActionProposal,
    DisplayMode,
    ExecutionResult,
    InboundUserMessage,
    Intent,
    OrchestrationDecision,
    ProviderKind,
    ProviderSettings,
    SessionContext,
    WritableCameraMode,
)

OLLAMA_ASYNC_CLIENT = httpx.AsyncClient


class OllamaProvider:
    CAMERA_MODE_LAYOUT_ALIASES = CAMERA_MODE_LAYOUT_ALIASES

    def __init__(self, default_target_device: str) -> None:
        self.default_target_device = default_target_device
        self.settings = ProviderSettings(
            provider=ProviderKind.OLLAMA,
            model=DEFAULT_OLLAMA_MODEL,
            base_url=DEFAULT_OLLAMA_BASE_URL,
        )
        self._fallback_provider = RuleBasedProvider(default_target_device)

    def bind_settings(self, settings: ProviderSettings) -> None:
        self.settings = settings.model_copy(deep=True)
        if self.settings.model is None:
            self.settings.model = DEFAULT_OLLAMA_MODEL
        if self.settings.base_url is None:
            self.settings.base_url = DEFAULT_OLLAMA_BASE_URL

    async def analyze_message(
        self,
        message: InboundUserMessage,
        session: SessionContext,
    ) -> OrchestrationDecision:
        fallback = await self._fallback_provider.analyze_message(message, session)

        payload = {
            "model": self.settings.model or DEFAULT_OLLAMA_MODEL,
            "stream": False,
            "format": "json",
            "messages": self._build_messages(message, session),
        }

        try:
            async with OLLAMA_ASYNC_CLIENT(
                base_url=self.settings.base_url or DEFAULT_OLLAMA_BASE_URL,
                timeout=60.0,
            ) as client:
                response = await client.post("/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            if fallback.action_proposal is not None or fallback.pending_action is not None:
                return fallback
            return OrchestrationDecision(
                reply_text=f"Ollama provider unavailable: {exc}"
            )

        raw: object = response.json()
        if not isinstance(raw, dict):
            return OrchestrationDecision(
                reply_text="Ollama returned an unexpected response shape."
            )
        if "error" in raw:
            error_text = raw.get("error")
            return OrchestrationDecision(
                reply_text=(
                    error_text
                    if isinstance(error_text, str)
                    else "Ollama returned an error."
                )
            )

        raw_message = raw.get("message")
        if not isinstance(raw_message, dict):
            if fallback.action_proposal is not None or fallback.pending_action is not None:
                return fallback
            return OrchestrationDecision(
                reply_text="Ollama chat response was missing the assistant message."
            )
        content = raw_message.get("content")
        if not isinstance(content, str) or not content.strip():
            if fallback.action_proposal is not None or fallback.pending_action is not None:
                return fallback
            return OrchestrationDecision(
                reply_text="Ollama did not return assistant content."
            )

        decision = self._parse_decision(content, message)
        if decision is not None:
            if self._is_non_action_chat_decision(decision):
                if fallback.action_proposal is not None or fallback.pending_action is not None:
                    return fallback
            else:
                return decision

        if fallback.action_proposal is not None or fallback.pending_action is not None:
            return fallback

        if self._looks_like_device_action(message.text):
            return fallback

        if self._looks_like_structured_output(content):
            if fallback.action_proposal is not None or fallback.pending_action is not None:
                return fallback
            return OrchestrationDecision(
                reply_text=(
                    "I understood this as a device action, but the model returned an invalid action payload. "
                    "Please try again, or rephrase the request with the target and action more explicitly."
                )
            )
        return OrchestrationDecision(reply_text=content.strip())

    def _looks_like_device_action(self, text: str) -> bool:
        lowered = text.lower()
        device_action_keywords = (
            "status",
            "environment",
            "temperature",
            "humidity",
            "booking",
            "obtp",
            "device",
            "devices",
            "join",
            "dial",
            "call",
            "hang up",
            "hangup",
            "drop",
            "dtmf",
            "mute",
            "unmute",
            "microphone",
            "volume",
            "selfview",
            "self view",
            "camera",
            "layout",
            "presentation",
            "share",
            "input",
            "source",
            "matrix",
            "display",
            "preset",
            "speakertrack",
            "speaker track",
            "standby",
            "reboot",
            "factory reset",
            "상태",
            "온도",
            "습도",
            "환경",
            "예약",
            "회의",
            "장비",
            "디바이스",
            "참가",
            "전화",
            "통화",
            "종료",
            "마이크",
            "음소거",
            "소리",
            "볼륨",
            "카메라",
            "레이아웃",
            "공유",
            "발표",
            "입력",
            "소스",
            "매트릭스",
            "디스플레이",
            "프리셋",
            "스피커트랙",
            "대기",
            "재부팅",
            "공장초기화",
        )
        return any(keyword in lowered for keyword in device_action_keywords)

    def _is_non_action_chat_decision(self, decision: OrchestrationDecision) -> bool:
        proposal = decision.action_proposal
        return (
            proposal is not None
            and proposal.intent == Intent.CHAT
            and decision.pending_action is None
            and not decision.reply_text
            and proposal.summary != "Start admin login approval."
        )

    async def render_execution_reply(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
        canonical_text: str,
    ) -> str | None:
        if not self.settings.render_execution_replies:
            return None

        payload = {
            "model": self.settings.model or DEFAULT_OLLAMA_MODEL,
            "stream": False,
            "messages": self._build_render_messages(
                execution_result, policy_reason, canonical_text
            ),
        }

        try:
            async with OLLAMA_ASYNC_CLIENT(
                base_url=self.settings.base_url or DEFAULT_OLLAMA_BASE_URL,
                timeout=30.0,
            ) as client:
                response = await client.post("/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        raw: object = response.json()
        if not isinstance(raw, dict):
            return None
        raw_message = raw.get("message")
        if not isinstance(raw_message, dict):
            return None
        content = raw_message.get("content")
        if not isinstance(content, str):
            return None
        rendered = content.strip()
        return rendered or None

    def _build_messages(
        self, message: InboundUserMessage, session: SessionContext
    ) -> list[dict[str, str]]:
        return ollama_prompts.build_messages(self, message, session)

    def _build_render_messages(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
        canonical_text: str,
    ) -> list[dict[str, str]]:
        return ollama_prompts.build_render_messages(
            execution_result, policy_reason, canonical_text
        )

    def _parse_decision(
        self, content: str, message: InboundUserMessage
    ) -> OrchestrationDecision | None:
        return ollama_prompts.parse_decision(self, content, message)

    def _looks_like_structured_output(self, content: str) -> bool:
        return ollama_prompts.looks_like_structured_output(content)

    def _build_action_proposal(
        self, raw_proposal: object, message: InboundUserMessage
    ) -> ActionProposal | None:
        return ollama_prompts.build_action_proposal(self, raw_proposal, message)

    def _normalize_action_payload(
        self, raw_proposal: dict[str, object]
    ) -> dict[str, object] | None:
        return ollama_normalizers.normalize_action_payload(raw_proposal)

    def _normalize_display_mode(self, raw_mode: str) -> DisplayMode | None:
        return ollama_normalizers.normalize_display_mode(raw_mode)

    def _layout_name_as_camera_mode(self, layout_name: str) -> WritableCameraMode | None:
        return ollama_normalizers.layout_name_as_camera_mode(layout_name)

    def _normalize_target_device(
        self, raw_target_device: object, message: InboundUserMessage
    ) -> str:
        return ollama_normalizers.normalize_target_device(
            raw_target_device,
            message,
            fallback_provider=self._fallback_provider,
            default_target_device=self.default_target_device,
        )

    def _normalize_camera_mode(self, raw_mode: str) -> WritableCameraMode | None:
        return ollama_normalizers.normalize_camera_mode(raw_mode)

    def _normalize_meeting_identifier(
        self, raw_meeting_identifier: object
    ) -> str | None:
        return ollama_normalizers.normalize_meeting_identifier(raw_meeting_identifier)

    def _looks_like_internal_meeting_identifier(
        self,
        meeting_identifier: str,
        message: InboundUserMessage,
    ) -> bool:
        return ollama_normalizers.looks_like_internal_meeting_identifier(
            meeting_identifier, message
        )

    def _try_decode_webex_identifier(self, value: str) -> str | None:
        return ollama_normalizers.try_decode_webex_identifier(value)
