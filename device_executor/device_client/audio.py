from __future__ import annotations

import httpx

from device_executor.device_client._base import _DeviceClientBase


class AudioMixin(_DeviceClientBase):
    async def set_microphone_mute(self, target_device: str, muted: bool) -> str:
        if self.config.device_mock_mode:
            action = "muted" if muted else "unmuted"
            return f"Mock microphones {action} on {target_device}."

        device = await self._with_resolved_device(target_device)
        command = "Audio.Microphones.Mute" if muted else "Audio.Microphones.Unmute"
        _ = await self._execute_command(device.id, command, None)
        action = "Muted" if muted else "Unmuted"
        return f"{action} microphones on {device.display_name or target_device}."

    async def set_microphone_mode(self, target_device: str, mode: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock microphone mode set to {mode} on {target_device}."

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
            device = await self._resolve_device(client, target_device)
            configurable_values = await self._fetch_device_configuration_enum_values(
                client,
                self._device_configuration_target_id(device),
                self.CONFIG_KEYS["microphone_mode"],
            )

        device_name = device.display_name or target_device
        exact_values_guidance = self._build_microphone_mode_guidance(configurable_values)
        if mode == "music-mode":
            _ = await self._execute_command(
                device.id,
                "Audio.Microphones.MusicMode.Start",
                None,
            )
            return f"Started music mode on {device_name}.{exact_values_guidance}"
        if mode == "noise-reduction":
            _ = await self._execute_command(
                device.id,
                "Audio.Microphones.NoiseRemoval.Activate",
                None,
            )
            return f"Activated noise reduction on {device_name}.{exact_values_guidance}"
        config_value = self.MICROPHONE_MODE_CONFIG_VALUES.get(mode)
        if config_value is not None:
            if configurable_values is None:
                raise RuntimeError(
                    f"Cannot set microphone mode to {self._render_microphone_mode_label(mode)} on {device_name} "
                    "because Webex did not return exact configurable microphone values."
                )
            if config_value not in configurable_values:
                raise RuntimeError(
                    f"Cannot set microphone mode to {self._render_microphone_mode_label(mode)} on {device_name} "
                    "because Webex reports configurable microphone values: "
                    f"{self._format_exact_values(configurable_values)}."
                )
        if mode == "normal":
            _ = await self._execute_command(
                device.id,
                "Audio.Microphones.NoiseRemoval.Deactivate",
                None,
            )
            _ = await self._patch_device_config(
                self._device_configuration_target_id(device),
                [
                    {
                        "op": "replace",
                        "path": self.CONFIG_PATHS["microphone_mode"],
                        "value": self.MICROPHONE_MODE_CONFIG_VALUES["normal"],
                    }
                ],
            )
            return f"Set microphone mode to normal on {device_name}.{exact_values_guidance}"
        if mode == "voice-optimized":
            _ = await self._patch_device_config(
                self._device_configuration_target_id(device),
                [
                    {
                        "op": "replace",
                        "path": self.CONFIG_PATHS["microphone_mode"],
                        "value": self.MICROPHONE_MODE_CONFIG_VALUES["voice-optimized"],
                    }
                ],
            )
            return (
                f"Set microphone mode to voice optimized on {device_name}.{exact_values_guidance}"
            )
        raise RuntimeError(f"Unsupported microphone mode: {mode}")

    async def set_volume(self, target_device: str, level: int) -> str:
        if self.config.device_mock_mode:
            return f"Mock volume set to {level} on {target_device}."

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(device.id, "Audio.Volume.Set", {"Level": level})
        return f"Set volume to {level} on {device.display_name or target_device}."
