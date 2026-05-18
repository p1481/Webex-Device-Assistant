from __future__ import annotations

from device_executor.device_client import DeviceClient
from shared.contracts import ExecutionRequest, ExecutionResult, ExecutionStatus, Intent


class ExecutionHandlers:
    def __init__(self, device_client: DeviceClient) -> None:
        self.device_client: DeviceClient = device_client

    async def handle(self, request: ExecutionRequest) -> ExecutionResult:
        if request.intent == Intent.GET_STATUS and request.get_status is not None:
            status_snapshot = await self.device_client.get_status(request.get_status.target_device)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=f"Collected status from {status_snapshot.target_device} via separated mode.",
                approval_request_id=request.approval_request_id,
                device_status=status_snapshot,
            )

        if (
            request.intent == Intent.GET_ENVIRONMENT_INFO
            and request.get_environment_info is not None
        ):
            environment_info_status = await self.device_client.get_environment_info(
                request.get_environment_info.target_device
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=(
                    "Collected environment info from "
                    f"{environment_info_status.target_device} via separated mode."
                ),
                approval_request_id=request.approval_request_id,
                environment_info_status=environment_info_status,
            )

        if request.intent == Intent.GET_CAMERA_MODE and request.get_camera_mode is not None:
            camera_mode_status = await self.device_client.get_camera_mode(
                request.get_camera_mode.target_device
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=(
                    f"Collected camera mode from {camera_mode_status.target_device} via separated mode."
                ),
                approval_request_id=request.approval_request_id,
                camera_mode_status=camera_mode_status,
            )

        if request.intent == Intent.GET_ROOM_BOOKING and request.get_room_booking is not None:
            room_booking_status = await self.device_client.get_room_booking(
                request.get_room_booking.target_device
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=(
                    "Collected room booking info from "
                    f"{room_booking_status.target_device} via separated mode."
                ),
                approval_request_id=request.approval_request_id,
                room_booking_status=room_booking_status,
            )

        if request.intent == Intent.LIST_DEVICES and request.list_devices is not None:
            devices = await self.device_client.list_devices()
            if request.list_devices.online_only:
                devices = [device for device in devices if device.online is True]
            limited_devices = devices[: request.list_devices.limit]
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message="Collected organization device inventory via separated mode.",
                approval_request_id=request.approval_request_id,
                devices=limited_devices,
            )

        if request.intent == Intent.WEBEX_JOIN and request.webex_join is not None:
            message = await self.device_client.webex_join(
                request.webex_join.target_device,
                request.webex_join.meeting_identifier,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.JOIN_OBTP and request.join_obtp is not None:
            message = await self.device_client.join_obtp(request.join_obtp.target_device)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.DIAL and request.dial is not None:
            message = await self.device_client.dial(
                request.dial.target_device,
                request.dial.address,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.HANG_UP and request.hang_up is not None:
            message = await self.device_client.hang_up(
                request.hang_up.target_device,
                request.hang_up.call_id,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SEND_DTMF and request.send_dtmf is not None:
            message = await self.device_client.send_dtmf(
                request.send_dtmf.target_device,
                request.send_dtmf.tones,
                request.send_dtmf.call_id,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_MICROPHONE_MUTE and request.set_microphone_mute is not None:
            message = await self.device_client.set_microphone_mute(
                request.set_microphone_mute.target_device,
                request.set_microphone_mute.muted,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_MICROPHONE_MODE and request.set_microphone_mode is not None:
            message = await self.device_client.set_microphone_mode(
                request.set_microphone_mode.target_device,
                request.set_microphone_mode.mode.value,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_VOLUME and request.set_volume is not None:
            message = await self.device_client.set_volume(
                request.set_volume.target_device,
                request.set_volume.level,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_VIDEO_MUTE and request.set_video_mute is not None:
            message = await self.device_client.set_video_mute(
                request.set_video_mute.target_device,
                request.set_video_mute.muted,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_SELFVIEW and request.set_selfview is not None:
            message = await self.device_client.set_selfview(
                request.set_selfview.target_device,
                request.set_selfview.enabled,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_CAMERA_MODE and request.set_camera_mode is not None:
            message = await self.device_client.set_camera_mode(
                request.set_camera_mode.target_device,
                request.set_camera_mode.mode.value,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_LAYOUT and request.set_layout is not None:
            message = await self.device_client.set_layout(
                request.set_layout.target_device,
                request.set_layout.layout_name,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_PRESENTATION and request.set_presentation is not None:
            message = await self.device_client.set_presentation(
                request.set_presentation.target_device,
                request.set_presentation.enabled,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SWITCH_INPUT_SOURCE and request.switch_input_source is not None:
            message = await self.device_client.switch_input_source(
                request.switch_input_source.target_device,
                request.switch_input_source.source_id,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.ASSIGN_MATRIX and request.assign_matrix is not None:
            message = await self.device_client.assign_matrix(
                request.assign_matrix.target_device,
                request.assign_matrix.output,
                request.assign_matrix.mode,
                request.assign_matrix.layout,
                request.assign_matrix.source_id,
                request.assign_matrix.remote_main,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.UNASSIGN_MATRIX and request.unassign_matrix is not None:
            message = await self.device_client.unassign_matrix(
                request.unassign_matrix.target_device,
                request.unassign_matrix.output,
                request.unassign_matrix.source_id,
                request.unassign_matrix.remote_main,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SWAP_MATRIX and request.swap_matrix is not None:
            message = await self.device_client.swap_matrix(
                request.swap_matrix.target_device,
                request.swap_matrix.output_a,
                request.swap_matrix.output_b,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_DISPLAY_MODE and request.set_display_mode is not None:
            message = await self.device_client.set_display_mode(
                request.set_display_mode.target_device,
                request.set_display_mode.mode.value,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_DISPLAY_ROLE and request.set_display_role is not None:
            message = await self.device_client.set_display_role(
                request.set_display_role.target_device,
                request.set_display_role.connector_id,
                request.set_display_role.role.value,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.ACTIVATE_CAMERA_PRESET
            and request.activate_camera_preset is not None
        ):
            message = await self.device_client.activate_camera_preset(
                request.activate_camera_preset.target_device,
                request.activate_camera_preset.preset_id,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.ADJUST_CAMERA_POSITION
            and request.adjust_camera_position is not None
        ):
            message = await self.device_client.adjust_camera_position(
                request.adjust_camera_position.target_device,
                request.adjust_camera_position.camera_id,
                request.adjust_camera_position.pan,
                request.adjust_camera_position.tilt,
                request.adjust_camera_position.zoom,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_SPEAKERTRACK and request.set_speakertrack is not None:
            message = await self.device_client.set_speakertrack(
                request.set_speakertrack.target_device,
                request.set_speakertrack.enabled,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_STANDBY and request.set_standby is not None:
            message = await self.device_client.set_standby(
                request.set_standby.target_device,
                request.set_standby.enabled,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.REBOOT and request.reboot is not None:
            message = await self.device_client.reboot(request.reboot.target_device)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.FACTORY_RESET and request.factory_reset is not None:
            message = await self.device_client.factory_reset(
                request.factory_reset.target_device,
                request.factory_reset.acknowledged,
            )
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        return ExecutionResult(
            request_id=request.request_id,
            intent=request.intent,
            execution_mode=request.execution_mode,
            status=ExecutionStatus.UNSUPPORTED,
            message=f"Intent {request.intent.value} is not enabled in the separated executor MVP.",
        )
