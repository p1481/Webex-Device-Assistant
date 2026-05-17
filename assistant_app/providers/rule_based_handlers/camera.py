from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import (
    ActionProposal,
    ActivateCameraPresetParams,
    AdjustCameraPositionParams,
    GetCameraModeParams,
    Intent,
    OrchestrationDecision,
    PendingActionProposal,
    SessionContext,
    SetCameraModeParams,
    SetSelfviewParams,
)

if TYPE_CHECKING:
    from assistant_app.providers.rule_based import RuleBasedProvider


def handle_get_mode(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    """Camera GET_CAMERA_MODE dispatch (fires just after `status`)."""
    _ = text
    _ = mentioned_target_device
    _ = session

    if provider._is_get_camera_mode_request(lowered):
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.GET_CAMERA_MODE,
                summary="Get the current camera mode.",
                get_camera_mode=GetCameraModeParams(target_device=target_device),
            )
        )

    return None


def handle_set_mode_and_selfview(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    message_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    """Camera SET_CAMERA_MODE + SET_SELFVIEW dispatch (fires after video-toggle)."""
    _ = text
    _ = session

    if provider._is_set_camera_mode_request(lowered):
        writable_camera_mode = provider._extract_camera_mode(lowered)
        if writable_camera_mode is not None:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_CAMERA_MODE,
                    summary="Change the camera mode.",
                    set_camera_mode=SetCameraModeParams(
                        target_device=target_device,
                        mode=writable_camera_mode,
                    ),
                )
            )
        return OrchestrationDecision(
            reply_text=(
                "I currently support these camera modes based on the RoomOS "
                "Cameras SpeakerTrack Set command Behavior values: Manual, "
                "Dynamic, BestOverview, Closeup, Frames, and GroupAndSpeaker."
            )
        )

    if (
        "selfview" in lowered
        or "self view" in lowered
        or "셀프뷰" in lowered
        or "내 모습" in lowered
        or "내모습" in lowered
    ):
        enabled = provider._extract_toggle_state(
            lowered,
            enable_words={
                "selfview on",
                "enable selfview",
                "show selfview",
                "turn on selfview",
                "셀프뷰 켜",
                "셀프뷰 보여",
                "셀프뷰 시작",
                "내 모습 보여",
                "내 모습 보이",
                "내 모습 나오",
                "내모습 보여",
                "내모습 보이",
                "내모습 나오",
            },
            disable_words={
                "selfview off",
                "disable selfview",
                "hide selfview",
                "turn off selfview",
                "셀프뷰 꺼",
                "셀프뷰 숨겨",
                "셀프뷰 중지",
                "내 모습 숨겨",
                "내 모습 안 보이",
                "내모습 숨겨",
                "내모습 안 보이",
            },
        )
        if enabled is not None:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SET_SELFVIEW,
                    summary="Change selfview state.",
                    set_selfview=SetSelfviewParams(
                        target_device=target_device,
                        enabled=enabled,
                    ),
                )
            )
        return OrchestrationDecision(
            pending_action=PendingActionProposal(
                intent=Intent.SET_SELFVIEW,
                summary="Change selfview state.",
                target_device=mentioned_target_device or message_target_device,
            )
        )

    return None


def handle_position_and_preset(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    """Camera ADJUST_CAMERA_POSITION + ACTIVATE_CAMERA_PRESET dispatch (fires near tail)."""
    _ = session

    camera_position = provider._extract_camera_position(text)
    if camera_position is not None:
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.ADJUST_CAMERA_POSITION,
                summary="Adjust a specific camera position.",
                adjust_camera_position=AdjustCameraPositionParams(
                    target_device=target_device if mentioned_target_device else "",
                    camera_id=camera_position["camera_id"],
                    pan=camera_position["pan"],
                    tilt=camera_position["tilt"],
                    zoom=camera_position["zoom"],
                ),
            )
        )

    if "camera preset" in lowered or "preset" in lowered:
        preset_id = provider._extract_preset_id(text)
        if preset_id is not None:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.ACTIVATE_CAMERA_PRESET,
                    summary="Activate a camera preset.",
                    activate_camera_preset=ActivateCameraPresetParams(
                        target_device=target_device,
                        preset_id=preset_id,
                    ),
                )
            )

    return None
