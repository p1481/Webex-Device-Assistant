from __future__ import annotations

from device_executor.device_client import DeviceResolutionError
from device_executor.handlers import ExecutionHandlers
from shared.contracts import (
    ApprovalState,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    Intent,
)


class DeviceExecutor:
    def __init__(self, handlers: ExecutionHandlers) -> None:
        self.handlers: ExecutionHandlers = handlers

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
                message="Approval is required before this action can run in separated mode.",
            )

        if request.intent not in {
            Intent.GET_STATUS,
            Intent.GET_ENVIRONMENT_INFO,
            Intent.GET_CAMERA_MODE,
            Intent.GET_ROOM_BOOKING,
            Intent.LIST_DEVICES,
            Intent.WEBEX_JOIN,
            Intent.JOIN_OBTP,
            Intent.DIAL,
            Intent.HANG_UP,
            Intent.SEND_DTMF,
            Intent.SET_MICROPHONE_MUTE,
            Intent.SET_MICROPHONE_MODE,
            Intent.SET_VOLUME,
            Intent.SET_VIDEO_MUTE,
            Intent.SET_SELFVIEW,
            Intent.SET_CAMERA_MODE,
            Intent.SET_LAYOUT,
            Intent.SET_PRESENTATION,
            Intent.SWITCH_INPUT_SOURCE,
            Intent.ASSIGN_MATRIX,
            Intent.UNASSIGN_MATRIX,
            Intent.SWAP_MATRIX,
            Intent.SET_DISPLAY_MODE,
            Intent.SET_DISPLAY_ROLE,
            Intent.ACTIVATE_CAMERA_PRESET,
            Intent.ADJUST_CAMERA_POSITION,
            Intent.SET_SPEAKERTRACK,
            Intent.SET_STANDBY,
            Intent.REBOOT,
            Intent.FACTORY_RESET,
        }:
            return ExecutionResult(
                request_id=request.request_id,
                intent=request.intent,
                execution_mode=request.execution_mode,
                status=ExecutionStatus.UNSUPPORTED,
                message=f"Intent {request.intent.value} is not enabled in the separated executor MVP.",
            )

        try:
            return await self.handlers.handle(request)
        except Exception as exc:
            return self._error_result(request, exc)
