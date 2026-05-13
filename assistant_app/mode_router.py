from __future__ import annotations

from device_executor.executor import DeviceExecutor
from direct_tool_adapter.adapter import DirectToolAdapter
from shared.contracts import (
    ActionProposal,
    ExecutionRequest,
    ExecutionResult,
    Intent,
    InboundUserMessage,
    PolicyDecision,
)


class ModeRouter:
    def __init__(
        self, device_executor: DeviceExecutor, direct_tool_adapter: DirectToolAdapter
    ) -> None:
        self.device_executor: DeviceExecutor = device_executor
        self.direct_tool_adapter: DirectToolAdapter = direct_tool_adapter

    async def execute(
        self,
        message: InboundUserMessage,
        proposal: ActionProposal,
        policy_decision: PolicyDecision,
    ) -> ExecutionResult:
        execution_request = self.build_request(message, proposal, policy_decision)
        return await self.execute_request(execution_request)

    async def execute_request(
        self, execution_request: ExecutionRequest
    ) -> ExecutionResult:
        if execution_request.execution_mode.value == "separated":
            return await self.device_executor.execute(execution_request)
        return await self.direct_tool_adapter.execute(execution_request)

    def build_request(
        self,
        message: InboundUserMessage,
        proposal: ActionProposal,
        policy_decision: PolicyDecision,
    ) -> ExecutionRequest:
        target_device = message.target_device
        if proposal.intent == Intent.GET_STATUS and proposal.get_status is not None:
            target_device = proposal.get_status.target_device
        elif (
            proposal.intent == Intent.GET_ENVIRONMENT_INFO
            and proposal.get_environment_info is not None
        ):
            target_device = proposal.get_environment_info.target_device
        elif (
            proposal.intent == Intent.GET_CAMERA_MODE
            and proposal.get_camera_mode is not None
        ):
            target_device = proposal.get_camera_mode.target_device
        elif (
            proposal.intent == Intent.GET_ROOM_BOOKING
            and proposal.get_room_booking is not None
        ):
            target_device = proposal.get_room_booking.target_device
        elif proposal.intent == Intent.LIST_DEVICES:
            target_device = None
        elif proposal.intent == Intent.WEBEX_JOIN and proposal.webex_join is not None:
            target_device = proposal.webex_join.target_device
        elif proposal.intent == Intent.JOIN_OBTP and proposal.join_obtp is not None:
            target_device = proposal.join_obtp.target_device
        elif proposal.intent == Intent.DIAL and proposal.dial is not None:
            target_device = proposal.dial.target_device
        elif proposal.intent == Intent.HANG_UP and proposal.hang_up is not None:
            target_device = proposal.hang_up.target_device
        elif proposal.intent == Intent.SEND_DTMF and proposal.send_dtmf is not None:
            target_device = proposal.send_dtmf.target_device
        elif (
            proposal.intent == Intent.SET_MICROPHONE_MUTE
            and proposal.set_microphone_mute is not None
        ):
            target_device = proposal.set_microphone_mute.target_device
        elif (
            proposal.intent == Intent.SET_MICROPHONE_MODE
            and proposal.set_microphone_mode is not None
        ):
            target_device = proposal.set_microphone_mode.target_device
        elif proposal.intent == Intent.SET_VOLUME and proposal.set_volume is not None:
            target_device = proposal.set_volume.target_device
        elif (
            proposal.intent == Intent.SET_VIDEO_MUTE
            and proposal.set_video_mute is not None
        ):
            target_device = proposal.set_video_mute.target_device
        elif (
            proposal.intent == Intent.SET_SELFVIEW and proposal.set_selfview is not None
        ):
            target_device = proposal.set_selfview.target_device
        elif (
            proposal.intent == Intent.SET_CAMERA_MODE
            and proposal.set_camera_mode is not None
        ):
            target_device = proposal.set_camera_mode.target_device
        elif proposal.intent == Intent.SET_LAYOUT and proposal.set_layout is not None:
            target_device = proposal.set_layout.target_device
        elif (
            proposal.intent == Intent.SET_PRESENTATION
            and proposal.set_presentation is not None
        ):
            target_device = proposal.set_presentation.target_device
        elif (
            proposal.intent == Intent.SWITCH_INPUT_SOURCE
            and proposal.switch_input_source is not None
        ):
            target_device = proposal.switch_input_source.target_device
        elif (
            proposal.intent == Intent.ASSIGN_MATRIX
            and proposal.assign_matrix is not None
        ):
            target_device = proposal.assign_matrix.target_device
        elif (
            proposal.intent == Intent.UNASSIGN_MATRIX
            and proposal.unassign_matrix is not None
        ):
            target_device = proposal.unassign_matrix.target_device
        elif proposal.intent == Intent.SWAP_MATRIX and proposal.swap_matrix is not None:
            target_device = proposal.swap_matrix.target_device
        elif (
            proposal.intent == Intent.SET_DISPLAY_MODE
            and proposal.set_display_mode is not None
        ):
            target_device = proposal.set_display_mode.target_device
        elif (
            proposal.intent == Intent.SET_DISPLAY_ROLE
            and proposal.set_display_role is not None
        ):
            target_device = proposal.set_display_role.target_device
        elif (
            proposal.intent == Intent.ACTIVATE_CAMERA_PRESET
            and proposal.activate_camera_preset is not None
        ):
            target_device = proposal.activate_camera_preset.target_device
        elif (
            proposal.intent == Intent.ADJUST_CAMERA_POSITION
            and proposal.adjust_camera_position is not None
        ):
            target_device = proposal.adjust_camera_position.target_device
        elif (
            proposal.intent == Intent.SET_SPEAKERTRACK
            and proposal.set_speakertrack is not None
        ):
            target_device = proposal.set_speakertrack.target_device
        elif proposal.intent == Intent.SET_STANDBY and proposal.set_standby is not None:
            target_device = proposal.set_standby.target_device
        elif proposal.intent == Intent.REBOOT and proposal.reboot is not None:
            target_device = proposal.reboot.target_device
        elif (
            proposal.intent == Intent.FACTORY_RESET
            and proposal.factory_reset is not None
        ):
            target_device = proposal.factory_reset.target_device

        return ExecutionRequest(
            session_id=message.session_id,
            requested_by=message.user_id,
            requested_by_email=message.person_email,
            intent=proposal.intent,
            execution_mode=policy_decision.selected_mode,
            approval_state=policy_decision.approval_state,
            target_device=target_device,
            reason=policy_decision.reason,
            get_status=(
                proposal.get_status
                if proposal.intent == Intent.GET_STATUS
                and proposal.get_status is not None
                else None
            ),
            get_environment_info=(
                proposal.get_environment_info
                if proposal.intent == Intent.GET_ENVIRONMENT_INFO
                and proposal.get_environment_info is not None
                else None
            ),
            get_camera_mode=(
                proposal.get_camera_mode
                if proposal.intent == Intent.GET_CAMERA_MODE
                and proposal.get_camera_mode is not None
                else None
            ),
            get_room_booking=(
                proposal.get_room_booking
                if proposal.intent == Intent.GET_ROOM_BOOKING
                and proposal.get_room_booking is not None
                else None
            ),
            list_devices=(
                proposal.list_devices
                if proposal.intent == Intent.LIST_DEVICES
                else None
            ),
            webex_join=(
                proposal.webex_join
                if proposal.intent == Intent.WEBEX_JOIN
                and proposal.webex_join is not None
                else None
            ),
            join_obtp=(
                proposal.join_obtp
                if proposal.intent == Intent.JOIN_OBTP
                and proposal.join_obtp is not None
                else None
            ),
            dial=(
                proposal.dial
                if proposal.intent == Intent.DIAL and proposal.dial is not None
                else None
            ),
            hang_up=(
                proposal.hang_up
                if proposal.intent == Intent.HANG_UP and proposal.hang_up is not None
                else None
            ),
            send_dtmf=(
                proposal.send_dtmf
                if proposal.intent == Intent.SEND_DTMF
                and proposal.send_dtmf is not None
                else None
            ),
            set_microphone_mute=(
                proposal.set_microphone_mute
                if proposal.intent == Intent.SET_MICROPHONE_MUTE
                and proposal.set_microphone_mute is not None
                else None
            ),
            set_microphone_mode=(
                proposal.set_microphone_mode
                if proposal.intent == Intent.SET_MICROPHONE_MODE
                and proposal.set_microphone_mode is not None
                else None
            ),
            set_volume=(
                proposal.set_volume
                if proposal.intent == Intent.SET_VOLUME
                and proposal.set_volume is not None
                else None
            ),
            set_video_mute=(
                proposal.set_video_mute
                if proposal.intent == Intent.SET_VIDEO_MUTE
                and proposal.set_video_mute is not None
                else None
            ),
            set_selfview=(
                proposal.set_selfview
                if proposal.intent == Intent.SET_SELFVIEW
                and proposal.set_selfview is not None
                else None
            ),
            set_camera_mode=(
                proposal.set_camera_mode
                if proposal.intent == Intent.SET_CAMERA_MODE
                and proposal.set_camera_mode is not None
                else None
            ),
            set_layout=(
                proposal.set_layout
                if proposal.intent == Intent.SET_LAYOUT
                and proposal.set_layout is not None
                else None
            ),
            set_presentation=(
                proposal.set_presentation
                if proposal.intent == Intent.SET_PRESENTATION
                and proposal.set_presentation is not None
                else None
            ),
            switch_input_source=(
                proposal.switch_input_source
                if proposal.intent == Intent.SWITCH_INPUT_SOURCE
                and proposal.switch_input_source is not None
                else None
            ),
            assign_matrix=(
                proposal.assign_matrix
                if proposal.intent == Intent.ASSIGN_MATRIX
                and proposal.assign_matrix is not None
                else None
            ),
            unassign_matrix=(
                proposal.unassign_matrix
                if proposal.intent == Intent.UNASSIGN_MATRIX
                and proposal.unassign_matrix is not None
                else None
            ),
            swap_matrix=(
                proposal.swap_matrix
                if proposal.intent == Intent.SWAP_MATRIX
                and proposal.swap_matrix is not None
                else None
            ),
            set_display_mode=(
                proposal.set_display_mode
                if proposal.intent == Intent.SET_DISPLAY_MODE
                and proposal.set_display_mode is not None
                else None
            ),
            set_display_role=(
                proposal.set_display_role
                if proposal.intent == Intent.SET_DISPLAY_ROLE
                and proposal.set_display_role is not None
                else None
            ),
            activate_camera_preset=(
                proposal.activate_camera_preset
                if proposal.intent == Intent.ACTIVATE_CAMERA_PRESET
                and proposal.activate_camera_preset is not None
                else None
            ),
            adjust_camera_position=(
                proposal.adjust_camera_position
                if proposal.intent == Intent.ADJUST_CAMERA_POSITION
                and proposal.adjust_camera_position is not None
                else None
            ),
            set_speakertrack=(
                proposal.set_speakertrack
                if proposal.intent == Intent.SET_SPEAKERTRACK
                and proposal.set_speakertrack is not None
                else None
            ),
            set_standby=(
                proposal.set_standby
                if proposal.intent == Intent.SET_STANDBY
                and proposal.set_standby is not None
                else None
            ),
            reboot=(
                proposal.reboot
                if proposal.intent == Intent.REBOOT and proposal.reboot is not None
                else None
            ),
            factory_reset=(
                proposal.factory_reset
                if proposal.intent == Intent.FACTORY_RESET
                and proposal.factory_reset is not None
                else None
            ),
        )
