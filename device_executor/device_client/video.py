from __future__ import annotations

import httpx

from device_executor.device_client._base import _DeviceClientBase


class VideoMixin(_DeviceClientBase):
    async def set_video_mute(self, target_device: str, muted: bool) -> str:
        if self.config.device_mock_mode:
            action = "muted" if muted else "unmuted"
            return f"Mock main video {action} on {target_device}."

        device = await self._with_resolved_device(target_device)
        command = "Video.Input.MainVideo.Mute" if muted else "Video.Input.MainVideo.Unmute"
        _ = await self._execute_command(device.id, command, None)
        action = "Muted" if muted else "Unmuted"
        return f"{action} main video on {device.display_name or target_device}."

    async def set_selfview(self, target_device: str, enabled: bool) -> str:
        if self.config.device_mock_mode:
            action = "enabled" if enabled else "disabled"
            return f"Mock selfview {action} on {target_device}."

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(
            device.id,
            "Video.Selfview.Set",
            {"Mode": "On" if enabled else "Off"},
        )
        action = "Enabled" if enabled else "Disabled"
        return f"{action} selfview on {device.display_name or target_device}."

    async def set_layout(self, target_device: str, layout_name: str) -> str:
        normalized_layout_name = self._normalize_layout_name(layout_name)
        if self.config.device_mock_mode:
            return f"Mock layout set to {normalized_layout_name} on {target_device}."

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
            device = await self._resolve_device(client, target_device)
            current_layout = await self._fetch_current_layout(client, device.id)
        _ = await self._execute_command(
            device.id,
            "Video.Layout.SetLayout",
            {"LayoutName": normalized_layout_name},
        )
        return (
            f"Set layout to {normalized_layout_name} on {device.display_name or target_device}."
            f"{self._build_layout_guidance(current_layout)}"
        )

    async def set_presentation(self, target_device: str, enabled: bool) -> str:
        if self.config.device_mock_mode:
            action = "started" if enabled else "stopped"
            return f"Mock presentation {action} on {target_device}."

        device = await self._with_resolved_device(target_device)
        command = "Presentation.Start" if enabled else "Presentation.Stop"
        _ = await self._execute_command(device.id, command, None)
        action = "Started" if enabled else "Stopped"
        return f"{action} presentation on {device.display_name or target_device}."

    async def set_display_mode(self, target_device: str, mode: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock display mode set to {mode} on {target_device}."

        role_values = self.DISPLAY_MODE_ROLE_VALUES.get(mode)
        if role_values is None:
            raise RuntimeError(f"Unsupported display mode: {mode}")
        connector_one_role, connector_two_role = role_values

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
            device = await self._resolve_device(client, target_device)

        _ = await self._patch_device_config(
            self._device_configuration_target_id(device),
            [
                {
                    "op": "replace",
                    "path": "Video.Output.Connector[1].MonitorRole/sources/configured/value",
                    "value": connector_one_role,
                },
                {
                    "op": "replace",
                    "path": "Video.Output.Connector[2].MonitorRole/sources/configured/value",
                    "value": connector_two_role,
                },
            ],
        )
        return (
            f"Set display mode to {mode} on {device.display_name or target_device} "
            f"(connector 1: {connector_one_role}, connector 2: {connector_two_role})."
        )

    async def set_display_role(self, target_device: str, connector_id: int, role: str) -> str:
        if self.config.device_mock_mode:
            return (
                f"Mock display role for connector {connector_id} set to {role} on {target_device}."
            )

        device = await self._with_resolved_device(target_device)
        role_map = {
            "auto": "Auto",
            "first": "First",
            "second": "Second",
            "third": "Third",
            "presentation-only": "PresentationOnly",
            "recorder": "Recorder",
        }
        config_value = role_map.get(role)
        if config_value is None:
            raise RuntimeError(f"Unsupported display role: {role}")
        _ = await self._patch_device_config(
            self._device_configuration_target_id(device),
            [
                {
                    "op": "replace",
                    "path": f"Video.Output.Connector[{connector_id}].MonitorRole/sources/configured/value",
                    "value": config_value,
                }
            ],
        )
        return (
            f"Set display role for connector {connector_id} to {role} on "
            f"{device.display_name or target_device}."
        )
