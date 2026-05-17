from __future__ import annotations

from shared.contracts import (
    ApprovalState,
    CommandPolicy,
    ExecutionMode,
    Intent,
    RiskLevel,
)

DEFAULT_COMMAND_POLICIES: dict[Intent, CommandPolicy] = {
    Intent.GET_STATUS: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.READ_ONLY,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason="Read-only device status can run in either mode for the MVP.",
    ),
    Intent.GET_ENVIRONMENT_INFO: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.READ_ONLY,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason="Read-only environment sensor queries can run in either mode for the MVP.",
    ),
    Intent.GET_CAMERA_MODE: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.READ_ONLY,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason="Read-only camera mode queries can run in either mode for the MVP.",
    ),
    Intent.GET_ROOM_BOOKING: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.READ_ONLY,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason="Read-only room booking and OBTP queries can run in either mode for the MVP.",
    ),
    Intent.LIST_DEVICES: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.READ_ONLY,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason="Read-only device inventory can run in either mode for the MVP.",
    ),
    Intent.WEBEX_JOIN: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Meeting joins are mutating actions and should require explicit approval.",
    ),
    Intent.JOIN_OBTP: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Scheduled meeting joins are mutating actions and should require explicit approval.",
    ),
    Intent.DIAL: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Outbound calls are mutating actions and should require explicit approval.",
    ),
    Intent.HANG_UP: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Call control changes device state and should require explicit approval.",
    ),
    Intent.SEND_DTMF: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="DTMF input should require explicit approval before it is sent.",
    ),
    Intent.SET_MICROPHONE_MUTE: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason=(
            "Mic mute is a binary toggle that is fully reversible. "
            "User intent and target value are unambiguous, so we execute immediately."
        ),
    ),
    Intent.SET_MICROPHONE_MODE: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Microphone processing changes should require explicit approval by default.",
    ),
    Intent.SET_VOLUME: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason=(
            "Volume affects only the local speaker output and is trivially reversible. "
            "Explicit numeric level from user is unambiguous, so we execute immediately."
        ),
    ),
    Intent.SET_VIDEO_MUTE: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason=(
            "Video mute is a binary on/off toggle that is fully reversible. "
            "User intent is unambiguous, so we execute immediately."
        ),
    ),
    Intent.SET_SELFVIEW: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason=(
            "Selfview is a local UI toggle (own preview only, fully reversible). "
            "When the user explicitly says on/off the intent and value are unambiguous, "
            "so we skip the approval card and execute immediately."
        ),
    ),
    Intent.SET_CAMERA_MODE: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason=(
            "Camera mode (Manual/Dynamic/BestOverview/Closeup/Frames/GroupAndSpeaker) "
            "is a reversible framing preference with no external impact."
        ),
    ),
    Intent.SET_LAYOUT: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason=(
            "Layout is a local view preference, fully reversible by selecting another. "
            "Executed immediately when the user names a layout."
        ),
    ),
    Intent.SET_PRESENTATION: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Presentation control should require explicit approval by default.",
    ),
    Intent.SWITCH_INPUT_SOURCE: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Input source changes should require explicit approval by default.",
    ),
    Intent.ASSIGN_MATRIX: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Video matrix assignments should require explicit approval by default.",
    ),
    Intent.UNASSIGN_MATRIX: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Video matrix unassignments should require explicit approval by default.",
    ),
    Intent.SWAP_MATRIX: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Video matrix swaps should require explicit approval by default.",
    ),
    Intent.SET_DISPLAY_MODE: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Display layout changes should require explicit approval by default.",
    ),
    Intent.SET_DISPLAY_ROLE: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Display role changes should require explicit approval by default.",
    ),
    Intent.ACTIVATE_CAMERA_PRESET: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Camera preset moves should require explicit approval by default.",
    ),
    Intent.ADJUST_CAMERA_POSITION: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Manual camera position changes should require explicit approval by default.",
    ),
    Intent.SET_SPEAKERTRACK: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.NOT_REQUIRED,
        reason=(
            "SpeakerTrack is a reversible camera-tracking toggle with no external impact."
        ),
    ),
    Intent.SET_STANDBY: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED, ExecutionMode.ALL_LLM],
        risk_level=RiskLevel.LOW,
        approval_state=ApprovalState.REQUIRED,
        reason="Standby changes should require explicit approval by default.",
    ),
    Intent.REBOOT: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED],
        risk_level=RiskLevel.HIGH,
        approval_state=ApprovalState.REQUIRED,
        reason="High-risk device actions stay in separated mode with approval.",
    ),
    Intent.FACTORY_RESET: CommandPolicy(
        allowed_modes=[ExecutionMode.SEPARATED],
        risk_level=RiskLevel.HIGH,
        approval_state=ApprovalState.REQUIRED,
        reason="Factory reset is destructive and must remain separated + approved.",
    ),
}
