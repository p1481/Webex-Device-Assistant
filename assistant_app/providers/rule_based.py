from __future__ import annotations

import re
from typing import TypedDict

from shared.contracts import (
    ActionProposal,
    ActivateCameraPresetParams,
    AdjustCameraPositionParams,
    AssignMatrixParams,
    DialParams,
    DisplayMode,
    DisplayRole,
    ExecutionResult,
    FactoryResetParams,
    GetCameraModeParams,
    GetEnvironmentInfoParams,
    GetRoomBookingParams,
    GetStatusParams,
    HangUpParams,
    InboundUserMessage,
    Intent,
    JoinObtpParams,
    ListDevicesParams,
    MicrophoneProcessingMode,
    OrchestrationDecision,
    PendingActionProposal,
    ProviderSettings,
    RebootParams,
    SendDtmfParams,
    SessionContext,
    SetCameraModeParams,
    SetDisplayModeParams,
    SetDisplayRoleParams,
    SetLayoutParams,
    SetMicrophoneModeParams,
    SetMicrophoneMuteParams,
    SetPresentationParams,
    SetSelfviewParams,
    SetSpeakerTrackParams,
    SetStandbyParams,
    SetVideoMuteParams,
    SetVolumeParams,
    SwapMatrixParams,
    SwitchInputSourceParams,
    UnassignMatrixParams,
    WebexJoinParams,
    WritableCameraMode,
)


class MatrixAssignMatch(TypedDict):
    output: str
    mode: str
    layout: str
    source_id: str | None
    remote_main: bool | None


class MatrixUnassignMatch(TypedDict):
    output: str
    source_id: str | None
    remote_main: bool | None


class MatrixSwapMatch(TypedDict):
    output_a: str
    output_b: str


class CameraPositionMatch(TypedDict):
    camera_id: str
    pan: int | None
    tilt: int | None
    zoom: int | None


class RuleBasedProvider:
    SOURCE_ALIAS_PATTERN: re.Pattern[str] = re.compile(
        r"(?:switch\s+)?(?:input\s+source|source\s+input)\s+(?:to\s+)?([A-Za-z0-9_-]+)",
        re.IGNORECASE,
    )
    PROMINENT_LAYOUT_PHRASES: tuple[str, ...] = (
        "layout prominent",
        "prominent layout",
        "make layout prominent",
        "set layout prominent",
        "set layout to prominent",
        "switch layout to prominent",
    )
    TOGGLE_ACTION_NAMES: frozenset[str] = frozenset(
        {
            "selfview",
            "self view",
            "speakertrack",
            "speaker track",
            "standby",
            "presentation",
            "share",
            "video",
            "camera",
        }
    )
    CAMERA_PAN_STEP: int = 1000
    CAMERA_TILT_STEP: int = 1000
    CAMERA_ZOOM_STEP: int = 700

    def __init__(self, default_target_device: str) -> None:
        self.default_target_device: str = default_target_device
        self.settings: ProviderSettings = ProviderSettings()

    def bind_settings(self, settings: ProviderSettings) -> None:
        self.settings = settings

    async def render_execution_reply(
        self,
        execution_result: ExecutionResult,
        policy_reason: str,
        canonical_text: str,
    ) -> str | None:
        _ = execution_result
        _ = policy_reason
        _ = canonical_text
        return None

    async def analyze_message(
        self,
        message: InboundUserMessage,
        session: SessionContext,
    ) -> OrchestrationDecision:
        text = message.text.strip()
        lowered = text.lower()

        if lowered in {"/reset", "/clear-context", "reset context", "clear context"}:
            return OrchestrationDecision(
                reply_text="I cleared the session context. Ask for a device status whenever you're ready.",
                action_proposal=ActionProposal(
                    intent=Intent.RESET_CONTEXT, summary="Reset conversation context."
                ),
            )

        if lowered in {"admin login", "admin auth", "/admin-login"}:
            return OrchestrationDecision(
                reply_text="I started an admin login approval request.",
                action_proposal=ActionProposal(
                    intent=Intent.CHAT,
                    summary="Start admin login approval.",
                ),
            )

        target_device = self._extract_target_device(text, message.target_device)
        mentioned_target_device = self._extract_mentioned_target_device(
            text, message.target_device
        )

        if self._is_list_devices_request(lowered):
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.LIST_DEVICES,
                    summary="List devices in the Webex organization.",
                    list_devices=ListDevicesParams(
                        limit=10,
                        online_only=("online" in lowered or "온라인" in lowered),
                    ),
                )
            )

        if self._is_get_environment_info_request(lowered):
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_ENVIRONMENT_INFO,
                    summary="Get the current environment sensor information.",
                    get_environment_info=GetEnvironmentInfoParams(
                        target_device=target_device
                    ),
                )
            )

        if self._is_get_room_booking_request(lowered):
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_ROOM_BOOKING,
                    summary="Get the current room booking and OBTP status.",
                    get_room_booking=GetRoomBookingParams(target_device=target_device),
                )
            )

        if "status" in lowered:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_STATUS,
                    summary="Get the current device status.",
                    get_status=GetStatusParams(target_device=target_device),
                )
            )

        if self._is_get_camera_mode_request(lowered):
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.GET_CAMERA_MODE,
                    summary="Get the current camera mode.",
                    get_camera_mode=GetCameraModeParams(target_device=target_device),
                )
            )

        if self._is_join_obtp_request(lowered):
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.JOIN_OBTP,
                    summary="Join the next joinable scheduled meeting from the target device.",
                    join_obtp=JoinObtpParams(target_device=target_device),
                )
            )

        if self._is_webex_join_request(lowered):
            meeting_identifier = self._extract_webex_meeting_identifier(text)
            if meeting_identifier is not None:
                action_target_device = mentioned_target_device or message.target_device
                if action_target_device is None:
                    return OrchestrationDecision(
                        pending_action=PendingActionProposal(
                            intent=Intent.WEBEX_JOIN,
                            summary="Join a Webex meeting from the target device.",
                            meeting_identifier=meeting_identifier,
                        )
                    )
                return OrchestrationDecision(
                    action_proposal=ActionProposal(
                        intent=Intent.WEBEX_JOIN,
                        summary="Join a Webex meeting from the target device.",
                        webex_join=WebexJoinParams(
                            target_device=action_target_device,
                            meeting_identifier=meeting_identifier,
                        ),
                    )
                )
            return OrchestrationDecision(
                pending_action=PendingActionProposal(
                    intent=Intent.WEBEX_JOIN,
                    summary="Join a Webex meeting from the target device.",
                    target_device=mentioned_target_device,
                )
            )

        if any(
            phrase in lowered
            for phrase in {"dial ", "sip ", "call ", "join sip", "전화", "통화"}
        ):
            address = self._extract_dial_address(text)
            if address is not None:
                if mentioned_target_device is None:
                    return OrchestrationDecision(
                        pending_action=PendingActionProposal(
                            intent=Intent.DIAL,
                            summary="Dial from the target device.",
                            address=address,
                        )
                    )
                return OrchestrationDecision(
                    action_proposal=ActionProposal(
                        intent=Intent.DIAL,
                        summary="Dial from the target device.",
                        dial=DialParams(target_device=target_device, address=address),
                    )
                )
            return OrchestrationDecision(
                pending_action=PendingActionProposal(
                    intent=Intent.DIAL,
                    summary="Dial from the target device.",
                    target_device=mentioned_target_device,
                )
            )

        if any(
            phrase in lowered
            for phrase in {
                "hang up",
                "hangup",
                "disconnect call",
                "drop call",
                "drop meeting",
            }
        ) or lowered.strip().endswith(" drop"):
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.HANG_UP,
                    summary="Disconnect the current device call.",
                    hang_up=HangUpParams(
                        target_device=target_device,
                        call_id=self._extract_call_id(text),
                    ),
                )
            )

        if "dtmf" in lowered or "send tone" in lowered or "send digits" in lowered:
            tones = self._extract_dtmf_tones(text)
            if tones is not None:
                return OrchestrationDecision(
                    action_proposal=ActionProposal(
                        intent=Intent.SEND_DTMF,
                        summary="Send DTMF tones on the current call.",
                        send_dtmf=SendDtmfParams(
                            target_device=target_device,
                            tones=tones,
                            call_id=self._extract_call_id(text),
                        ),
                    )
                )

        if self._mentions_microphone_toggle(lowered):
            muted = self._extract_toggle_state(
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
            mode = self._extract_microphone_mode(lowered)
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
            level = self._extract_volume_level(lowered)
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

        if self._mentions_video_toggle(lowered):
            muted = self._extract_toggle_state(
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

        if self._is_set_camera_mode_request(lowered):
            writable_camera_mode = self._extract_camera_mode(lowered)
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
            enabled = self._extract_toggle_state(
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
                    target_device=mentioned_target_device or message.target_device,
                )
            )

        if "presentation" in lowered or "share" in lowered:
            enabled = self._extract_toggle_state(
                lowered,
                enable_words={
                    "start presentation",
                    "presentation start",
                    "start share",
                    "turn on presentation",
                    "turn on share",
                },
                disable_words={
                    "stop presentation",
                    "presentation stop",
                    "stop share",
                    "turn off presentation",
                    "turn off share",
                },
            )
            if enabled is not None:
                return OrchestrationDecision(
                    action_proposal=ActionProposal(
                        intent=Intent.SET_PRESENTATION,
                        summary="Start or stop presentation.",
                        set_presentation=SetPresentationParams(
                            target_device=target_device,
                            enabled=enabled,
                        ),
                    )
                )

        matrix_assign = self._extract_matrix_assign(text)
        if matrix_assign is not None:
            if mentioned_target_device is None:
                return OrchestrationDecision(
                    pending_action=PendingActionProposal(
                        intent=Intent.ASSIGN_MATRIX,
                        summary="Assign a video matrix source to an output.",
                        action_proposal=ActionProposal(
                            intent=Intent.ASSIGN_MATRIX,
                            summary="Assign a video matrix source to an output.",
                            assign_matrix=AssignMatrixParams(
                                target_device="",
                                output=matrix_assign["output"],
                                mode=matrix_assign["mode"],
                                layout=matrix_assign["layout"],
                                source_id=matrix_assign["source_id"],
                                remote_main=matrix_assign["remote_main"],
                            ),
                        ),
                    )
                )
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.ASSIGN_MATRIX,
                    summary="Assign a video matrix source to an output.",
                    assign_matrix=AssignMatrixParams(
                        target_device=target_device,
                        output=matrix_assign["output"],
                        mode=matrix_assign["mode"],
                        layout=matrix_assign["layout"],
                        source_id=matrix_assign["source_id"],
                        remote_main=matrix_assign["remote_main"],
                    ),
                )
            )

        matrix_unassign = self._extract_matrix_unassign(text)
        if matrix_unassign is not None:
            if mentioned_target_device is None:
                return OrchestrationDecision(
                    pending_action=PendingActionProposal(
                        intent=Intent.UNASSIGN_MATRIX,
                        summary="Unassign a video matrix source from an output.",
                        action_proposal=ActionProposal(
                            intent=Intent.UNASSIGN_MATRIX,
                            summary="Unassign a video matrix source from an output.",
                            unassign_matrix=UnassignMatrixParams(
                                target_device="",
                                output=matrix_unassign["output"],
                                source_id=matrix_unassign["source_id"],
                                remote_main=matrix_unassign["remote_main"],
                            ),
                        ),
                    )
                )
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.UNASSIGN_MATRIX,
                    summary="Unassign a video matrix source from an output.",
                    unassign_matrix=UnassignMatrixParams(
                        target_device=target_device,
                        output=matrix_unassign["output"],
                        source_id=matrix_unassign["source_id"],
                        remote_main=matrix_unassign["remote_main"],
                    ),
                )
            )

        matrix_swap = self._extract_matrix_swap(text)
        if matrix_swap is not None:
            if mentioned_target_device is None:
                return OrchestrationDecision(
                    pending_action=PendingActionProposal(
                        intent=Intent.SWAP_MATRIX,
                        summary="Swap two video matrix outputs.",
                        action_proposal=ActionProposal(
                            intent=Intent.SWAP_MATRIX,
                            summary="Swap two video matrix outputs.",
                            swap_matrix=SwapMatrixParams(
                                target_device="",
                                output_a=matrix_swap["output_a"],
                                output_b=matrix_swap["output_b"],
                            ),
                        ),
                    )
                )
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SWAP_MATRIX,
                    summary="Swap two video matrix outputs.",
                    swap_matrix=SwapMatrixParams(
                        target_device=target_device,
                        output_a=matrix_swap["output_a"],
                        output_b=matrix_swap["output_b"],
                    ),
                )
            )

        source_id = self._extract_source_id(text)
        if source_id is not None:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SWITCH_INPUT_SOURCE,
                    summary="Switch the main video input source.",
                    switch_input_source=SwitchInputSourceParams(
                        target_device=target_device,
                        source_id=source_id,
                    ),
                )
            )

        layout_name = self._extract_layout_name(text)
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

        display_mode = self._extract_display_mode(lowered)
        if (
            "display mode" in lowered
            or "monitor mode" in lowered
            or display_mode is not None
        ):
            if display_mode is not None:
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
            connector_id = self._extract_connector_id(text)
            display_role = self._extract_display_role(lowered)
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

        camera_position = self._extract_camera_position(text)
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
            preset_id = self._extract_preset_id(text)
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

        if "speakertrack" in lowered or "speaker track" in lowered:
            enabled = self._extract_toggle_state(
                lowered,
                enable_words={
                    "speakertrack on",
                    "activate speakertrack",
                    "speaker track on",
                    "turn on speakertrack",
                    "turn on speaker track",
                },
                disable_words={
                    "speakertrack off",
                    "deactivate speakertrack",
                    "speaker track off",
                    "turn off speakertrack",
                    "turn off speaker track",
                },
            )
            if enabled is not None:
                return OrchestrationDecision(
                    action_proposal=ActionProposal(
                        intent=Intent.SET_SPEAKERTRACK,
                        summary="Change SpeakerTrack state.",
                        set_speakertrack=SetSpeakerTrackParams(
                            target_device=target_device,
                            enabled=enabled,
                        ),
                    )
                )

        if "standby" in lowered:
            enabled = self._extract_toggle_state(
                lowered,
                enable_words={
                    "standby on",
                    "activate standby",
                    "enter standby",
                    "turn on standby",
                },
                disable_words={
                    "standby off",
                    "deactivate standby",
                    "exit standby",
                    "turn off standby",
                },
            )
            if enabled is not None:
                return OrchestrationDecision(
                    action_proposal=ActionProposal(
                        intent=Intent.SET_STANDBY,
                        summary="Change standby state.",
                        set_standby=SetStandbyParams(
                            target_device=target_device,
                            enabled=enabled,
                        ),
                    )
                )

        if "reboot" in lowered:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.REBOOT,
                    summary="Reboot the target device.",
                    reboot=RebootParams(target_device=target_device),
                )
            )

        if "factory reset" in lowered:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.FACTORY_RESET,
                    summary="Factory reset the target device.",
                    factory_reset=FactoryResetParams(
                        target_device=target_device,
                        acknowledged=(
                            "confirm" in lowered or "yes" in lowered or "ack" in lowered
                        ),
                    ),
                )
            )

        fallback = (
            "I can currently help with read-only device status. "
            "Try 'get status of RoomKit-7F' or '/reset'."
        )
        if session.last_intent == Intent.GET_STATUS:
            fallback = "I only support the get_status flow in this MVP. Try another device status query or '/reset'."

        return OrchestrationDecision(reply_text=fallback)

    def _is_list_devices_request(self, lowered_text: str) -> bool:
        if lowered_text.strip().endswith(" drop"):
            return False
        return any(
            phrase in lowered_text
            for phrase in {
                "device list",
                "list devices",
                "show devices",
                "show me devices",
                "디바이스 리스트",
                "장비 리스트",
                "디바이스 목록",
                "장비 목록",
            }
        )

    def _is_get_camera_mode_request(self, lowered_text: str) -> bool:
        if not self._mentions_camera_mode(lowered_text):
            return False
        return any(
            phrase in lowered_text
            for phrase in {
                "camera mode",
                "camera tracking mode",
                "what camera mode",
                "which camera mode",
                "current camera mode",
                "get camera mode",
                "show camera mode",
                "camera framing mode",
            }
        ) and not self._is_set_camera_mode_request(lowered_text)

    def _is_get_environment_info_request(self, lowered_text: str) -> bool:
        environment_keywords = {
            "temperature",
            "humidity",
            "noise",
            "people count",
            "air quality",
            "environment",
            "sensor",
            "ambient",
            "온도",
            "습도",
            "소음",
            "공기질",
            "환경",
            "센서",
        }
        if "status" in lowered_text and not any(
            keyword in lowered_text for keyword in environment_keywords
        ):
            return False
        return any(
            phrase in lowered_text
            for phrase in {
                "get environment info",
                "environment info",
                "environment data",
                "environment sensor",
                "sensor info",
                "room analytics",
                "temperature",
                "humidity",
                "ambient noise",
                "noise level",
                "people count",
                "air quality",
                "온도",
                "습도",
                "소음",
                "공기질",
                "환경 정보",
                "센서 정보",
            }
        )

    def _is_get_room_booking_request(self, lowered_text: str) -> bool:
        booking_phrases = {
            "booking info",
            "room booking",
            "booked",
            "next meeting",
            "scheduled meeting",
            "obtp available",
            "one button to push",
        }
        if not any(phrase in lowered_text for phrase in booking_phrases):
            return False
        if self._is_join_obtp_request(lowered_text):
            return False
        return any(
            phrase in lowered_text
            for phrase in {
                "show booking info",
                "get booking info",
                "room booking",
                "is the room booked",
                "is room booked",
                "next meeting",
                "scheduled meeting",
                "obtp available",
                "is obtp available",
                "one button to push",
            }
        )

    def _is_webex_join_request(self, lowered_text: str) -> bool:
        if "webex join" in lowered_text or "join webex" in lowered_text:
            return True
        if lowered_text.strip() in {"join meeting", "join a meeting", "join the meeting"}:
            return True
        return (
            ("미팅" in lowered_text or "회의" in lowered_text or "meeting" in lowered_text)
            and any(
                phrase in lowered_text
                for phrase in {
                    "참여",
                    "참가",
                    "입장",
                    "조인",
                    "join",
                }
            )
        )

    def _is_join_obtp_request(self, lowered_text: str) -> bool:
        return any(
            phrase in lowered_text
            for phrase in {
                "join scheduled meeting",
                "join the scheduled meeting",
                "join obtp",
                "join the obtp",
                "join next meeting",
                "join the next meeting",
            }
        )

    def _is_set_camera_mode_request(self, lowered_text: str) -> bool:
        return any(
            phrase in lowered_text
            for phrase in {
                "set camera mode",
                "camera mode to",
                "camera mode best",
                "camera mode speaker",
                "camera mode frames",
                "switch camera mode",
                "change camera mode",
                "enable frames",
                "speaker closeup",
                "best overview",
            }
        )

    def _mentions_camera_mode(self, lowered_text: str) -> bool:
        return any(
            phrase in lowered_text
            for phrase in {
                "camera mode",
                "camera framing",
                "frames",
                "speaker closeup",
                "best overview",
            }
        )

    def _extract_target_device(self, text: str, explicit_target: str | None) -> str:
        mentioned_target_device = self._extract_mentioned_target_device(
            text, explicit_target
        )
        if mentioned_target_device is not None:
            return mentioned_target_device
        return self.default_target_device

    def _extract_mentioned_target_device(
        self, text: str, explicit_target: str | None
    ) -> str | None:
        if explicit_target:
            return explicit_target

        korean_phrase_target = self._extract_korean_phrase_target_device(text)
        if korean_phrase_target is not None:
            return korean_phrase_target

        lowered = " ".join(text.casefold().split())
        if "룸바" in lowered or "룸 바" in lowered or "room bar" in lowered:
            return "Room Bar"

        trailing_target = self._extract_trailing_target_device(text)
        if trailing_target is not None:
            return trailing_target

        turn_toggle_target = self._extract_turn_toggle_target_device(text)
        if turn_toggle_target is not None:
            return turn_toggle_target

        match = re.search(
            r"(?:status|volume|reboot|factory reset|webex join|join webex|dial|call|hang up|hangup|drop|dtmf|mute|unmute|selfview|layout|presentation|share|input source|camera preset|speakertrack|speaker track|standby|전화|통화)\s+(?:of|on|for|로|으로)\s+([A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        return match.group(1).strip().rstrip("?.!")

    def _extract_trailing_target_device(self, text: str) -> str | None:
        match = re.search(
            r"\b(?:on|for|of)\s+([A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)\s*[?.!]*$",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        candidate = match.group(1).strip().rstrip("?.!")
        lowered = " ".join(text.casefold().split())
        normalized_candidate = " ".join(candidate.casefold().split())
        if lowered.startswith("turn on ") and normalized_candidate in self.TOGGLE_ACTION_NAMES:
            return None
        return candidate

    def _extract_turn_toggle_target_device(self, text: str) -> str | None:
        lowered = " ".join(text.casefold().split())
        for action in ("turn on", "turn off"):
            prefix = f"{action} "
            if not lowered.startswith(prefix):
                continue
            candidate = text[len(prefix) :].strip().rstrip("?.!")
            normalized_candidate = " ".join(candidate.casefold().split())
            if normalized_candidate in self.TOGGLE_ACTION_NAMES:
                return None
            if candidate:
                return candidate
        return None

    def _strip_trailing_target_clause(self, text: str) -> str:
        match = re.search(
            r"^(.*?)(?:\s+\b(?:on|for|of)\s+[A-Za-z0-9._:-]+(?:\s+[A-Za-z0-9._:-]+)*)\s*[?.!]*$",
            text,
            re.IGNORECASE,
        )
        if not match:
            return text.strip().rstrip("?.!")
        return match.group(1).strip().rstrip("?.!")

    def _extract_korean_phrase_target_device(self, text: str) -> str | None:
        lowered = text.lower()
        if not any(
            token in lowered
            for token in {
                "전화",
                "통화",
                "음소거",
                "뮤트",
                "언뮤트",
                "미팅",
                "회의",
            }
        ):
            return None

        email_match = re.search(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+", text)
        candidate_text = text if email_match is None else text[: email_match.start()]
        number_match = re.search(r"(?<!\d)(?:\d[\s-]*){9,14}(?!\d)", candidate_text)
        if number_match is not None:
            before_number = candidate_text[: number_match.start()].strip()
            target_match = re.search(r"(.+?)(?:로|으로)\s*$", before_number)
            if target_match:
                candidate = target_match.group(1).strip().rstrip("?.!")
                return candidate or None
        candidate_match = re.search(r"(.+?)(?:로|으로)\s*$", candidate_text)
        if not candidate_match:
            candidate_match = re.search(
                r"^(.+?)\s+(?:음소거(?:\s+해줘)?|뮤트(?:해줘)?|언뮤트(?:해줘)?|음소거\s+해제(?:해줘)?)\s*$",
                candidate_text,
            )
        if not candidate_match:
            return None

        candidate = candidate_match.group(1).strip().rstrip("?.!")
        if not candidate:
            return None
        if any(
            token in candidate.lower()
            for token in {
                "전화",
                "통화",
                "call",
                "dial",
                "음소거",
                "뮤트",
                "언뮤트",
                "미팅",
                "회의",
            }
        ):
            return None
        return candidate

    def _extract_volume_level(self, text: str) -> int | None:
        match = re.search(r"(?:set volume|volume)\s+(?:to\s+)?(\d{1,3})", text)
        if match:
            level = int(match.group(1))
            return level if 0 <= level <= 100 else None
        lowered = text.lower()
        if any(
            token in lowered
            for token in {"volume up", "increase volume", "볼륨 올", "볼륨 높"}
        ):
            return None
        if any(
            token in lowered
            for token in {
                "volume down",
                "decrease volume",
                "볼륨 내",
                "볼륨 낮",
                "볼륨 줄",
            }
        ):
            return None
        return None

    def _extract_webex_meeting_identifier(self, text: str) -> str | None:
        stripped_text = self._strip_trailing_target_clause(text)
        match = re.search(
            r"(?:webex join|join webex)(?:\s+meeting)?\s+([A-Za-z0-9@._:-]+)",
            stripped_text,
            re.IGNORECASE,
        )
        if not match:
            digit_match = re.search(r"(?<!\d)(?:\d[\s-]*){9,14}(?!\d)", stripped_text)
            if digit_match:
                candidate = re.sub(r"\D+", "", digit_match.group(0))
                return candidate if 9 <= len(candidate) <= 14 else None
            return None
        candidate = match.group(1).strip().rstrip("?.!")
        if candidate.lower() in {"on", "for", "of"}:
            return None
        return re.sub(r"\D+", "", candidate) if re.fullmatch(r"[\d\s-]+", candidate) else candidate

    def _extract_dial_address(self, text: str) -> str | None:
        stripped_text = self._strip_trailing_target_clause(text)
        match = re.search(
            r"(?:dial|call|join sip|sip|전화(?:해줘)?|통화(?:해줘)?)\s+(?:to\s+|로\s+|으로\s+)?([A-Za-z0-9@._:+-]+)",
            stripped_text,
            re.IGNORECASE,
        )
        if not match:
            fallback_match = re.search(
                r"([A-Za-z0-9._+-]+@[A-Za-z0-9.-]+)", stripped_text
            )
            if not fallback_match:
                return None
            return fallback_match.group(1).strip().rstrip("?.!")
        return match.group(1).strip().rstrip("?.!")

    def _extract_dtmf_tones(self, text: str) -> str | None:
        match = re.search(
            r"(?:dtmf|send tone|send digits)\s+(?:to\s+)?([0-9A-D#*,]+)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        return match.group(1).strip().upper()

    def _extract_call_id(self, text: str) -> int | None:
        match = re.search(r"call(?:\s+id)?\s+(\d+)", text, re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    def _mentions_microphone_toggle(self, lowered_text: str) -> bool:
        return (
            "microphone" in lowered_text
            or "mic " in lowered_text
            or lowered_text.endswith(" mic")
            or "mute" in lowered_text
            or "unmute" in lowered_text
            or "음소거" in lowered_text
            or "뮤트" in lowered_text
            or "언뮤트" in lowered_text
        )

    def _mentions_video_toggle(self, lowered_text: str) -> bool:
        return (
            "video" in lowered_text
            or "camera" in lowered_text
            or "비디오" in lowered_text
            or "카메라" in lowered_text
        )

    def _extract_camera_mode(self, lowered_text: str) -> WritableCameraMode | None:
        mode_phrases: dict[WritableCameraMode, set[str]] = {
            WritableCameraMode.MANUAL: {"manual", "수동"},
            WritableCameraMode.DYNAMIC: {"dynamic", "동적"},
            WritableCameraMode.BEST_OVERVIEW: {
                "best overview",
                "best_overview",
                "bestoverview",
                "overview",
            },
            WritableCameraMode.CLOSEUP: {
                "closeup",
                "close up",
                "speaker closeup",
                "speaker close up",
            },
            WritableCameraMode.FRAMES: {"frames", "frame"},
            WritableCameraMode.GROUP_AND_SPEAKER: {
                "group and speaker",
                "group_and_speaker",
                "groupandspeaker",
                "group speaker",
            },
        }
        for mode, phrases in mode_phrases.items():
            if any(phrase in lowered_text for phrase in phrases):
                return mode
        return None

    def _extract_toggle_state(
        self,
        lowered_text: str,
        enable_words: set[str],
        disable_words: set[str],
        enable_value: bool = True,
    ) -> bool | None:
        for phrase in disable_words:
            if phrase in lowered_text:
                return not enable_value
        for phrase in enable_words:
            if phrase in lowered_text:
                return enable_value
        return None

    def _extract_layout_name(self, text: str) -> str | None:
        lowered = text.lower()
        if any(phrase in lowered for phrase in self.PROMINENT_LAYOUT_PHRASES):
            return "Prominent"
        match = re.search(r"layout\s+(?:to\s+)?([A-Za-z0-9_-]+)", text, re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip().rstrip("?.!")

    def _extract_source_id(self, text: str) -> str | None:
        match = self.SOURCE_ALIAS_PATTERN.search(text)
        if not match:
            return None
        return match.group(1).strip().rstrip("?.!")

    def _extract_matrix_assign(self, text: str) -> MatrixAssignMatch | None:
        stripped_text = self._strip_trailing_target_clause(text)
        match = re.search(
            r"matrix\s+assign\s+output\s+([A-Za-z0-9_-]+)\s+(?:to\s+)?mode\s+([A-Za-z0-9_-]+)\s+layout\s+([A-Za-z0-9_-]+)(?:\s+source\s+([A-Za-z0-9_-]+))?(?:\s+(remote\s+main))?",
            stripped_text,
            re.IGNORECASE,
        )
        if not match:
            return None
        remote_main = match.group(5)
        return {
            "output": match.group(1).strip().rstrip("?.!"),
            "mode": match.group(2).strip().rstrip("?.!"),
            "layout": match.group(3).strip().rstrip("?.!"),
            "source_id": (
                match.group(4).strip().rstrip("?.!")
                if match.group(4) is not None
                else None
            ),
            "remote_main": True if remote_main is not None else None,
        }

    def _extract_matrix_unassign(self, text: str) -> MatrixUnassignMatch | None:
        stripped_text = self._strip_trailing_target_clause(text)
        match = re.search(
            r"matrix\s+unassign\s+output\s+([A-Za-z0-9_-]+)(?:\s+source\s+([A-Za-z0-9_-]+))?(?:\s+(remote\s+main))?",
            stripped_text,
            re.IGNORECASE,
        )
        if not match:
            return None
        remote_main = match.group(3)
        return {
            "output": match.group(1).strip().rstrip("?.!"),
            "source_id": (
                match.group(2).strip().rstrip("?.!")
                if match.group(2) is not None
                else None
            ),
            "remote_main": True if remote_main is not None else None,
        }

    def _extract_matrix_swap(self, text: str) -> MatrixSwapMatch | None:
        stripped_text = self._strip_trailing_target_clause(text)
        match = re.search(
            r"matrix\s+swap\s+output\s+([A-Za-z0-9_-]+)\s+(?:with|and)\s+output\s+([A-Za-z0-9_-]+)",
            stripped_text,
            re.IGNORECASE,
        )
        if not match:
            return None
        return {
            "output_a": match.group(1).strip().rstrip("?.!"),
            "output_b": match.group(2).strip().rstrip("?.!"),
        }

    def _extract_preset_id(self, text: str) -> str | None:
        match = re.search(
            r"(?:camera preset|preset)\s+(?:to\s+)?([A-Za-z0-9_-]+)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        return match.group(1).strip().rstrip("?.!")

    def _extract_camera_position(self, text: str) -> CameraPositionMatch | None:
        stripped_text = self._strip_trailing_target_clause(text)
        lowered = stripped_text.lower()
        if "camera preset" in lowered or "speakertrack" in lowered:
            return None

        camera_match = re.search(
            r"\bcamera\s+(\d+)\b",
            stripped_text,
            re.IGNORECASE,
        )
        if camera_match is None:
            return None

        pan: int | None = None
        tilt: int | None = None
        zoom: int | None = None

        if re.search(r"\b(?:pan\s+)?left\b", lowered):
            pan = self.CAMERA_PAN_STEP
        elif re.search(r"\b(?:pan\s+)?right\b", lowered):
            pan = -self.CAMERA_PAN_STEP

        if re.search(r"\b(?:tilt\s+)?up\b", lowered):
            tilt = self.CAMERA_TILT_STEP
        elif re.search(r"\b(?:tilt\s+)?down\b", lowered):
            tilt = -self.CAMERA_TILT_STEP

        if re.search(r"\bzoom\s+in\b", lowered):
            zoom = -self.CAMERA_ZOOM_STEP
        elif re.search(r"\bzoom\s+out\b", lowered):
            zoom = self.CAMERA_ZOOM_STEP

        if pan is None and tilt is None and zoom is None:
            return None

        return {
            "camera_id": camera_match.group(1).strip().rstrip("?.!"),
            "pan": pan,
            "tilt": tilt,
            "zoom": zoom,
        }

    def _extract_microphone_mode(
        self, lowered_text: str
    ) -> MicrophoneProcessingMode | None:
        mode_phrases: dict[MicrophoneProcessingMode, set[str]] = {
            MicrophoneProcessingMode.NORMAL: {"normal", "standard"},
            MicrophoneProcessingMode.NOISE_REDUCTION: {
                "noise reduction",
                "noise-reduction",
            },
            MicrophoneProcessingMode.VOICE_OPTIMIZED: {
                "voice optimized",
                "voice-optimized",
                "focused",
            },
            MicrophoneProcessingMode.MUSIC_MODE: {"music mode", "music-mode"},
        }
        for mode, phrases in mode_phrases.items():
            if any(phrase in lowered_text for phrase in phrases):
                return mode
        return None

    def _extract_display_mode(self, lowered_text: str) -> DisplayMode | None:
        compact_text = re.sub(r"\s+", "", lowered_text)
        mode_phrases: tuple[tuple[DisplayMode, tuple[str, ...]], ...] = (
            (
                DisplayMode.LEFT_VIDEO_RIGHT_PRESENTATION,
                (
                    "left video right presentation",
                    "left-video-right-presentation",
                    "dual presentation only",
                    "dual-presentation-only",
                    "dual presentation-only",
                    "dual-presentation only",
                    "dualpresentationonly",
                    "왼쪽영상오른쪽프리젠테이션",
                    "왼쪽영상오른쪽프레젠테이션",
                ),
            ),
            (
                DisplayMode.LEFT_PRESENTATION_RIGHT_VIDEO,
                (
                    "left presentation right video",
                    "left-presentation-right-video",
                    "왼쪽프리젠테이션오른쪽영상",
                    "왼쪽프레젠테이션오른쪽영상",
                ),
            ),
            (
                DisplayMode.BOTH_PRESENTATION,
                (
                    "both presentation",
                    "both-presentation",
                    "양쪽모두프리젠테이션",
                    "양쪽모두프레젠테이션",
                ),
            ),
            (
                DisplayMode.LEFT_VIDEO_RIGHT_VIDEO,
                (
                    "left video right video",
                    "left-video-right-video",
                    "dual",
                    "왼쪽영상오른쪽영상",
                ),
            ),
        )
        for mode, phrases in mode_phrases:
            if any(phrase in lowered_text or phrase in compact_text for phrase in phrases):
                return mode
        return None

    def _extract_display_role(self, lowered_text: str) -> DisplayRole | None:
        role_phrases: dict[DisplayRole, set[str]] = {
            DisplayRole.AUTO: {"auto"},
            DisplayRole.FIRST: {"first"},
            DisplayRole.SECOND: {"second"},
            DisplayRole.THIRD: {"third"},
            DisplayRole.PRESENTATION_ONLY: {
                "presentation only",
                "presentation-only",
            },
            DisplayRole.RECORDER: {"recorder"},
        }
        for role, phrases in role_phrases.items():
            if any(phrase in lowered_text for phrase in phrases):
                return role
        return None

    def _extract_connector_id(self, text: str) -> int | None:
        match = re.search(r"connector\s+(\d+)", text, re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))
