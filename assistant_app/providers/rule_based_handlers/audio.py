from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import (
    ActionProposal,
    Intent,
    OrchestrationDecision,
    PendingActionProposal,
    SessionContext,
    SetMicrophoneModeParams,
    SetMicrophoneMuteParams,
    SetVolumeParams,
)

if TYPE_CHECKING:
    from assistant_app.providers.rule_based import RuleBasedProvider


def handle(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    """Audio dispatch: microphone toggle, microphone mode, volume."""
    _ = text
    _ = session

    if provider._mentions_microphone_toggle(lowered):
        muted = provider._extract_toggle_state(
            lowered,
            enable_words={
                "mute microphone",
                "mute mic",
                "microphone mute",
                "mic mute",
                "mute",
                "음소거",
                "뮤트",
            },
            disable_words={
                "unmute microphone",
                "unmute mic",
                "microphone unmute",
                "mic unmute",
                "unmute",
                "음소거 해제",
                "언뮤트",
            },
            enable_value=True,
        )
        if muted is not None:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_MICROPHONE_MUTE,
                    summary="Change microphone mute state.",
                    set_microphone_mute=SetMicrophoneMuteParams(
                        target_device=target_device,
                        muted=muted,
                    ),
                )
            )

    if "microphone mode" in lowered or "mic mode" in lowered:
        mode = provider._extract_microphone_mode(lowered)
        if mode is not None:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_MICROPHONE_MODE,
                    summary="Change microphone processing mode.",
                    set_microphone_mode=SetMicrophoneModeParams(
                        target_device=target_device,
                        mode=mode,
                    ),
                )
            )

    if (
        "set volume" in lowered
        or lowered.startswith("volume ")
        or "볼륨" in lowered
    ):
        level = provider._extract_volume_level(lowered)
        if level is not None:
            if mentioned_target_device is None:
                return OrchestrationDecision(
                    pending_action=PendingActionProposal(
                        intent=Intent.SET_VOLUME,
                        summary="Set device volume.",
                        level=level,
                    )
                )
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_VOLUME,
                    summary="Set device volume.",
                    set_volume=SetVolumeParams(
                        target_device=target_device, level=level
                    ),
                )
            )
        return OrchestrationDecision(
            pending_action=PendingActionProposal(
                intent=Intent.SET_VOLUME,
                summary="Set device volume.",
                target_device=mentioned_target_device,
            )
        )

    return None
