from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .actions import (
    ActivateCameraPresetParams,
    AdjustCameraPositionParams,
    AssignMatrixParams,
    DialParams,
    FactoryResetParams,
    GetCameraModeParams,
    GetEnvironmentInfoParams,
    GetRoomBookingParams,
    GetStatusParams,
    HangUpParams,
    Intent,
    JoinObtpParams,
    ListDevicesParams,
    RebootParams,
    SendDtmfParams,
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
)
from .admin import OrganizationDeviceRecord
from .policy import ApprovalState, ExecutionMode


class ExecutionStatus(StrEnum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class DeviceStatusSnapshot(BaseModel):
    target_device: str
    source: str
    device_id: str | None = None
    display_name: str | None = None
    workspace_id: str | None = None
    product: str | None = None
    product_platform: str | None = None
    place: str | None = None
    software_version: str | None = None
    software_display_name: str | None = None
    serial_number: str | None = None
    online: bool = True
    connection_status: str | None = None
    system_state: str | None = None
    active_interface: str | None = None
    ipv4_address: str | None = None
    wifi_status: str | None = None
    volume: int | None = None
    volume_muted: bool | None = None
    microphones_muted: bool | None = None
    call_active: bool | None = None
    active_call_count: int | None = None
    presentation_active: bool | None = None
    presentation_mode: str | None = None
    selfview_mode: str | None = None
    selfview_fullscreen: str | None = None
    speakertrack_state: str | None = None
    presentertrack_status: str | None = None
    standby_state: str | None = None
    detail: str | None = None


class CameraModeStatus(BaseModel):
    target_device: str
    source: str
    device_id: str | None = None
    display_name: str | None = None
    current_mode: str | None = None
    effective_mode: str | None = None
    available_modes: list[str] = Field(default_factory=list)
    detail: str | None = None


class EnvironmentInfoStatus(BaseModel):
    target_device: str
    source: str
    device_id: str | None = None
    display_name: str | None = None
    temperature_celsius: float | None = None
    relative_humidity_percent: float | None = None
    ambient_noise_db: float | None = None
    people_count: int | None = None
    air_quality_index: int | None = None
    detail: str | None = None


class RoomBookingStatus(BaseModel):
    target_device: str
    source: str
    device_id: str | None = None
    display_name: str | None = None
    availability_status: str | None = None
    availability_timestamp: str | None = None
    current_booking_id: str | None = None
    is_booked_now: bool | None = None
    next_booking_id: str | None = None
    next_meeting_title: str | None = None
    next_meeting_start_time: str | None = None
    next_meeting_end_time: str | None = None
    obtp_available: bool | None = None
    obtp_join_method: str | None = None
    detail: str | None = None


class ExecutionRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    requested_by: str
    requested_by_email: str | None = None
    intent: Intent
    execution_mode: ExecutionMode
    approval_state: ApprovalState
    approval_request_id: str | None = None
    target_device: str | None = None
    reason: str
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
    def validate_payload(self) -> ExecutionRequest:
        required_payloads: dict[Intent, str] = {
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
        payload_name = required_payloads.get(self.intent)
        if payload_name is not None and getattr(self, payload_name) is None:
            raise ValueError(
                f"{self.intent.value} execution request requires {payload_name} parameters"
            )
        return self


class ExecutionResult(BaseModel):
    request_id: str
    intent: Intent
    execution_mode: ExecutionMode
    status: ExecutionStatus
    message: str
    approval_request_id: str | None = None
    audit_id: str | None = None
    device_status: DeviceStatusSnapshot | None = None
    environment_info_status: EnvironmentInfoStatus | None = None
    camera_mode_status: CameraModeStatus | None = None
    room_booking_status: RoomBookingStatus | None = None
    devices: list[OrganizationDeviceRecord] | None = None
    failed_target_device: str | None = None
    resolution_error: str | None = None
    candidate_devices: list[OrganizationDeviceRecord] | None = None
