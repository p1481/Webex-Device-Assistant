from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import (
    ActionProposal,
    Intent,
    OrchestrationDecision,
    SessionContext,
    SetDisplayModeParams,
    SetDisplayRoleParams,
    SetLayoutParams,
    SetVideoMuteParams,
)

if TYPE_CHECKING:
    from assistant_app.providers.rule_based import RuleBasedProvider


def handle_video_mute(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    """Video mute toggle dispatch."""
    _ = text
    _ = mentioned_target_device
    _ = session

    if provider._mentions_video_toggle(lowered):
        muted = provider._extract_toggle_state(
            lowered,
            enable_words={
                "video mute",
                "mute video",
                "camera off",
                "stop video",
                "turn off video",
                "비디오 꺼",
                "카메라 꺼",
                "비디오 중지",
                "카메라 중지",
            },
            disable_words={
                "video unmute",
                "unmute video",
                "camera on",
                "start video",
                "turn on video",
                "비디오 켜",
                "카메라 켜",
                "비디오 시작",
                "카메라 시작",
            },
            enable_value=True,
        )
        if muted is not None:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_VIDEO_MUTE,
                    summary="Change main video mute state.",
                    set_video_mute=SetVideoMuteParams(
                        target_device=target_device,
                        muted=muted,
                    ),
                )
            )

    return None


def handle_layout_and_display(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    """Layout, display mode, and display role dispatch."""
    _ = mentioned_target_device
    _ = session

    layout_name = provider._extract_layout_name(text)
    if layout_name is not None and (
        "layout" in lowered or layout_name == "Prominent"
    ):
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.SET_LAYOUT,
                summary="Change the video layout.",
                set_layout=SetLayoutParams(
                    target_device=target_device,
                    layout_name=layout_name,
                ),
            )
        )

    display_mode = provider._extract_display_mode(lowered)
    if (
        "display mode" in lowered
        or "monitor mode" in lowered
        or display_mode is not None
    ) and display_mode is not None:
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.SET_DISPLAY_MODE,
                summary="Change the display mode.",
                set_display_mode=SetDisplayModeParams(
                    target_device=target_device,
                    mode=display_mode,
                ),
            )
        )

    if "display role" in lowered or "monitor role" in lowered:
        connector_id = provider._extract_connector_id(text)
        display_role = provider._extract_display_role(lowered)
        if connector_id is not None and display_role is not None:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_DISPLAY_ROLE,
                    summary="Change a display connector role.",
                    set_display_role=SetDisplayRoleParams(
                        target_device=target_device,
                        connector_id=connector_id,
                        role=display_role,
                    ),
                )
            )

    return None
