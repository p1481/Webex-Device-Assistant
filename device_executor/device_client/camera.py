from __future__ import annotations

import httpx

from device_executor.device_client._base import _DeviceClientBase
from shared.contracts import (
    CameraModeStatus,
)


class CameraMixin(_DeviceClientBase):
    async def get_camera_mode(self, target_device: str) -> CameraModeStatus:
        if self.config.device_mock_mode:
            return CameraModeStatus(
                target_device=target_device,
                source="mock-device-client",
                device_id="mock-device-1",
                display_name=target_device,
                current_mode="best_overview",
                effective_mode="best_overview",
                available_modes=list(self.CAMERA_MODE_ORDER),
                detail=(
                    "Mock camera mode status. PresenterTrack is reported separately and "
                    "set_camera_mode only allows best_overview, speaker_closeup, or frames."
                ),
            )

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
            device = await self._resolve_device(client, target_device)
            status_payload = await self._fetch_status(client, device.id, self.CAMERA_STATUS_NAMES)

        observation = self._extract_camera_mode_observation(status_payload)
        return CameraModeStatus(
            target_device=target_device,
            source="webex-cloud-xapi",
            device_id=device.id,
            display_name=device.display_name,
            current_mode=observation.current_mode,
            effective_mode=observation.effective_mode,
            available_modes=list(observation.available_modes),
            detail=observation.detail,
        )

    async def set_camera_mode(self, target_device: str, mode: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock camera mode set to {mode} on {target_device}."

        normalized_mode = mode.strip()
        config_value = self.CAMERA_MODE_CONFIG_VALUES.get(normalized_mode)
        if config_value is None:
            alias_key = " ".join(normalized_mode.casefold().replace("_", " ").split())
            canonical_mode = self.CAMERA_MODE_CONFIG_ALIASES.get(alias_key)
            if canonical_mode is None:
                canonical_mode = self.CAMERA_MODE_CONFIG_ALIASES.get(alias_key.replace(" ", ""))
            if canonical_mode is not None:
                normalized_mode = canonical_mode
                config_value = self.CAMERA_MODE_CONFIG_VALUES.get(canonical_mode)
        if config_value is None:
            raise RuntimeError(
                "Unsupported camera mode request. Supported camera modes are: "
                "Manual, Dynamic, BestOverview, Closeup, Frames, GroupAndSpeaker."
            )

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
            device = await self._resolve_device(client, target_device)

        _ = await self._execute_command(
            device.id,
            "Cameras.SpeakerTrack.Set",
            {"Behavior": config_value},
        )
        device_name = device.display_name or target_device
        return (
            f"Set camera mode to {normalized_mode} on {device_name} "
            f"(Cameras.SpeakerTrack.Set Behavior: {config_value})."
        )

    async def list_supported_camera_modes(self, target_device: str) -> tuple[str, ...]:
        if self.config.device_mock_mode:
            return self.CAMERA_MODE_ORDER

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
            _ = await self._resolve_device(client, target_device)
        return self.CAMERA_MODE_ORDER

    async def activate_camera_preset(self, target_device: str, preset_id: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock camera preset {preset_id} activated on {target_device}."

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(
            device.id,
            "Camera.Preset.Activate",
            {"PresetId": preset_id},
        )
        return f"Activated camera preset {preset_id} on {device.display_name or target_device}."

    async def adjust_camera_position(
        self,
        target_device: str,
        camera_id: str,
        pan: int | None = None,
        tilt: int | None = None,
        zoom: int | None = None,
    ) -> str:
        device_name = target_device
        if self.config.device_mock_mode:
            return self._build_camera_position_message(
                device_name,
                camera_id,
                pan,
                tilt,
                zoom,
            )

        camera_id_int = self._parse_camera_id(camera_id)
        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
            device = await self._resolve_device(client, target_device)
            device_name = device.display_name or target_device
            current_position = await self._fetch_camera_position(
                client,
                device.id,
                camera_id_int,
            )

        arguments: dict[str, object] = {"CameraId": camera_id_int}
        if pan is not None:
            current_pan = current_position.get("pan")
            if current_pan is None:
                raise RuntimeError(
                    f"Cannot adjust pan for camera {camera_id_int} on {device_name} because Webex did not return the current pan position."
                )
            arguments["Pan"] = current_pan + pan
        if tilt is not None:
            current_tilt = current_position.get("tilt")
            if current_tilt is None:
                raise RuntimeError(
                    f"Cannot adjust tilt for camera {camera_id_int} on {device_name} because Webex did not return the current tilt position."
                )
            arguments["Tilt"] = current_tilt + tilt
        if zoom is not None:
            current_zoom = current_position.get("zoom")
            if current_zoom is None:
                raise RuntimeError(
                    f"Cannot adjust zoom for camera {camera_id_int} on {device_name} because Webex did not return the current zoom position."
                )
            arguments["Zoom"] = max(0, current_zoom + zoom)

        _ = await self._execute_command(device.id, "Camera.PositionSet", arguments)
        return self._build_camera_position_message(
            device_name,
            str(camera_id_int),
            pan,
            tilt,
            zoom,
        )

    async def set_speakertrack(self, target_device: str, enabled: bool) -> str:
        if self.config.device_mock_mode:
            action = "enabled" if enabled else "disabled"
            return f"Mock SpeakerTrack {action} on {target_device}."

        device = await self._with_resolved_device(target_device)
        command = "Cameras.SpeakerTrack.Activate" if enabled else "Cameras.SpeakerTrack.Deactivate"
        _ = await self._execute_command(device.id, command, None)
        action = "Enabled" if enabled else "Disabled"
        return f"{action} SpeakerTrack on {device.display_name or target_device}."
