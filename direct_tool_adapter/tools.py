from __future__ import annotations

from device_executor.device_client import DeviceClient
from shared.contracts import (
    CameraModeStatus,
    DeviceStatusSnapshot,
    EnvironmentInfoStatus,
    OrganizationDeviceRecord,
    RoomBookingStatus,
)


class DirectToolSet:
    def __init__(self, device_client: DeviceClient) -> None:
        self.device_client: DeviceClient = device_client

    async def get_status(self, target_device: str) -> DeviceStatusSnapshot:
        return await self.device_client.get_status(target_device)

    async def get_environment_info(self, target_device: str) -> EnvironmentInfoStatus:
        return await self.device_client.get_environment_info(target_device)

    async def get_camera_mode(self, target_device: str) -> CameraModeStatus:
        return await self.device_client.get_camera_mode(target_device)

    async def get_room_booking(self, target_device: str) -> RoomBookingStatus:
        return await self.device_client.get_room_booking(target_device)

    async def list_devices(self) -> list[OrganizationDeviceRecord]:
        return await self.device_client.list_devices()

    async def webex_join(self, target_device: str, meeting_identifier: str) -> str:
        return await self.device_client.webex_join(target_device, meeting_identifier)

    async def join_obtp(self, target_device: str) -> str:
        return await self.device_client.join_obtp(target_device)

    async def dial(self, target_device: str, address: str) -> str:
        return await self.device_client.dial(target_device, address)

    async def hang_up(self, target_device: str, call_id: int | None = None) -> str:
        return await self.device_client.hang_up(target_device, call_id)

    async def send_dtmf(
        self,
        target_device: str,
        tones: str,
        call_id: int | None = None,
    ) -> str:
        return await self.device_client.send_dtmf(target_device, tones, call_id)

    async def set_microphone_mute(self, target_device: str, muted: bool) -> str:
        return await self.device_client.set_microphone_mute(target_device, muted)

    async def set_microphone_mode(self, target_device: str, mode: str) -> str:
        return await self.device_client.set_microphone_mode(target_device, mode)

    async def set_volume(self, target_device: str, level: int) -> str:
        return await self.device_client.set_volume(target_device, level)

    async def set_video_mute(self, target_device: str, muted: bool) -> str:
        return await self.device_client.set_video_mute(target_device, muted)

    async def set_selfview(self, target_device: str, enabled: bool) -> str:
        return await self.device_client.set_selfview(target_device, enabled)

    async def set_camera_mode(self, target_device: str, mode: str) -> str:
        return await self.device_client.set_camera_mode(target_device, mode)

    async def set_layout(self, target_device: str, layout_name: str) -> str:
        return await self.device_client.set_layout(target_device, layout_name)

    async def set_presentation(self, target_device: str, enabled: bool) -> str:
        return await self.device_client.set_presentation(target_device, enabled)

    async def switch_input_source(self, target_device: str, source_id: str) -> str:
        return await self.device_client.switch_input_source(target_device, source_id)

    async def assign_matrix(
        self,
        target_device: str,
        output: str,
        mode: str,
        layout: str,
        source_id: str | None = None,
        remote_main: bool | None = None,
    ) -> str:
        return await self.device_client.assign_matrix(
            target_device,
            output,
            mode,
            layout,
            source_id,
            remote_main,
        )

    async def unassign_matrix(
        self,
        target_device: str,
        output: str,
        source_id: str | None = None,
        remote_main: bool | None = None,
    ) -> str:
        return await self.device_client.unassign_matrix(
            target_device,
            output,
            source_id,
            remote_main,
        )

    async def swap_matrix(
        self,
        target_device: str,
        output_a: str,
        output_b: str,
    ) -> str:
        return await self.device_client.swap_matrix(target_device, output_a, output_b)

    async def set_display_mode(self, target_device: str, mode: str) -> str:
        return await self.device_client.set_display_mode(target_device, mode)

    async def set_display_role(
        self, target_device: str, connector_id: int, role: str
    ) -> str:
        return await self.device_client.set_display_role(
            target_device, connector_id, role
        )

    async def activate_camera_preset(self, target_device: str, preset_id: str) -> str:
        return await self.device_client.activate_camera_preset(target_device, preset_id)

    async def adjust_camera_position(
        self,
        target_device: str,
        camera_id: str,
        pan: int | None = None,
        tilt: int | None = None,
        zoom: int | None = None,
    ) -> str:
        return await self.device_client.adjust_camera_position(
            target_device,
            camera_id,
            pan,
            tilt,
            zoom,
        )

    async def set_speakertrack(self, target_device: str, enabled: bool) -> str:
        return await self.device_client.set_speakertrack(target_device, enabled)

    async def set_standby(self, target_device: str, enabled: bool) -> str:
        return await self.device_client.set_standby(target_device, enabled)

    async def reboot(self, target_device: str) -> str:
        return await self.device_client.reboot(target_device)

    async def factory_reset(self, target_device: str, acknowledged: bool) -> str:
        return await self.device_client.factory_reset(target_device, acknowledged)
