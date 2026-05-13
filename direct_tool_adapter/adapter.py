from __future__ import annotations

from device_executor.device_client import DeviceResolutionError
from direct_tool_adapter.tools import DirectToolSet
from shared.contracts import (
    ApprovalState,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    Intent,
)


class DirectToolAdapter:
    def __init__(self, tools: DirectToolSet) -> None:
        self.tools: DirectToolSet = tools

    def _allowed_without_approval(self, request: ExecutionRequest) -> bool:
        return request.intent in {
            Intent.GET_STATUS,
            Intent.GET_ENVIRONMENT_INFO,
            Intent.GET_CAMERA_MODE,
            Intent.GET_ROOM_BOOKING,
            Intent.LIST_DEVICES,
        }

    def _error_result(
        self,
        request: ExecutionRequest,
        exc: Exception,
    ) -> ExecutionResult:
        if isinstance(exc, DeviceResolutionError):
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.ERROR,
                approval_request_id=request.approval_request_id,
                message=str(exc),
                failed_target_device=exc.target_device,
                resolution_error=exc.reason,
                candidate_devices=exc.candidate_devices,
            )
        return ExecutionResult(
            request_id=request.request_id,
            intent=request.intent,
            execution_mode=request.execution_mode,
            status=ExecutionStatus.ERROR,
            approval_request_id=request.approval_request_id,
            message=str(exc),
        )

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if (
            request.approval_state == ApprovalState.REQUIRED
            and not self._allowed_without_approval(request)
        ):
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.BLOCKED,
                approval_request_id=request.approval_request_id,
                message="Approval is required before this action can run in all-LLM mode.",
            )

        if request.intent == Intent.GET_STATUS and request.get_status is not None:
            try:
                status_snapshot = await self.tools.get_status(
                    request.get_status.target_device
                )
            except Exception as exc:
                return self._error_result(request, exc)

            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=f"Collected status from {status_snapshot.target_device} via all-LLM mode.",
                approval_request_id=request.approval_request_id,
                device_status=status_snapshot,
            )

        if (
            request.intent == Intent.GET_ENVIRONMENT_INFO
            and request.get_environment_info is not None
        ):
            try:
                environment_info_status = await self.tools.get_environment_info(
                    request.get_environment_info.target_device
                )
            except Exception as exc:
                return self._error_result(request, exc)

            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=(
                    "Collected environment info from "
                    f"{environment_info_status.target_device} via all-LLM mode."
                ),
                approval_request_id=request.approval_request_id,
                environment_info_status=environment_info_status,
            )

        if (
            request.intent == Intent.GET_CAMERA_MODE
            and request.get_camera_mode is not None
        ):
            try:
                camera_mode_status = await self.tools.get_camera_mode(
                    request.get_camera_mode.target_device
                )
            except Exception as exc:
                return self._error_result(request, exc)

            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=(
                    f"Collected camera mode from {camera_mode_status.target_device} via all-LLM mode."
                ),
                approval_request_id=request.approval_request_id,
                camera_mode_status=camera_mode_status,
            )

        if (
            request.intent == Intent.GET_ROOM_BOOKING
            and request.get_room_booking is not None
        ):
            try:
                room_booking_status = await self.tools.get_room_booking(
                    request.get_room_booking.target_device
                )
            except Exception as exc:
                return self._error_result(request, exc)

            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=(
                    "Collected room booking info from "
                    f"{room_booking_status.target_device} via all-LLM mode."
                ),
                approval_request_id=request.approval_request_id,
                room_booking_status=room_booking_status,
            )

        if request.intent == Intent.LIST_DEVICES and request.list_devices is not None:
            try:
                devices = await self.tools.list_devices()
            except Exception as exc:
                return self._error_result(request, exc)

            if request.list_devices.online_only:
                devices = [device for device in devices if device.online is True]
            limited_devices = devices[: request.list_devices.limit]
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message="Collected organization device inventory via all-LLM mode.",
                approval_request_id=request.approval_request_id,
                devices=limited_devices,
            )

        if request.intent == Intent.WEBEX_JOIN and request.webex_join is not None:
            try:
                message = await self.tools.webex_join(
                    request.webex_join.target_device,
                    request.webex_join.meeting_identifier,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.JOIN_OBTP and request.join_obtp is not None:
            try:
                message = await self.tools.join_obtp(request.join_obtp.target_device)
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.DIAL and request.dial is not None:
            try:
                message = await self.tools.dial(
                    request.dial.target_device,
                    request.dial.address,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.HANG_UP and request.hang_up is not None:
            try:
                message = await self.tools.hang_up(
                    request.hang_up.target_device,
                    request.hang_up.call_id,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SEND_DTMF and request.send_dtmf is not None:
            try:
                message = await self.tools.send_dtmf(
                    request.send_dtmf.target_device,
                    request.send_dtmf.tones,
                    request.send_dtmf.call_id,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_MICROPHONE_MUTE
            and request.set_microphone_mute is not None
        ):
            try:
                message = await self.tools.set_microphone_mute(
                    request.set_microphone_mute.target_device,
                    request.set_microphone_mute.muted,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_MICROPHONE_MODE
            and request.set_microphone_mode is not None
        ):
            try:
                message = await self.tools.set_microphone_mode(
                    request.set_microphone_mode.target_device,
                    request.set_microphone_mode.mode.value,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_VOLUME and request.set_volume is not None:
            try:
                message = await self.tools.set_volume(
                    request.set_volume.target_device,
                    request.set_volume.level,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_VIDEO_MUTE
            and request.set_video_mute is not None
        ):
            try:
                message = await self.tools.set_video_mute(
                    request.set_video_mute.target_device,
                    request.set_video_mute.muted,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_SELFVIEW and request.set_selfview is not None:
            try:
                message = await self.tools.set_selfview(
                    request.set_selfview.target_device,
                    request.set_selfview.enabled,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_CAMERA_MODE
            and request.set_camera_mode is not None
        ):
            try:
                message = await self.tools.set_camera_mode(
                    request.set_camera_mode.target_device,
                    request.set_camera_mode.mode.value,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_LAYOUT and request.set_layout is not None:
            try:
                message = await self.tools.set_layout(
                    request.set_layout.target_device,
                    request.set_layout.layout_name,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_PRESENTATION
            and request.set_presentation is not None
        ):
            try:
                message = await self.tools.set_presentation(
                    request.set_presentation.target_device,
                    request.set_presentation.enabled,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SWITCH_INPUT_SOURCE
            and request.switch_input_source is not None
        ):
            try:
                message = await self.tools.switch_input_source(
                    request.switch_input_source.target_device,
                    request.switch_input_source.source_id,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.ASSIGN_MATRIX and request.assign_matrix is not None:
            try:
                message = await self.tools.assign_matrix(
                    request.assign_matrix.target_device,
                    request.assign_matrix.output,
                    request.assign_matrix.mode,
                    request.assign_matrix.layout,
                    request.assign_matrix.source_id,
                    request.assign_matrix.remote_main,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.UNASSIGN_MATRIX
            and request.unassign_matrix is not None
        ):
            try:
                message = await self.tools.unassign_matrix(
                    request.unassign_matrix.target_device,
                    request.unassign_matrix.output,
                    request.unassign_matrix.source_id,
                    request.unassign_matrix.remote_main,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SWAP_MATRIX and request.swap_matrix is not None:
            try:
                message = await self.tools.swap_matrix(
                    request.swap_matrix.target_device,
                    request.swap_matrix.output_a,
                    request.swap_matrix.output_b,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_DISPLAY_MODE
            and request.set_display_mode is not None
        ):
            try:
                message = await self.tools.set_display_mode(
                    request.set_display_mode.target_device,
                    request.set_display_mode.mode.value,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_DISPLAY_ROLE
            and request.set_display_role is not None
        ):
            try:
                message = await self.tools.set_display_role(
                    request.set_display_role.target_device,
                    request.set_display_role.connector_id,
                    request.set_display_role.role.value,
                )
            except Exception as exc:
                return self._error_result(request, exc)
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
            try:
                message = await self.tools.activate_camera_preset(
                    request.activate_camera_preset.target_device,
                    request.activate_camera_preset.preset_id,
                )
            except Exception as exc:
                return self._error_result(request, exc)
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
            try:
                message = await self.tools.adjust_camera_position(
                    request.adjust_camera_position.target_device,
                    request.adjust_camera_position.camera_id,
                    request.adjust_camera_position.pan,
                    request.adjust_camera_position.tilt,
                    request.adjust_camera_position.zoom,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_SPEAKERTRACK
            and request.set_speakertrack is not None
        ):
            try:
                message = await self.tools.set_speakertrack(
                    request.set_speakertrack.target_device,
                    request.set_speakertrack.enabled,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_DISPLAY_MODE
            and request.set_display_mode is not None
        ):
            try:
                message = await self.tools.set_display_mode(
                    request.set_display_mode.target_device,
                    request.set_display_mode.mode.value,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if (
            request.intent == Intent.SET_DISPLAY_ROLE
            and request.set_display_role is not None
        ):
            try:
                message = await self.tools.set_display_role(
                    request.set_display_role.target_device,
                    request.set_display_role.connector_id,
                    request.set_display_role.role.value,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.SET_STANDBY and request.set_standby is not None:
            try:
                message = await self.tools.set_standby(
                    request.set_standby.target_device,
                    request.set_standby.enabled,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.REBOOT and request.reboot is not None:
            try:
                message = await self.tools.reboot(request.reboot.target_device)
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.FACTORY_RESET and request.factory_reset is not None:
            try:
                message = await self.tools.factory_reset(
                    request.factory_reset.target_device,
                    request.factory_reset.acknowledged,
                )
            except Exception as exc:
                return self._error_result(request, exc)
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.SUCCESS,
                message=message,
                approval_request_id=request.approval_request_id,
            )

        if request.intent == Intent.CHAT:
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.UNSUPPORTED,
                message=f"Intent {request.intent.value} is not enabled in the direct tool adapter MVP.",
            )

        return ExecutionResult(
            request_id=request.request_id,
            intent=request.intent,
            execution_mode=request.execution_mode,
            status=ExecutionStatus.UNSUPPORTED,
            message=f"Intent {request.intent.value} is not enabled in the direct tool adapter MVP.",
        )
