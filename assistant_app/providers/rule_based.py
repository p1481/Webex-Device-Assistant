from __future__ import annotations

import re

from assistant_app.providers import rule_based_extractors as _rbx
from assistant_app.providers.rule_based_extractors import (
    CameraPositionMatch,
    MatrixAssignMatch,
    MatrixSwapMatch,
    MatrixUnassignMatch,
)
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
        return _rbx.is_list_devices_request(lowered_text)

    def _is_get_camera_mode_request(self, lowered_text: str) -> bool:
        return _rbx.is_get_camera_mode_request(lowered_text)

    def _is_get_environment_info_request(self, lowered_text: str) -> bool:
        return _rbx.is_get_environment_info_request(lowered_text)

    def _is_get_room_booking_request(self, lowered_text: str) -> bool:
        return _rbx.is_get_room_booking_request(lowered_text)

    def _is_webex_join_request(self, lowered_text: str) -> bool:
        return _rbx.is_webex_join_request(lowered_text)

    def _is_join_obtp_request(self, lowered_text: str) -> bool:
        return _rbx.is_join_obtp_request(lowered_text)

    def _is_set_camera_mode_request(self, lowered_text: str) -> bool:
        return _rbx.is_set_camera_mode_request(lowered_text)

    def _mentions_camera_mode(self, lowered_text: str) -> bool:
        return _rbx.mentions_camera_mode(lowered_text)

    def _extract_target_device(self, text: str, explicit_target: str | None) -> str:
        return _rbx.extract_target_device(text, explicit_target, self.default_target_device)

    def _extract_mentioned_target_device(
        self, text: str, explicit_target: str | None
    ) -> str | None:
        return _rbx.extract_mentioned_target_device(text, explicit_target)

    def _extract_trailing_target_device(self, text: str) -> str | None:
        return _rbx.extract_trailing_target_device(text)

    def _extract_turn_toggle_target_device(self, text: str) -> str | None:
        return _rbx.extract_turn_toggle_target_device(text)

    def _strip_trailing_target_clause(self, text: str) -> str:
        return _rbx.strip_trailing_target_clause(text)

    def _extract_korean_phrase_target_device(self, text: str) -> str | None:
        return _rbx.extract_korean_phrase_target_device(text)

    def _extract_volume_level(self, text: str) -> int | None:
        return _rbx.extract_volume_level(text)

    def _extract_webex_meeting_identifier(self, text: str) -> str | None:
        return _rbx.extract_webex_meeting_identifier(text)

    def _extract_dial_address(self, text: str) -> str | None:
        return _rbx.extract_dial_address(text)

    def _extract_dtmf_tones(self, text: str) -> str | None:
        return _rbx.extract_dtmf_tones(text)

    def _extract_call_id(self, text: str) -> int | None:
        return _rbx.extract_call_id(text)

    def _mentions_microphone_toggle(self, lowered_text: str) -> bool:
        return _rbx.mentions_microphone_toggle(lowered_text)

    def _mentions_video_toggle(self, lowered_text: str) -> bool:
        return _rbx.mentions_video_toggle(lowered_text)

    def _extract_camera_mode(self, lowered_text: str) -> WritableCameraMode | None:
        return _rbx.extract_camera_mode(lowered_text)

    def _extract_toggle_state(
        self,
        lowered_text: str,
        enable_words: set[str],
        disable_words: set[str],
        enable_value: bool = True,
    ) -> bool | None:
        return _rbx.extract_toggle_state(lowered_text, enable_words, disable_words, enable_value)

    def _extract_layout_name(self, text: str) -> str | None:
        return _rbx.extract_layout_name(text)

    def _extract_source_id(self, text: str) -> str | None:
        return _rbx.extract_source_id(text)

    def _extract_matrix_assign(self, text: str) -> MatrixAssignMatch | None:
        return _rbx.extract_matrix_assign(text)

    def _extract_matrix_unassign(self, text: str) -> MatrixUnassignMatch | None:
        return _rbx.extract_matrix_unassign(text)

    def _extract_matrix_swap(self, text: str) -> MatrixSwapMatch | None:
        return _rbx.extract_matrix_swap(text)

    def _extract_preset_id(self, text: str) -> str | None:
        return _rbx.extract_preset_id(text)

    def _extract_camera_position(self, text: str) -> CameraPositionMatch | None:
        return _rbx.extract_camera_position(text)

    def _extract_microphone_mode(
        self, lowered_text: str
    ) -> MicrophoneProcessingMode | None:
        return _rbx.extract_microphone_mode(lowered_text)

    def _extract_display_mode(self, lowered_text: str) -> DisplayMode | None:
        return _rbx.extract_display_mode(lowered_text)

    def _extract_display_role(self, lowered_text: str) -> DisplayRole | None:
        return _rbx.extract_display_role(lowered_text)

    def _extract_connector_id(self, text: str) -> int | None:
        return _rbx.extract_connector_id(text)
