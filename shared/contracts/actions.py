from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class Intent(StrEnum):
    CHAT = "chat"
    GET_STATUS = "get_status"
    GET_ENVIRONMENT_INFO = "get_environment_info"
    GET_CAMERA_MODE = "get_camera_mode"
    GET_ROOM_BOOKING = "get_room_booking"
    LIST_DEVICES = "list_devices"
    WEBEX_JOIN = "webex_join"
    JOIN_OBTP = "join_obtp"
    DIAL = "dial"
    HANG_UP = "hang_up"
    SEND_DTMF = "send_dtmf"
    SET_MICROPHONE_MUTE = "set_microphone_mute"
    SET_MICROPHONE_MODE = "set_microphone_mode"
    SET_VOLUME = "set_volume"
    SET_VIDEO_MUTE = "set_video_mute"
    SET_SELFVIEW = "set_selfview"
    SET_CAMERA_MODE = "set_camera_mode"
    SET_LAYOUT = "set_layout"
    SET_PRESENTATION = "set_presentation"
    SWITCH_INPUT_SOURCE = "switch_input_source"
    ASSIGN_MATRIX = "assign_matrix"
    UNASSIGN_MATRIX = "unassign_matrix"
    SWAP_MATRIX = "swap_matrix"
    SET_DISPLAY_MODE = "set_display_mode"
    SET_DISPLAY_ROLE = "set_display_role"
    ACTIVATE_CAMERA_PRESET = "activate_camera_preset"
    ADJUST_CAMERA_POSITION = "adjust_camera_position"
    SET_SPEAKERTRACK = "set_speakertrack"
    SET_STANDBY = "set_standby"
    REBOOT = "reboot"
    FACTORY_RESET = "factory_reset"
    RESET_CONTEXT = "reset_context"


class TargetDeviceParams(BaseModel):
    target_device: str


class GetStatusParams(TargetDeviceParams):
    include_metrics: bool = True


class GetEnvironmentInfoParams(TargetDeviceParams):
    pass


class GetCameraModeParams(TargetDeviceParams):
    pass


class GetRoomBookingParams(TargetDeviceParams):
    pass


class ListDevicesParams(BaseModel):
    limit: int = Field(default=10, ge=1, le=25)
    online_only: bool = False


class WebexJoinParams(TargetDeviceParams):
    meeting_identifier: str


class JoinObtpParams(TargetDeviceParams):
    pass


class DialParams(TargetDeviceParams):
    address: str


class HangUpParams(TargetDeviceParams):
    call_id: int | None = Field(default=None, gt=0)


class SendDtmfParams(TargetDeviceParams):
    tones: str
    call_id: int | None = Field(default=None, gt=0)


class SetMicrophoneMuteParams(TargetDeviceParams):
    muted: bool


class MicrophoneProcessingMode(StrEnum):
    NORMAL = "normal"
    NOISE_REDUCTION = "noise-reduction"
    VOICE_OPTIMIZED = "voice-optimized"
    MUSIC_MODE = "music-mode"


class SetMicrophoneModeParams(TargetDeviceParams):
    mode: MicrophoneProcessingMode


class SetVolumeParams(TargetDeviceParams):
    level: int = Field(ge=0, le=100)


class SetVideoMuteParams(TargetDeviceParams):
    muted: bool


class SetSelfviewParams(TargetDeviceParams):
    enabled: bool


class WritableCameraMode(StrEnum):
    MANUAL = "Manual"
    DYNAMIC = "Dynamic"
    BEST_OVERVIEW = "BestOverview"
    CLOSEUP = "Closeup"
    FRAMES = "Frames"
    GROUP_AND_SPEAKER = "GroupAndSpeaker"


class SetCameraModeParams(TargetDeviceParams):
    mode: WritableCameraMode


class SetLayoutParams(TargetDeviceParams):
    layout_name: str


class SetPresentationParams(TargetDeviceParams):
    enabled: bool


class SwitchInputSourceParams(TargetDeviceParams):
    source_id: str


class AssignMatrixParams(TargetDeviceParams):
    output: str
    mode: str
    layout: str
    source_id: str | None = None
    remote_main: bool | None = None


class UnassignMatrixParams(TargetDeviceParams):
    output: str
    source_id: str | None = None
    remote_main: bool | None = None


class SwapMatrixParams(TargetDeviceParams):
    output_a: str
    output_b: str


class DisplayMode(StrEnum):
    LEFT_VIDEO_RIGHT_VIDEO = "left-video-right-video"
    LEFT_VIDEO_RIGHT_PRESENTATION = "left-video-right-presentation"
    LEFT_PRESENTATION_RIGHT_VIDEO = "left-presentation-right-video"
    BOTH_PRESENTATION = "both-presentation"


class SetDisplayModeParams(TargetDeviceParams):
    mode: DisplayMode


class DisplayRole(StrEnum):
    AUTO = "auto"
    FIRST = "first"
    SECOND = "second"
    THIRD = "third"
    PRESENTATION_ONLY = "presentation-only"
    RECORDER = "recorder"


class SetDisplayRoleParams(TargetDeviceParams):
    connector_id: int = Field(ge=1)
    role: DisplayRole


class ActivateCameraPresetParams(TargetDeviceParams):
    preset_id: str


class AdjustCameraPositionParams(TargetDeviceParams):
    camera_id: str
    pan: int | None = Field(default=None)
    tilt: int | None = Field(default=None)
    zoom: int | None = Field(default=None)

    @model_validator(mode="after")
    def validate_adjustment(self) -> AdjustCameraPositionParams:
        normalized_camera_id = self.camera_id.strip()
        if not normalized_camera_id.isdigit() or int(normalized_camera_id) <= 0:
            raise ValueError(
                "adjust_camera_position requires a positive decimal camera_id"
            )
        self.camera_id = normalized_camera_id
        if self.pan is None and self.tilt is None and self.zoom is None:
            raise ValueError(
                "adjust_camera_position requires pan, tilt, or zoom parameters"
            )
        return self


class SetSpeakerTrackParams(TargetDeviceParams):
    enabled: bool


class SetStandbyParams(TargetDeviceParams):
    enabled: bool


class RebootParams(TargetDeviceParams):
    pass


class FactoryResetParams(TargetDeviceParams):
    acknowledged: bool = False


ACTION_PROPOSAL_PAYLOAD_MODELS: dict[Intent, type[BaseModel]] = {
    Intent.GET_STATUS: GetStatusParams,
    Intent.GET_ENVIRONMENT_INFO: GetEnvironmentInfoParams,
    Intent.GET_CAMERA_MODE: GetCameraModeParams,
    Intent.GET_ROOM_BOOKING: GetRoomBookingParams,
    Intent.LIST_DEVICES: ListDevicesParams,
    Intent.WEBEX_JOIN: WebexJoinParams,
    Intent.JOIN_OBTP: JoinObtpParams,
    Intent.DIAL: DialParams,
    Intent.HANG_UP: HangUpParams,
    Intent.SEND_DTMF: SendDtmfParams,
    Intent.SET_MICROPHONE_MUTE: SetMicrophoneMuteParams,
    Intent.SET_MICROPHONE_MODE: SetMicrophoneModeParams,
    Intent.SET_VOLUME: SetVolumeParams,
    Intent.SET_VIDEO_MUTE: SetVideoMuteParams,
    Intent.SET_SELFVIEW: SetSelfviewParams,
    Intent.SET_CAMERA_MODE: SetCameraModeParams,
    Intent.SET_LAYOUT: SetLayoutParams,
    Intent.SET_PRESENTATION: SetPresentationParams,
    Intent.SWITCH_INPUT_SOURCE: SwitchInputSourceParams,
    Intent.ASSIGN_MATRIX: AssignMatrixParams,
    Intent.UNASSIGN_MATRIX: UnassignMatrixParams,
    Intent.SWAP_MATRIX: SwapMatrixParams,
    Intent.SET_DISPLAY_MODE: SetDisplayModeParams,
    Intent.SET_DISPLAY_ROLE: SetDisplayRoleParams,
    Intent.ACTIVATE_CAMERA_PRESET: ActivateCameraPresetParams,
    Intent.ADJUST_CAMERA_POSITION: AdjustCameraPositionParams,
    Intent.SET_SPEAKERTRACK: SetSpeakerTrackParams,
    Intent.SET_STANDBY: SetStandbyParams,
    Intent.REBOOT: RebootParams,
    Intent.FACTORY_RESET: FactoryResetParams,
}

ACTION_PROPOSAL_PAYLOAD_FIELDS: dict[Intent, str] = {
    Intent.GET_STATUS: "get_status",
    Intent.GET_ENVIRONMENT_INFO: "get_environment_info",
    Intent.GET_CAMERA_MODE: "get_camera_mode",
    Intent.GET_ROOM_BOOKING: "get_room_booking",
    Intent.LIST_DEVICES: "list_devices",
    Intent.WEBEX_JOIN: "webex_join",
    Intent.JOIN_OBTP: "join_obtp",
    Intent.DIAL: "dial",
    Intent.HANG_UP: "hang_up",
    Intent.SEND_DTMF: "send_dtmf",
    Intent.SET_MICROPHONE_MUTE: "set_microphone_mute",
    Intent.SET_MICROPHONE_MODE: "set_microphone_mode",
    Intent.SET_VOLUME: "set_volume",
    Intent.SET_VIDEO_MUTE: "set_video_mute",
    Intent.SET_SELFVIEW: "set_selfview",
    Intent.SET_CAMERA_MODE: "set_camera_mode",
    Intent.SET_LAYOUT: "set_layout",
    Intent.SET_PRESENTATION: "set_presentation",
    Intent.SWITCH_INPUT_SOURCE: "switch_input_source",
    Intent.ASSIGN_MATRIX: "assign_matrix",
    Intent.UNASSIGN_MATRIX: "unassign_matrix",
    Intent.SWAP_MATRIX: "swap_matrix",
    Intent.SET_DISPLAY_MODE: "set_display_mode",
    Intent.SET_DISPLAY_ROLE: "set_display_role",
    Intent.ACTIVATE_CAMERA_PRESET: "activate_camera_preset",
    Intent.ADJUST_CAMERA_POSITION: "adjust_camera_position",
    Intent.SET_SPEAKERTRACK: "set_speakertrack",
    Intent.SET_STANDBY: "set_standby",
    Intent.REBOOT: "reboot",
    Intent.FACTORY_RESET: "factory_reset",
}


def get_action_payload_field(intent: Intent) -> str | None:
    return ACTION_PROPOSAL_PAYLOAD_FIELDS.get(intent)


def intent_requires_target_device(intent: Intent) -> bool:
    payload_model = ACTION_PROPOSAL_PAYLOAD_MODELS.get(intent)
    return payload_model is not None and issubclass(payload_model, TargetDeviceParams)


class ActionProposal(BaseModel):
    intent: Intent
    summary: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    get_status: GetStatusParams | None = None
    get_environment_info: GetEnvironmentInfoParams | None = None
    get_camera_mode: GetCameraModeParams | None = None
    get_room_booking: GetRoomBookingParams | None = None
    list_devices: ListDevicesParams | None = None
    webex_join: WebexJoinParams | None = None
    join_obtp: JoinObtpParams | None = None
    dial: DialParams | None = None
    hang_up: HangUpParams | None = None
    send_dtmf: SendDtmfParams | None = None
    set_microphone_mute: SetMicrophoneMuteParams | None = None
    set_microphone_mode: SetMicrophoneModeParams | None = None
    set_volume: SetVolumeParams | None = None
    set_video_mute: SetVideoMuteParams | None = None
    set_selfview: SetSelfviewParams | None = None
    set_camera_mode: SetCameraModeParams | None = None
    set_layout: SetLayoutParams | None = None
    set_presentation: SetPresentationParams | None = None
    switch_input_source: SwitchInputSourceParams | None = None
    assign_matrix: AssignMatrixParams | None = None
    unassign_matrix: UnassignMatrixParams | None = None
    swap_matrix: SwapMatrixParams | None = None
    set_display_mode: SetDisplayModeParams | None = None
    set_display_role: SetDisplayRoleParams | None = None
    activate_camera_preset: ActivateCameraPresetParams | None = None
    adjust_camera_position: AdjustCameraPositionParams | None = None
    set_speakertrack: SetSpeakerTrackParams | None = None
    set_standby: SetStandbyParams | None = None
    reboot: RebootParams | None = None
    factory_reset: FactoryResetParams | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> ActionProposal:
        payload_name = get_action_payload_field(self.intent)
        if payload_name is not None and getattr(self, payload_name) is None:
            raise ValueError(
                f"{self.intent.value} proposal requires {payload_name} parameters"
            )
        return self


class PendingActionProposal(BaseModel):
    pending_action_id: str = Field(default_factory=lambda: str(uuid4()))
    intent: Intent
    summary: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    target_device: str | None = None
    meeting_identifier: str | None = None
    address: str | None = None
    level: int | None = Field(default=None, ge=0, le=100)
    display_mode: DisplayMode | None = None
    camera_mode: WritableCameraMode | None = None
    action_proposal: ActionProposal | None = None


class OrchestrationDecision(BaseModel):
    reply_text: str | None = None
    action_proposal: ActionProposal | None = None
    pending_action: PendingActionProposal | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> OrchestrationDecision:
        if (
            self.reply_text is None
            and self.action_proposal is None
            and self.pending_action is None
        ):
            raise ValueError(
                "decision requires reply_text, action_proposal, or pending_action"
            )
        return self


_ = PendingActionProposal.model_rebuild()
