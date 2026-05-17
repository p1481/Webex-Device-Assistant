from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from typing import ClassVar, cast

import httpx

from assistant_app.config import AppConfig
from assistant_app.token_provider import WebexTokenProvider
from shared.contracts import (
    CameraModeStatus,
    DeviceStatusSnapshot,
    EnvironmentInfoStatus,
    OrganizationDeviceRecord,
    RoomBookingStatus,
)


@dataclass(frozen=True, slots=True)
class CameraModeObservation:
    current_mode: str | None
    effective_mode: str | None
    available_modes: tuple[str, ...]
    detail: str
    speakertrack_state: str | None
    presentertrack_status: str | None
    speakertrack_available: bool
    frames_available: bool
    presentertrack_available: bool
    closeup_active: bool
    frames_active: bool
    presentertrack_active: bool


@dataclass(frozen=True, slots=True)
class ResolvedDevice:
    id: str
    webex_device_id: str | None
    display_name: str | None
    workspace_id: str | None
    product: str | None
    place: str | None
    online: bool | None
    connection_status: str | None


@dataclass(frozen=True, slots=True)
class BookingObservation:
    booking_id: str | None
    title: str | None
    start_time: str | None
    end_time: str | None
    obtp_available: bool | None
    join_method: str | None
    join_number: str | None


class DeviceResolutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        target_device: str,
        reason: str,
        candidate_devices: list[OrganizationDeviceRecord] | None = None,
    ) -> None:
        super().__init__(message)
        self.target_device: str = target_device
        self.reason: str = reason
        self.candidate_devices: list[OrganizationDeviceRecord] = candidate_devices or []


class DeviceClient:
    DEVICE_ALIASES: ClassVar[dict[str, str]] = {
        "홈오피스": "Home Office",
        "룸바": "Room Bar",
        "룸바 기기": "Room Bar",
        "룸 바": "Room Bar",
        "room bar": "Room Bar",
    }
    MAIN_DEVICE_TYPES: ClassVar[frozenset[str]] = frozenset({"roomdesk"})
    INPUT_SOURCE_ALIASES: ClassVar[dict[str, str]] = {
        "pc": "1",
        "remote": "3",
    }
    STATUS_NAMES: ClassVar[tuple[str, ...]] = (
        "Audio.Volume",
        "Audio.VolumeMute",
        "Audio.Microphones.Mute",
        "Audio.Microphones.MusicMode",
        "Audio.Microphones.NoiseRemoval",
        "Call[*].Status",
        "Cameras.PresenterTrack.Availability",
        "Cameras.PresenterTrack.Status",
        "Cameras.SpeakerTrack.Availability",
        "Cameras.SpeakerTrack.Closeup.Status",
        "Cameras.SpeakerTrack.Frames.Availability",
        "Cameras.SpeakerTrack.Frames.Status",
        "Cameras.SpeakerTrack.State",
        "Conference.Presentation.Mode",
        "Conference.Presentation.LocalInstance[*].SendingMode",
        "Network[1].ActiveInterface",
        "Network[1].IPv4.Address",
        "Network[1].Wifi.Status",
        "Standby.State",
        "SystemUnit.Hardware.Module.SerialNumber",
        "SystemUnit.ProductPlatform",
        "SystemUnit.ProductId",
        "SystemUnit.Software.DisplayName",
        "SystemUnit.Software.Version",
        "SystemUnit.State.System",
        "SystemUnit.State.NumberOfActiveCalls",
        "Video.Selfview.Mode",
        "Video.Selfview.FullscreenMode",
        "Video.Monitors",
    )
    CAMERA_STATUS_NAMES: ClassVar[tuple[str, ...]] = (
        "Audio.Volume",
        "Audio.Microphones.MusicMode",
        "Audio.Microphones.NoiseRemoval",
        "Call[*].Status",
        "Cameras.PresenterTrack.Availability",
        "Cameras.PresenterTrack.Status",
        "Cameras.SpeakerTrack.Availability",
        "Cameras.SpeakerTrack.Closeup.Status",
        "Cameras.SpeakerTrack.Frames.Availability",
        "Cameras.SpeakerTrack.Frames.Status",
        "Cameras.SpeakerTrack.State",
        "Conference.Presentation.LocalInstance[*].SendingMode",
        "Standby.State",
        "SystemUnit.Hardware.Module.SerialNumber",
        "SystemUnit.ProductId",
        "SystemUnit.Software.Version",
        "SystemUnit.State.NumberOfActiveCalls",
        "Video.Monitors",
    )
    ENVIRONMENT_STATUS_NAMES: ClassVar[tuple[str, ...]] = (
        "RoomAnalytics.AmbientTemperature",
        "RoomAnalytics.RelativeHumidity",
        "RoomAnalytics.AmbientNoise.Level.A",
        "RoomAnalytics.PeopleCount.Current",
        "Peripherals.ConnectedDevice[*].RoomAnalytics.AirQuality.Index",
        "Peripherals.ConnectedDevice[*].RoomAnalytics.AmbientTemperature",
        "Peripherals.ConnectedDevice[*].RoomAnalytics.RelativeHumidity",
    )
    ROOM_BOOKING_STATUS_NAMES: ClassVar[tuple[str, ...]] = (
        "Bookings.Availability.Status",
        "Bookings.Availability.TimeStamp",
        "Bookings.Current.Id",
    )
    CONFIG_PATHS: ClassVar[dict[str, str]] = {
        "microphone_mode": "Audio.Input.MicrophoneMode/sources/configured/value",
        "speakertrack_frames_mode": "Cameras.SpeakerTrack.Frames.Mode/sources/configured/value",
        "display_mode": "Video.Monitors/sources/configured/value",
    }
    CONFIG_KEYS: ClassVar[dict[str, str]] = {
        "microphone_mode": "Audio.Input.MicrophoneMode",
        "speakertrack_frames_mode": "Cameras.SpeakerTrack.Frames.Mode",
        "display_mode": "Video.Monitors",
    }
    MICROPHONE_MODE_CONFIG_VALUES: ClassVar[dict[str, str]] = {
        "normal": "Wide",
        "voice-optimized": "Focused",
    }
    DISPLAY_MODE_ROLE_VALUES: ClassVar[dict[str, tuple[str, str]]] = {
        "left-video-right-video": ("First", "Second"),
        "left-video-right-presentation": ("First", "PresentationOnly"),
        "left-presentation-right-video": ("PresentationOnly", "First"),
        "both-presentation": ("PresentationOnly", "PresentationOnly"),
        # Backward-compatible aliases from the earlier Video.Monitors implementation.
        "dual": ("First", "Second"),
        "dual-presentation-only": ("First", "PresentationOnly"),
    }
    LAYOUT_STATUS_NAMES: ClassVar[tuple[str, ...]] = (
        "Video.Layout.CurrentLayout",
        "Video.Layout.LayoutFamily.Local",
    )
    DOCUMENTED_LAYOUT_CANDIDATES: ClassVar[tuple[str, ...]] = (
        "Equal",
        "Overlay",
        "Prominent",
        "Single",
        "SpeakerOnly",
    )
    LAYOUT_ALIASES: ClassVar[dict[str, str]] = {
        "equal": "Equal",
        "overlay": "Overlay",
        "prominent": "Prominent",
        "single": "Single",
        "speakeronly": "SpeakerOnly",
        "speaker only": "SpeakerOnly",
        "speaker-only": "SpeakerOnly",
    }
    CAMERA_MODE_LAYOUT_MISNAMES: ClassVar[dict[str, str]] = {
        "frames": "frames",
        "frame": "frames",
        "best overview": "best_overview",
        "best-overview": "best_overview",
        "best_overview": "best_overview",
        "speaker closeup": "speaker_closeup",
        "speaker close-up": "speaker_closeup",
        "speaker-closeup": "speaker_closeup",
        "speaker_closeup": "speaker_closeup",
    }
    CAMERA_MODE_ORDER: ClassVar[tuple[str, ...]] = (
        "Manual",
        "Dynamic",
        "BestOverview",
        "Closeup",
        "Frames",
        "GroupAndSpeaker",
    )
    CAMERA_MODE_CONFIG_VALUES: ClassVar[dict[str, str]] = {
        "Manual": "Manual",
        "Dynamic": "Dynamic",
        "BestOverview": "BestOverview",
        "Closeup": "Closeup",
        "Frames": "Frames",
        "GroupAndSpeaker": "GroupAndSpeaker",
    }
    CAMERA_MODE_CONFIG_ALIASES: ClassVar[dict[str, str]] = {
        "manual": "Manual",
        "수동": "Manual",
        "dynamic": "Dynamic",
        "동적": "Dynamic",
        "bestoverview": "BestOverview",
        "best overview": "BestOverview",
        "best_overview": "BestOverview",
        "overview": "BestOverview",
        "closeup": "Closeup",
        "close up": "Closeup",
        "speaker closeup": "Closeup",
        "speaker close up": "Closeup",
        "frames": "Frames",
        "frame": "Frames",
        "groupandspeaker": "GroupAndSpeaker",
        "group and speaker": "GroupAndSpeaker",
        "group_and_speaker": "GroupAndSpeaker",
        "group speaker": "GroupAndSpeaker",
    }

    def __init__(self, config: AppConfig, token_provider: WebexTokenProvider) -> None:
        self.config: AppConfig = config
        self.token_provider: WebexTokenProvider = token_provider

    async def get_status(self, target_device: str) -> DeviceStatusSnapshot:
        if self.config.device_mock_mode:
            return DeviceStatusSnapshot(
                target_device=target_device,
                source="mock-device-client",
                device_id="mock-device-1",
                display_name=target_device,
                workspace_id="mock-workspace-1",
                product="Room Kit",
                product_platform="RoomOS",
                place="Mock HQ",
                software_version="RoomOS 11.0",
                software_display_name="RoomOS 11.0",
                serial_number="MOCK123456",
                online=True,
                connection_status="connected",
                system_state="Available",
                volume=35,
                volume_muted=False,
                microphones_muted=False,
                call_active=False,
                active_call_count=0,
                presentation_active=False,
                presentation_mode="Off",
                selfview_mode="Off",
                selfview_fullscreen="Off",
                speakertrack_state="Inactive",
                presentertrack_status="Inactive",
                standby_state="Off",
                detail="Mock device status. Real mode uses Webex cloud xAPI over the Webex APIs.",
            )

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            device = await self._resolve_device(client, target_device)
            status_payload = await self._fetch_status(
                client, device.id, self.STATUS_NAMES
            )

        volume = self._extract_audio_volume(status_payload)
        volume_muted = self._extract_bool_status(
            self._lookup_path(status_payload, ["Audio", "VolumeMute"])
        )
        microphones_muted = self._extract_bool_status(
            self._lookup_path(status_payload, ["Audio", "Microphones", "Mute"])
        )
        active_calls = self._extract_active_call_count(status_payload)
        presentation_active = self._extract_presentation_active(status_payload)
        presentation_mode = self._extract_presentation_mode(status_payload)
        standby_state = self._extract_standby_state(status_payload)
        camera_observation = self._extract_camera_mode_observation(status_payload)

        detail_parts = [
            f"Resolved Webex deviceId={device.id}",
            f"displayName={device.display_name or target_device}",
        ]
        if standby_state is not None:
            detail_parts.append(f"standby_state={standby_state}")

        return DeviceStatusSnapshot(
            target_device=target_device,
            source="webex-cloud-xapi",
            device_id=device.id,
            display_name=device.display_name,
            workspace_id=device.workspace_id,
            product=device.product,
            product_platform=self._extract_product_platform(status_payload),
            place=device.place,
            software_version=self._extract_software_version(status_payload),
            software_display_name=self._extract_software_display_name(status_payload),
            serial_number=self._extract_serial_number(status_payload),
            online=device.online if device.online is not None else True,
            connection_status=device.connection_status,
            system_state=self._extract_system_state(status_payload),
            active_interface=self._extract_network_string(
                status_payload, ["Network", 0, "ActiveInterface"]
            ),
            ipv4_address=self._extract_network_string(
                status_payload, ["Network", 0, "IPv4", "Address"]
            ),
            wifi_status=self._extract_network_string(
                status_payload, ["Network", 0, "Wifi", "Status"]
            ),
            volume=volume,
            volume_muted=volume_muted,
            microphones_muted=microphones_muted,
            call_active=(active_calls > 0) if active_calls is not None else None,
            active_call_count=active_calls,
            presentation_active=presentation_active,
            presentation_mode=presentation_mode,
            selfview_mode=self._extract_selfview_mode(status_payload),
            selfview_fullscreen=self._extract_selfview_fullscreen(status_payload),
            speakertrack_state=camera_observation.speakertrack_state,
            presentertrack_status=camera_observation.presentertrack_status,
            standby_state=standby_state,
            detail=", ".join(detail_parts),
        )

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

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            device = await self._resolve_device(client, target_device)
            status_payload = await self._fetch_status(
                client, device.id, self.CAMERA_STATUS_NAMES
            )

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

    async def get_environment_info(self, target_device: str) -> EnvironmentInfoStatus:
        if self.config.device_mock_mode:
            return EnvironmentInfoStatus(
                target_device=target_device,
                source="mock-device-client",
                device_id="mock-device-1",
                display_name=target_device,
                temperature_celsius=22.5,
                relative_humidity_percent=45.0,
                ambient_noise_db=38.0,
                people_count=2,
                air_quality_index=72,
                detail=(
                    "Mock environment info. Real mode uses Webex cloud xAPI room analytics "
                    "with best-effort nulls for unsupported sensor values."
                ),
            )

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            device = await self._resolve_device(client, target_device)
            status_payload = await self._fetch_status_for_names(
                client,
                device.id,
                self.ENVIRONMENT_STATUS_NAMES,
            )

        temperature_celsius = self._extract_environment_temperature(status_payload)
        relative_humidity_percent = self._extract_environment_humidity(status_payload)
        ambient_noise_db = self._extract_environment_noise(status_payload)
        people_count = self._extract_environment_people_count(status_payload)
        air_quality_index = self._extract_environment_air_quality_index(status_payload)

        detail_parts = [
            f"Resolved Webex deviceId={device.id}",
            f"displayName={device.display_name or target_device}",
            "best_effort_nulls=true",
        ]

        return EnvironmentInfoStatus(
            target_device=target_device,
            source="webex-cloud-xapi",
            device_id=device.id,
            display_name=device.display_name,
            temperature_celsius=temperature_celsius,
            relative_humidity_percent=relative_humidity_percent,
            ambient_noise_db=ambient_noise_db,
            people_count=people_count,
            air_quality_index=air_quality_index,
            detail=", ".join(detail_parts),
        )

    async def get_room_booking(self, target_device: str) -> RoomBookingStatus:
        if self.config.device_mock_mode:
            return RoomBookingStatus(
                target_device=target_device,
                source="mock-device-client",
                device_id="mock-device-1",
                display_name=target_device,
                availability_status="Booked",
                availability_timestamp="2026-04-23T09:25:00Z",
                current_booking_id="mock-booking-current",
                is_booked_now=True,
                next_booking_id="mock-booking-next",
                next_meeting_title="Weekly Staff Meeting",
                next_meeting_start_time="2026-04-23T09:30:00Z",
                next_meeting_end_time="2026-04-23T10:00:00Z",
                obtp_available=True,
                obtp_join_method="webex",
                detail=(
                    "Mock room booking status. Real mode uses Bookings.Availability.* "
                    "plus Bookings.List Upcoming with best-effort nulls."
                ),
            )

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            device = await self._resolve_device(client, target_device)
            status_payload = await self._fetch_status_for_names(
                client,
                device.id,
                self.ROOM_BOOKING_STATUS_NAMES,
            )
            bookings_payload = await self._execute_command_with_client(
                client,
                device.id,
                "Bookings.List",
                {"ScheduleType": "Upcoming"},
            )

        availability_status = self._extract_booking_availability_status(status_payload)
        availability_timestamp = self._extract_booking_availability_timestamp(
            status_payload
        )
        current_booking_id = self._extract_booking_current_id(status_payload)
        next_booking = self._extract_next_booking(bookings_payload)
        next_booking_id = next_booking.booking_id if next_booking is not None else None
        next_meeting_title = next_booking.title if next_booking is not None else None
        next_meeting_start_time = (
            next_booking.start_time if next_booking is not None else None
        )
        next_meeting_end_time = (
            next_booking.end_time if next_booking is not None else None
        )
        obtp_available = (
            next_booking.obtp_available if next_booking is not None else None
        )
        obtp_join_method = (
            next_booking.join_method if next_booking is not None else None
        )

        return RoomBookingStatus(
            target_device=target_device,
            source="webex-cloud-xapi",
            device_id=device.id,
            display_name=device.display_name,
            availability_status=availability_status,
            availability_timestamp=availability_timestamp,
            current_booking_id=current_booking_id,
            is_booked_now=self._derive_is_booked_now(
                availability_status, current_booking_id
            ),
            next_booking_id=next_booking_id,
            next_meeting_title=next_meeting_title,
            next_meeting_start_time=next_meeting_start_time,
            next_meeting_end_time=next_meeting_end_time,
            obtp_available=obtp_available,
            obtp_join_method=obtp_join_method,
            detail=(
                f"Resolved Webex deviceId={device.id}, displayName={device.display_name or target_device}, "
                "best_effort_nulls=true"
            ),
        )

    async def join_obtp(self, target_device: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock OBTP join requested on {target_device} for the next Webex meeting."

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            device = await self._resolve_device(client, target_device)
            bookings_payload = await self._execute_command_with_client(
                client,
                device.id,
                "Bookings.List",
                {"ScheduleType": "Upcoming"},
            )

        next_booking = self._extract_next_joinable_booking(bookings_payload)
        if next_booking is None:
            raise RuntimeError(
                f"No confidently joinable upcoming booking was found on {device.display_name or target_device}."
            )
        if next_booking.join_method is None or next_booking.join_number is None:
            raise RuntimeError(
                f"No confidently joinable upcoming booking was found on {device.display_name or target_device}."
            )

        command_key_map = {
            "webex": "Webex.Join",
            "microsoftteams": "MicrosoftTeams.Join",
            "zoom": "Zoom.Join",
        }
        command_key = command_key_map.get(next_booking.join_method)
        if command_key is None:
            raise RuntimeError(
                f"No confidently joinable upcoming booking was found on {device.display_name or target_device}."
            )

        _ = await self._execute_command(
            device.id,
            command_key,
            self._build_meeting_join_arguments(
                next_booking.join_number,
                device.display_name or target_device,
            ),
        )
        meeting_label = next_booking.title or "the next scheduled meeting"
        return (
            f"Requested OBTP join for {meeting_label} on {device.display_name or target_device} "
            f"using {next_booking.join_method}."
        )

    async def webex_join(self, target_device: str, meeting_identifier: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock Webex join requested for {meeting_identifier} on {target_device}."

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(
            device.id,
            "Webex.Join",
            self._build_meeting_join_arguments(
                meeting_identifier,
                device.display_name or target_device,
            ),
        )
        return (
            f"Webex join requested for {meeting_identifier} on "
            f"{device.display_name or target_device}."
        )

    def _build_meeting_join_arguments(
        self,
        meeting_identifier: str,
        display_name: str | None,
    ) -> dict[str, object]:
        return {"Number": meeting_identifier}

    async def dial(self, target_device: str, address: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock dial requested to {address} on {target_device}."

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(device.id, "Dial", {"Number": address})
        return f"Dial requested to {address} on {device.display_name or target_device}."

    async def hang_up(self, target_device: str, call_id: int | None = None) -> str:
        if self.config.device_mock_mode:
            return f"Mock hang up requested for {target_device}."

        device = await self._with_resolved_device(target_device)
        arguments: dict[str, object] | None = (
            {"CallId": call_id} if call_id is not None else None
        )
        _ = await self._execute_command(device.id, "Call.Disconnect", arguments)
        return f"Hang up requested for {device.display_name or target_device}."

    async def send_dtmf(
        self,
        target_device: str,
        tones: str,
        call_id: int | None = None,
    ) -> str:
        if self.config.device_mock_mode:
            return f"Mock DTMF {tones} requested on {target_device}."

        device = await self._with_resolved_device(target_device)
        arguments: dict[str, object] = {"DTMFString": tones}
        if call_id is not None:
            arguments["CallId"] = call_id
        _ = await self._execute_command(device.id, "Call.DTMFSend", arguments)
        return f"DTMF {tones} sent on {device.display_name or target_device}."

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

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            device = await self._resolve_device(client, target_device)
            configurable_values = await self._fetch_device_configuration_enum_values(
                client,
                self._device_configuration_target_id(device),
                self.CONFIG_KEYS["microphone_mode"],
            )

        device_name = device.display_name or target_device
        exact_values_guidance = self._build_microphone_mode_guidance(
            configurable_values
        )
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
                f"Set microphone mode to voice optimized on {device_name}."
                f"{exact_values_guidance}"
            )
        raise RuntimeError(f"Unsupported microphone mode: {mode}")

    async def set_volume(self, target_device: str, level: int) -> str:
        if self.config.device_mock_mode:
            return f"Mock volume set to {level} on {target_device}."

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(device.id, "Audio.Volume.Set", {"Level": level})
        return f"Set volume to {level} on {device.display_name or target_device}."

    async def set_video_mute(self, target_device: str, muted: bool) -> str:
        if self.config.device_mock_mode:
            action = "muted" if muted else "unmuted"
            return f"Mock main video {action} on {target_device}."

        device = await self._with_resolved_device(target_device)
        command = (
            "Video.Input.MainVideo.Mute" if muted else "Video.Input.MainVideo.Unmute"
        )
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

    async def set_camera_mode(self, target_device: str, mode: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock camera mode set to {mode} on {target_device}."

        normalized_mode = mode.strip()
        config_value = self.CAMERA_MODE_CONFIG_VALUES.get(normalized_mode)
        if config_value is None:
            alias_key = " ".join(normalized_mode.casefold().replace("_", " ").split())
            canonical_mode = self.CAMERA_MODE_CONFIG_ALIASES.get(alias_key)
            if canonical_mode is None:
                canonical_mode = self.CAMERA_MODE_CONFIG_ALIASES.get(
                    alias_key.replace(" ", "")
                )
            if canonical_mode is not None:
                normalized_mode = canonical_mode
                config_value = self.CAMERA_MODE_CONFIG_VALUES.get(canonical_mode)
        if config_value is None:
            raise RuntimeError(
                "Unsupported camera mode request. Supported camera modes are: "
                "Manual, Dynamic, BestOverview, Closeup, Frames, GroupAndSpeaker."
            )

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
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

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            _ = await self._resolve_device(client, target_device)
        return self.CAMERA_MODE_ORDER

    def _normalize_supported_camera_mode_values(
        self, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        normalized_modes: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                continue
            mode = self.CAMERA_MODE_CONFIG_VALUES.get(stripped)
            if mode is None:
                normalized_key = " ".join(
                    stripped.casefold().replace("_", " ").split()
                )
                mode = self.CAMERA_MODE_CONFIG_ALIASES.get(normalized_key)
                if mode is None:
                    compact_key = normalized_key.replace(" ", "")
                    mode = self.CAMERA_MODE_CONFIG_ALIASES.get(compact_key)
            if mode is not None and mode not in normalized_modes:
                normalized_modes.append(mode)
        return tuple(normalized_modes)

    async def set_layout(self, target_device: str, layout_name: str) -> str:
        normalized_layout_name = self._normalize_layout_name(layout_name)
        if self.config.device_mock_mode:
            return f"Mock layout set to {normalized_layout_name} on {target_device}."

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
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

    async def switch_input_source(self, target_device: str, source_id: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock input source switched to {source_id} on {target_device}."

        device = await self._with_resolved_device(target_device)
        connector_id = self._resolve_input_source_id(source_id)
        try:
            _ = await self._execute_command(
                device.id,
                "Video.Input.SetMainVideoSource",
                {"ConnectorId": connector_id},
            )
        except (httpx.HTTPStatusError, RuntimeError) as exc:
            response = getattr(exc, "response", None)
            if isinstance(exc, RuntimeError) or (response is not None and response.status_code == 400):
                raise RuntimeError(
                    f"Cannot switch input source to {source_id} on "
                    f"{device.display_name or target_device}. Webex rejected "
                    f"connector {connector_id}; check that the source is connected "
                    "and supported by this device."
                ) from exc
            raise
        return (
            f"Switched input source to {source_id} on "
            f"{device.display_name or target_device}."
        )

    async def assign_matrix(
        self,
        target_device: str,
        output: str,
        mode: str,
        layout: str,
        source_id: str | None = None,
        remote_main: bool | None = None,
    ) -> str:
        if self.config.device_mock_mode:
            return (
                "Mock video matrix assign requested for "
                f"output {output} on {target_device}."
            )

        device = await self._with_resolved_device(target_device)
        arguments: dict[str, object] = {
            "Output": output,
            "Mode": mode,
            "Layout": layout,
        }
        if source_id is not None:
            arguments["SourceId"] = source_id
        if remote_main is not None:
            arguments["RemoteMain"] = "On" if remote_main else "Off"
        _ = await self._execute_command(device.id, "Video.Matrix.Assign", arguments)
        return (
            f"Assigned video matrix output {output} on "
            f"{device.display_name or target_device}."
        )

    async def unassign_matrix(
        self,
        target_device: str,
        output: str,
        source_id: str | None = None,
        remote_main: bool | None = None,
    ) -> str:
        if self.config.device_mock_mode:
            return (
                "Mock video matrix unassign requested for "
                f"output {output} on {target_device}."
            )

        device = await self._with_resolved_device(target_device)
        arguments: dict[str, object] = {"Output": output}
        if source_id is not None:
            arguments["SourceId"] = source_id
        if remote_main is not None:
            arguments["RemoteMain"] = "On" if remote_main else "Off"
        _ = await self._execute_command(device.id, "Video.Matrix.Unassign", arguments)
        return (
            f"Unassigned video matrix output {output} on "
            f"{device.display_name or target_device}."
        )

    async def swap_matrix(
        self,
        target_device: str,
        output_a: str,
        output_b: str,
    ) -> str:
        if self.config.device_mock_mode:
            return (
                "Mock video matrix swap requested for "
                f"outputs {output_a} and {output_b} on {target_device}."
            )

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(
            device.id,
            "Video.Matrix.Swap",
            {"OutputA": output_a, "OutputB": output_b},
        )
        return (
            f"Swapped video matrix outputs {output_a} and {output_b} on "
            f"{device.display_name or target_device}."
        )

    async def set_display_mode(self, target_device: str, mode: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock display mode set to {mode} on {target_device}."

        role_values = self.DISPLAY_MODE_ROLE_VALUES.get(mode)
        if role_values is None:
            raise RuntimeError(f"Unsupported display mode: {mode}")
        connector_one_role, connector_two_role = role_values

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
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

    async def set_display_role(
        self, target_device: str, connector_id: int, role: str
    ) -> str:
        if self.config.device_mock_mode:
            return f"Mock display role for connector {connector_id} set to {role} on {target_device}."

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

    async def activate_camera_preset(self, target_device: str, preset_id: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock camera preset {preset_id} activated on {target_device}."

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(
            device.id,
            "Camera.Preset.Activate",
            {"PresetId": preset_id},
        )
        return (
            f"Activated camera preset {preset_id} on "
            f"{device.display_name or target_device}."
        )

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
        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
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
        command = (
            "Cameras.SpeakerTrack.Activate"
            if enabled
            else "Cameras.SpeakerTrack.Deactivate"
        )
        _ = await self._execute_command(device.id, command, None)
        action = "Enabled" if enabled else "Disabled"
        return f"{action} SpeakerTrack on {device.display_name or target_device}."

    async def set_standby(self, target_device: str, enabled: bool) -> str:
        if self.config.device_mock_mode:
            action = "activated" if enabled else "deactivated"
            return f"Mock standby {action} on {target_device}."

        device = await self._with_resolved_device(target_device)
        command = "Standby.Activate" if enabled else "Standby.Deactivate"
        _ = await self._execute_command(device.id, command, None)
        action = "Activated" if enabled else "Deactivated"
        return f"{action} standby on {device.display_name or target_device}."

    async def reboot(self, target_device: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock reboot requested for {target_device}."

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(device.id, "SystemUnit.Boot", None)
        return f"Reboot requested for {device.display_name or target_device}."

    async def factory_reset(self, target_device: str, acknowledged: bool) -> str:
        if not acknowledged:
            raise RuntimeError("Factory reset requires explicit acknowledgement.")

        if self.config.device_mock_mode:
            return f"Mock factory reset requested for {target_device}."

        device = await self._with_resolved_device(target_device)
        _ = await self._execute_command(
            device.id,
            "SystemUnit.FactoryReset",
            {"Confirm": "Yes"},
        )
        return f"Factory reset requested for {device.display_name or target_device}."

    async def list_devices(self) -> list[OrganizationDeviceRecord]:
        if self.config.device_mock_mode:
            return self._build_candidate_devices(self._mock_device_items())

        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            items = await self._fetch_device_items(client)

        return self._build_candidate_devices(items)

    async def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self.token_provider.get_bearer_token()}"
        }

    async def _resolve_device(
        self, client: httpx.AsyncClient, target_device: str
    ) -> ResolvedDevice:
        alias_target = self.DEVICE_ALIASES.get(target_device, target_device)
        normalized_target = self._normalize_device_name(alias_target)

        normalized_items = await self._fetch_device_items(
            client,
            display_name=alias_target,
        )

        device = next(
            (
                item
                for item in normalized_items
                if item.get("displayName") == alias_target
            ),
            None,
        )
        if device is None and normalized_target:
            normalized_matches = [
                item
                for item in normalized_items
                if self._normalize_device_name(item.get("displayName"))
                == normalized_target
            ]
            if len(normalized_matches) == 1:
                device = normalized_matches[0]
            elif len(normalized_matches) > 1:
                raise DeviceResolutionError(
                    f"Multiple Webex devices match target {target_device!r}: "
                    f"{self._candidate_names(normalized_matches)}.",
                    target_device=target_device,
                    reason="ambiguous",
                    candidate_devices=self._build_candidate_devices(normalized_matches),
                )

        if device is None:
            inventory_items = await self._fetch_device_items(client)
            inventory_matches = [
                item
                for item in inventory_items
                if item.get("displayName") == alias_target
                or (
                    normalized_target
                    and self._normalize_device_name(item.get("displayName"))
                    == normalized_target
                )
            ]
            if len(inventory_matches) == 1:
                device = inventory_matches[0]
            elif len(inventory_matches) > 1:
                raise DeviceResolutionError(
                    f"Multiple Webex devices match target {target_device!r}: "
                    f"{self._candidate_names(inventory_matches)}.",
                    target_device=target_device,
                    reason="ambiguous",
                    candidate_devices=self._build_candidate_devices(inventory_matches),
                )
            else:
                raise DeviceResolutionError(
                    f"No Webex device found for target {target_device!r}.",
                    target_device=target_device,
                    reason="not_found",
                    candidate_devices=self._build_candidate_devices(inventory_items),
                )

        device_id = device.get("id")
        if not isinstance(device_id, str) or not device_id:
            raise RuntimeError("Resolved Webex device is missing an id.")

        display_name = device.get("displayName")
        webex_device_id = device.get("webexDeviceId")
        workspace_id = device.get("workspaceId")
        product = device.get("product")
        place = device.get("place")
        connection_status = device.get("connectionStatus")
        return ResolvedDevice(
            id=device_id,
            webex_device_id=(
                webex_device_id if isinstance(webex_device_id, str) else None
            ),
            display_name=display_name if isinstance(display_name, str) else None,
            workspace_id=workspace_id if isinstance(workspace_id, str) else None,
            product=product if isinstance(product, str) else None,
            place=place if isinstance(place, str) else None,
            online=(
                connection_status.lower() == "connected"
                if isinstance(connection_status, str)
                else None
            ),
            connection_status=(
                connection_status if isinstance(connection_status, str) else None
            ),
        )

    def _normalize_device_items(
        self, item_list: list[object]
    ) -> list[dict[str, object]]:
        normalized_items: list[dict[str, object]] = []
        for raw_item in item_list:
            if isinstance(raw_item, dict):
                normalized_items.append(cast(dict[str, object], raw_item))
        return normalized_items

    def _filter_device_items(
        self, items: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        return [item for item in items if self._is_supported_main_device(item)]

    async def _fetch_device_items(
        self,
        client: httpx.AsyncClient,
        display_name: str | None = None,
    ) -> list[dict[str, object]]:
        auth_headers = await self._auth_headers()
        if display_name is None:
            response = await client.get("/devices", headers=auth_headers)
        else:
            response = await client.get(
                "/devices",
                headers=auth_headers,
                params={"displayName": display_name},
            )
        _ = response.raise_for_status()
        if not response.content.strip():
            return []
        payload = cast(object, response.json())
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected Webex devices response shape.")
        payload_dict = cast(dict[str, object], payload)
        items = payload_dict.get("items")
        if not isinstance(items, list):
            raise RuntimeError("Unexpected Webex devices response shape.")
        normalized_items = self._normalize_device_items(cast(list[object], items))
        return self._filter_device_items(normalized_items)

    def _build_candidate_devices(
        self,
        items: list[dict[str, object]],
    ) -> list[OrganizationDeviceRecord]:
        candidate_devices: list[OrganizationDeviceRecord] = []
        for item in items:
            record = self._organization_device_record_from_item(item)
            if record is not None:
                candidate_devices.append(record)
        return candidate_devices

    def _organization_device_record_from_item(
        self, item: dict[str, object]
    ) -> OrganizationDeviceRecord | None:
        device_id = item.get("id")
        display_name = item.get("displayName")
        if not isinstance(device_id, str) or not isinstance(display_name, str):
            return None
        workspace_id = item.get("workspaceId")
        product = item.get("product")
        place = item.get("place")
        connection_status = item.get("connectionStatus")
        software_version = item.get("software")
        serial_number = item.get("serial")
        webex_device_id = item.get("webexDeviceId")
        return OrganizationDeviceRecord(
            device_id=device_id,
            display_name=display_name,
            workspace_id=workspace_id if isinstance(workspace_id, str) else None,
            product=product if isinstance(product, str) else None,
            device_type=self._normalize_device_type(item.get("type")),
            permissions=self._normalize_permissions(item.get("permissions")),
            webex_device_id=(
                webex_device_id if isinstance(webex_device_id, str) else None
            ),
            place=place if isinstance(place, str) else None,
            software_version=(
                software_version if isinstance(software_version, str) else None
            ),
            serial_number=serial_number if isinstance(serial_number, str) else None,
            online=(
                connection_status.lower() == "connected"
                if isinstance(connection_status, str)
                else None
            ),
            connection_status=(
                connection_status if isinstance(connection_status, str) else None
            ),
        )

    def _normalize_device_type(self, raw_value: object) -> str | None:
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip().casefold()
        return normalized or None

    def _normalize_permissions(self, raw_value: object) -> list[str] | None:
        if not isinstance(raw_value, list):
            return None
        permissions: list[str] = []
        for raw_permission in raw_value:
            if not isinstance(raw_permission, str):
                continue
            normalized = raw_permission.strip()
            if normalized and normalized not in permissions:
                permissions.append(normalized)
        return permissions

    def _permissions_include_xapi(self, permissions: list[str] | None) -> bool:
        if permissions is None:
            return True
        return any(permission.casefold() == "xapi" for permission in permissions)

    def _is_supported_main_device(self, item: dict[str, object]) -> bool:
        device_type = self._normalize_device_type(item.get("type"))
        if device_type is not None and device_type not in self.MAIN_DEVICE_TYPES:
            return False
        permissions = self._normalize_permissions(item.get("permissions"))
        if not self._permissions_include_xapi(permissions):
            return False
        return True

    def _mock_device_items(self) -> list[dict[str, object]]:
        return self._filter_device_items(
            [
                {
                    "id": "mock-device-1",
                    "webexDeviceId": "mock-webex-device-1",
                    "displayName": "Mock Room Kit",
                    "workspaceId": "mock-workspace-1",
                    "product": "Room Kit",
                    "type": "roomdesk",
                    "permissions": ["xapi"],
                    "place": "Mock HQ",
                    "software": "RoomOS 11.0",
                    "serial": "MOCK123456",
                    "connectionStatus": "connected",
                },
                {
                    "id": "mock-device-2",
                    "webexDeviceId": "mock-webex-device-2",
                    "displayName": "Board Pro",
                    "workspaceId": "mock-workspace-2",
                    "product": "Board Pro",
                    "type": "roomdesk",
                    "permissions": ["xapi"],
                    "place": "Mock Floor 7",
                    "software": "RoomOS 11.0",
                    "serial": "MOCK654321",
                    "connectionStatus": "connected",
                },
                {
                    "id": "mock-accessory-1",
                    "webexDeviceId": "mock-accessory-webex-1",
                    "displayName": "Board Pro Camera",
                    "workspaceId": "mock-workspace-2",
                    "product": "Quad Camera",
                    "type": "accessory",
                    "permissions": ["xapi"],
                    "place": "Mock Floor 7",
                    "software": "RoomOS 11.0",
                    "serial": "MOCKACC123",
                    "connectionStatus": "connected",
                },
            ]
        )

    def _candidate_names(self, items: list[dict[str, object]]) -> str:
        return ", ".join(
            display_name
            for item in items
            if isinstance((display_name := item.get("displayName")), str)
        )

    def _normalize_device_name(self, raw_name: object) -> str:
        if not isinstance(raw_name, str):
            return ""
        return " ".join(raw_name.casefold().split())

    async def _with_resolved_device(self, target_device: str) -> ResolvedDevice:
        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            return await self._resolve_device(client, target_device)

    def _device_configuration_target_id(self, device: ResolvedDevice) -> str:
        return device.webex_device_id or device.id

    async def _execute_command(
        self,
        device_id: str,
        command_key: str,
        arguments: dict[str, object] | None,
    ) -> dict[str, object]:
        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            return await self._execute_command_with_client(
                client, device_id, command_key, arguments
            )

    async def _execute_command_with_client(
        self,
        client: httpx.AsyncClient,
        device_id: str,
        command_key: str,
        arguments: dict[str, object] | None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"deviceId": device_id}
        if arguments:
            payload["arguments"] = arguments
        response = await client.post(
            f"/xapi/command/{command_key}",
            headers=await self._auth_headers(),
            json=payload,
        )
        if response.is_error:
            raise RuntimeError(self._format_webex_error_response(response))
        _ = response.raise_for_status()

        command_payload = cast(object, response.json())
        if not isinstance(command_payload, dict):
            raise RuntimeError("Unexpected Webex xAPI command response shape.")
        return cast(dict[str, object], command_payload)

    def _format_webex_error_response(self, response: httpx.Response) -> str:
        base = f"Webex API returned {response.status_code} {response.reason_phrase} for {response.request.url}."
        if not response.content:
            return base
        details: str | None = None
        try:
            body = response.json()
        except ValueError:
            body_text = response.text.strip()
            details = body_text if body_text else None
        else:
            details = self._summarize_webex_error_body(body)
        if not details:
            return base
        return f"{base} Details: {details}"

    def _summarize_webex_error_body(self, body: object) -> str | None:
        if isinstance(body, dict):
            parts: list[str] = []
            for key in ("message", "error", "reason", "description"):
                value = body.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
            errors = body.get("errors")
            if isinstance(errors, list):
                for item in errors:
                    if isinstance(item, dict):
                        for key in ("description", "message", "error"):
                            value = item.get(key)
                            if isinstance(value, str) and value.strip():
                                parts.append(value.strip())
                                break
                    elif isinstance(item, str) and item.strip():
                        parts.append(item.strip())
            if parts:
                return "; ".join(dict.fromkeys(parts))
        if isinstance(body, str) and body.strip():
            return body.strip()
        return None

    async def _patch_device_config(
        self,
        device_id: str,
        operations: list[dict[str, object]],
    ) -> list[object]:
        async with httpx.AsyncClient(
            base_url=self.config.webex_api_base, timeout=10.0
        ) as client:
            response = await client.patch(
                "/deviceConfigurations",
                headers={
                    **(await self._auth_headers()),
                    "Content-Type": "application/json-patch+json",
                },
                params={"deviceId": device_id},
                json=operations,
            )
            _ = response.raise_for_status()

        if not response.content.strip():
            return []

        payload = cast(object, response.json())
        if isinstance(payload, list):
            return cast(list[object], payload)
        if isinstance(payload, dict):
            items = cast(dict[str, object], payload).get("items")
            if isinstance(items, list):
                return cast(list[object], items)
            return [payload]
        raise RuntimeError("Unexpected Webex device configuration response shape.")

    async def _fetch_device_configuration_enum_values(
        self,
        client: httpx.AsyncClient,
        device_id: str,
        config_key: str,
    ) -> tuple[str, ...] | None:
        response = await client.get(
            "/deviceConfigurations",
            headers=await self._auth_headers(),
            params={"deviceId": device_id, "key": config_key},
        )
        _ = response.raise_for_status()
        if not response.content.strip():
            return None
        payload = cast(object, response.json())
        configuration = self._select_device_configuration(payload, config_key)
        if configuration is None:
            return None
        return self._extract_configuration_enum_values(configuration)

    def _select_device_configuration(
        self,
        payload: object,
        config_key: str,
    ) -> dict[str, object] | None:
        if isinstance(payload, dict):
            payload_dict = cast(dict[str, object], payload)
            items = payload_dict.get("items")
            if isinstance(items, list):
                for raw_item in items:
                    if not isinstance(raw_item, dict):
                        continue
                    item = cast(dict[str, object], raw_item)
                    item_key = item.get("key")
                    if item_key == config_key:
                        return item
                return None
            return payload_dict
        if isinstance(payload, list):
            for raw_item in payload:
                if not isinstance(raw_item, dict):
                    continue
                item = cast(dict[str, object], raw_item)
                item_key = item.get("key")
                if item_key == config_key:
                    return item
            if len(payload) == 1 and isinstance(payload[0], dict):
                return cast(dict[str, object], payload[0])
        return None

    def _extract_configuration_enum_values(
        self,
        configuration: dict[str, object],
    ) -> tuple[str, ...] | None:
        value_space = configuration.get("valueSpace")
        if not isinstance(value_space, dict):
            sources = configuration.get("sources")
            if isinstance(sources, dict):
                configured = cast(dict[object, object], sources).get("configured")
                if isinstance(configured, dict):
                    nested_value_space = cast(dict[object, object], configured).get(
                        "valueSpace"
                    )
                    if isinstance(nested_value_space, dict):
                        value_space = cast(dict[str, object], nested_value_space)
        if not isinstance(value_space, dict):
            return None
        enum_values = cast(dict[str, object], value_space).get("enum")
        if not isinstance(enum_values, list):
            return None

        values: list[str] = []
        for raw_value in enum_values:
            if isinstance(raw_value, str):
                if raw_value not in values:
                    values.append(raw_value)
                continue
            if not isinstance(raw_value, dict):
                continue
            raw_value_dict = cast(dict[str, object], raw_value)
            for key in ("value", "id", "name"):
                candidate = raw_value_dict.get(key)
                if isinstance(candidate, str):
                    if candidate not in values:
                        values.append(candidate)
                    break
        return tuple(values)

    async def _fetch_status(
        self,
        client: httpx.AsyncClient,
        device_id: str,
        status_names: tuple[str, ...],
    ) -> dict[str, object]:
        return await self._fetch_status_for_names(client, device_id, status_names)

    async def _fetch_status_for_names(
        self,
        client: httpx.AsyncClient,
        device_id: str,
        status_names: tuple[str, ...],
    ) -> dict[str, object]:
        merged_payload: dict[str, object] = {}
        for name_batch in self._chunked(status_names, 10):
            try:
                batch_payload = await self._fetch_status_batch(
                    client, device_id, name_batch
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 400 or len(name_batch) == 1:
                    raise
                batch_payload = await self._fetch_status_names_individually(
                    client, device_id, name_batch
                )
            self._merge_status_payload(merged_payload, batch_payload)
        return merged_payload

    async def _fetch_status_batch(
        self,
        client: httpx.AsyncClient,
        device_id: str,
        names: tuple[str, ...],
    ) -> dict[str, object]:
        params: tuple[tuple[str, str], ...] = (("deviceId", device_id),) + tuple(
            ("name", name) for name in names
        )
        response = await client.get(
            "/xapi/status",
            headers=await self._auth_headers(),
            params=params,
        )
        _ = response.raise_for_status()
        payload = cast(object, response.json())
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected Webex xAPI status response shape.")
        payload_dict = cast(dict[str, object], payload)
        result = payload_dict.get("result")
        if isinstance(result, dict):
            return cast(dict[str, object], result)
        return payload_dict

    async def _fetch_status_names_individually(
        self,
        client: httpx.AsyncClient,
        device_id: str,
        names: tuple[str, ...],
    ) -> dict[str, object]:
        merged_payload: dict[str, object] = {}
        for name in names:
            try:
                payload = await self._fetch_status_batch(client, device_id, (name,))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 400:
                    continue
                raise
            self._merge_status_payload(merged_payload, payload)
        return merged_payload

    async def _fetch_current_layout(
        self,
        client: httpx.AsyncClient,
        device_id: str,
    ) -> str | None:
        payload = await self._fetch_status_names_individually(
            client,
            device_id,
            self.LAYOUT_STATUS_NAMES,
        )
        for path in (
            ["Video", "Layout", "CurrentLayout"],
            ["Video", "Layout", "LayoutFamily", "Local"],
        ):
            layout = self._lookup_path(payload, path)
            if isinstance(layout, str) and layout.strip():
                return layout.strip()
        return None

    async def _fetch_camera_position(
        self,
        client: httpx.AsyncClient,
        device_id: str,
        camera_id: int,
    ) -> dict[str, int | None]:
        status_names = (
            f"Cameras.Camera[{camera_id}].Position.Pan",
            f"Cameras.Camera[{camera_id}].Position.Tilt",
            f"Cameras.Camera[{camera_id}].Position.Zoom",
        )
        try:
            payload = await self._fetch_status_batch(client, device_id, status_names)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            payload = await self._fetch_status_names_individually(
                client,
                device_id,
                status_names,
            )
        return {
            "pan": self._extract_int_status(
                self._lookup_path(
                    payload, ["Cameras", "Camera", camera_id - 1, "Position", "Pan"]
                ),
            ),
            "tilt": self._extract_int_status(
                self._lookup_path(
                    payload, ["Cameras", "Camera", camera_id - 1, "Position", "Tilt"]
                ),
            ),
            "zoom": self._extract_int_status(
                self._lookup_path(
                    payload, ["Cameras", "Camera", camera_id - 1, "Position", "Zoom"]
                ),
            ),
        }

    def _merge_status_payload(
        self,
        target: dict[str, object],
        source: dict[str, object],
    ) -> None:
        for key, value in source.items():
            existing = target.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                self._merge_status_payload(existing, value)
            elif isinstance(existing, list) and isinstance(value, list):
                self._merge_status_list(existing, value)
            else:
                target[key] = value

    def _merge_status_list(
        self,
        target: list[object],
        source: list[object],
    ) -> None:
        for index, value in enumerate(source):
            if index >= len(target):
                target.append(value)
                continue
            existing = target[index]
            if isinstance(existing, dict) and isinstance(value, dict):
                self._merge_status_payload(existing, value)
            elif isinstance(existing, list) and isinstance(value, list):
                self._merge_status_list(existing, value)
            else:
                target[index] = value

    def _chunked(
        self,
        items: tuple[str, ...],
        size: int,
    ) -> tuple[tuple[str, ...], ...]:
        iterator = iter(items)
        chunks: list[tuple[str, ...]] = []
        while chunk := tuple(islice(iterator, size)):
            chunks.append(chunk)
        return tuple(chunks)

    def _extract_audio_volume(self, payload: dict[str, object]) -> int | None:
        value = self._lookup_path(payload, ["Audio", "Volume"])
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _extract_int_status(self, value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("-"):
                remainder = stripped[1:]
                if remainder.isdigit():
                    return int(stripped)
            elif stripped.isdigit():
                return int(stripped)
        return None

    def _extract_bool_status(self, value: object) -> bool | None:
        if isinstance(value, bool):
            return value
        normalized = self._normalize_status_string(value)
        if normalized is None:
            return None
        if normalized in {"on", "true", "yes", "active", "muted"}:
            return True
        if normalized in {"off", "false", "no", "inactive", "unmuted"}:
            return False
        return None

    def _extract_active_call_count(self, payload: dict[str, object]) -> int | None:
        count = self._lookup_path(
            payload, ["SystemUnit", "State", "NumberOfActiveCalls"]
        )
        if isinstance(count, int):
            return count
        if isinstance(count, str) and count.isdigit():
            return int(count)

        statuses = self._lookup_path(payload, ["Call"])
        if not isinstance(statuses, list):
            return None
        status_list = cast(list[object], statuses)

        active_count = 0
        saw_status = False
        for raw_item in status_list:
            if not isinstance(raw_item, dict):
                continue
            item_dict = cast(dict[str, object], raw_item)
            status = item_dict.get("Status")
            if not isinstance(status, str):
                continue
            saw_status = True
            if status.lower() not in {"idle", "disconnected"}:
                active_count += 1

        if not saw_status:
            return None
        return active_count

    def _extract_presentation_active(self, payload: dict[str, object]) -> bool | None:
        local_instances = self._lookup_path(
            payload, ["Conference", "Presentation", "LocalInstance"]
        )
        if not isinstance(local_instances, list):
            return None
        local_instance_list = cast(list[object], local_instances)

        sending_modes: list[str] = []
        for raw_item in local_instance_list:
            if not isinstance(raw_item, dict):
                continue
            item_dict = cast(dict[str, object], raw_item)
            mode = item_dict.get("SendingMode")
            if isinstance(mode, str):
                sending_modes.append(mode.lower())

        if not sending_modes:
            return None

        return any(mode not in {"off", "notsending", "none"} for mode in sending_modes)

    def _extract_standby_state(self, payload: dict[str, object]) -> str | None:
        state = self._lookup_path(payload, ["Standby", "State"])
        return state if isinstance(state, str) else None

    def _extract_product_platform(self, payload: dict[str, object]) -> str | None:
        value = self._lookup_path(payload, ["SystemUnit", "ProductPlatform"])
        return value if isinstance(value, str) else None

    def _extract_software_display_name(self, payload: dict[str, object]) -> str | None:
        value = self._lookup_path(payload, ["SystemUnit", "Software", "DisplayName"])
        return value if isinstance(value, str) else None

    def _extract_system_state(self, payload: dict[str, object]) -> str | None:
        value = self._lookup_path(payload, ["SystemUnit", "State", "System"])
        return value if isinstance(value, str) else None

    def _extract_presentation_mode(self, payload: dict[str, object]) -> str | None:
        value = self._lookup_path(payload, ["Conference", "Presentation", "Mode"])
        return value if isinstance(value, str) else None

    def _extract_selfview_mode(self, payload: dict[str, object]) -> str | None:
        value = self._lookup_path(payload, ["Video", "Selfview", "Mode"])
        return value if isinstance(value, str) else None

    def _extract_selfview_fullscreen(self, payload: dict[str, object]) -> str | None:
        value = self._lookup_path(payload, ["Video", "Selfview", "FullscreenMode"])
        return value if isinstance(value, str) else None

    def _extract_software_version(self, payload: dict[str, object]) -> str | None:
        version = self._lookup_path(payload, ["SystemUnit", "Software", "Version"])
        return version if isinstance(version, str) else None

    def _extract_serial_number(self, payload: dict[str, object]) -> str | None:
        serial = self._lookup_path(
            payload, ["SystemUnit", "Hardware", "Module", "SerialNumber"]
        )
        return serial if isinstance(serial, str) else None

    def _extract_environment_temperature(
        self, payload: dict[str, object]
    ) -> float | None:
        primary = self._extract_numeric_status(
            self._lookup_path(payload, ["RoomAnalytics", "AmbientTemperature"])
        )
        if primary is not None:
            return primary
        return self._extract_first_peripheral_numeric_status(
            payload,
            ["RoomAnalytics", "AmbientTemperature"],
        )

    def _extract_environment_humidity(self, payload: dict[str, object]) -> float | None:
        primary = self._extract_numeric_status(
            self._lookup_path(payload, ["RoomAnalytics", "RelativeHumidity"])
        )
        if primary is not None:
            return primary
        return self._extract_first_peripheral_numeric_status(
            payload,
            ["RoomAnalytics", "RelativeHumidity"],
        )

    def _extract_environment_noise(self, payload: dict[str, object]) -> float | None:
        return self._extract_numeric_status(
            self._lookup_path(payload, ["RoomAnalytics", "AmbientNoise", "Level", "A"])
        )

    def _extract_environment_people_count(
        self, payload: dict[str, object]
    ) -> int | None:
        value = self._lookup_path(payload, ["RoomAnalytics", "PeopleCount", "Current"])
        return self._extract_int_status(value)

    def _extract_environment_air_quality_index(
        self, payload: dict[str, object]
    ) -> int | None:
        value = self._extract_first_peripheral_numeric_status(
            payload,
            ["RoomAnalytics", "AirQuality", "Index"],
        )
        if value is None:
            return None
        return int(value)

    def _extract_booking_availability_status(
        self, payload: dict[str, object]
    ) -> str | None:
        value = self._lookup_path(payload, ["Bookings", "Availability", "Status"])
        return value if isinstance(value, str) and value.strip() else None

    def _extract_booking_availability_timestamp(
        self, payload: dict[str, object]
    ) -> str | None:
        value = self._lookup_path(payload, ["Bookings", "Availability", "TimeStamp"])
        return value if isinstance(value, str) and value.strip() else None

    def _extract_booking_current_id(self, payload: dict[str, object]) -> str | None:
        value = self._lookup_path(payload, ["Bookings", "Current", "Id"])
        return value if isinstance(value, str) and value.strip() else None

    def _derive_is_booked_now(
        self, availability_status: str | None, current_booking_id: str | None
    ) -> bool | None:
        normalized = self._normalize_status_string(availability_status)
        if current_booking_id is not None:
            return True
        if normalized in {"booked", "busy", "occupied", "inmeeting"}:
            return True
        if normalized in {"available", "free", "idle"}:
            return False
        return None

    def _extract_next_joinable_booking(
        self, payload: dict[str, object]
    ) -> BookingObservation | None:
        bookings = self._extract_booking_entries(payload)
        joinable_bookings = [
            booking
            for booking in bookings
            if booking.obtp_available is True
            and booking.join_method is not None
            and booking.join_number is not None
        ]
        if not joinable_bookings:
            return None
        sorted_bookings = sorted(
            joinable_bookings,
            key=lambda booking: self._sort_key_for_timestamp(booking.start_time),
        )
        return sorted_bookings[0]

    def _extract_next_booking(
        self, payload: dict[str, object]
    ) -> BookingObservation | None:
        bookings = self._extract_booking_entries(payload)
        if not bookings:
            return None
        sorted_bookings = sorted(
            bookings,
            key=lambda booking: self._sort_key_for_timestamp(booking.start_time),
        )
        return sorted_bookings[0]

    def _extract_booking_entries(
        self, payload: dict[str, object]
    ) -> list[BookingObservation]:
        raw_items = self._lookup_path(payload, ["Bookings", "ListResult", "Booking"])
        if isinstance(raw_items, dict):
            items = [raw_items]
        elif isinstance(raw_items, list):
            items = [item for item in raw_items if isinstance(item, dict)]
        else:
            items = []

        booking_entries: list[BookingObservation] = []
        for raw_item in items:
            booking_entries.append(
                self._normalize_booking_entry(cast(dict[str, object], raw_item))
            )
        return booking_entries

    def _normalize_booking_entry(
        self, booking: dict[str, object]
    ) -> BookingObservation:
        booking_id = self._first_string_value(
            booking,
            ("Id", "BookingId", "MeetingId"),
        )
        title = self._first_string_value(
            booking,
            ("Title", "Subject", "MeetingTitle", "Agenda"),
        )
        start_time = self._first_string_value(
            booking,
            ("StartTime", "Start", "StartDateTime", "Time"),
        )
        end_time = self._first_string_value(
            booking,
            ("EndTime", "End", "EndDateTime"),
        )
        join_method = self._detect_booking_join_method(booking)
        join_number = self._extract_booking_join_number(booking, join_method)
        if join_method is None:
            obtp_available: bool | None = None
        elif join_number is None:
            obtp_available = None
        else:
            obtp_available = True
        return BookingObservation(
            booking_id=booking_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            obtp_available=obtp_available,
            join_method=join_method,
            join_number=join_number,
        )

    def _detect_booking_join_method(self, booking: dict[str, object]) -> str | None:
        explicit_service = self._first_string_value(
            booking,
            (
                "Service",
                "MeetingService",
                "JoinService",
                "JoinMethod",
                "Provider",
                "Platform",
            ),
        )
        normalized_service = self._normalize_booking_join_method_token(explicit_service)

        explicit_methods = [
            method
            for method, keys in (
                ("webex", ("WebexJoinNumber", "WebexMeetingNumber", "WebexUrl")),
                (
                    "microsoftteams",
                    (
                        "MicrosoftTeamsJoinNumber",
                        "MicrosoftTeamsUrl",
                        "TeamsMeetingNumber",
                    ),
                ),
                ("zoom", ("ZoomJoinNumber", "ZoomMeetingNumber", "ZoomUrl")),
            )
            if any(
                self._first_string_value(booking, (key,)) is not None for key in keys
            )
        ]

        methods = set(explicit_methods)
        if normalized_service is not None:
            methods.add(normalized_service)
        if len(methods) != 1:
            return None
        return next(iter(methods))

    def _normalize_booking_join_method_token(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if normalized in {"webex", "ciscowebex"}:
            return "webex"
        if normalized in {"microsoftteams", "microsoft teams", "teams"}:
            return "microsoftteams"
        if normalized == "zoom":
            return "zoom"
        return None

    def _extract_booking_join_number(
        self, booking: dict[str, object], join_method: str | None
    ) -> str | None:
        if join_method is None:
            return None
        candidate_keys_by_method: dict[str, tuple[str, ...]] = {
            "webex": (
                "WebexJoinNumber",
                "WebexMeetingNumber",
                "JoinMeetingNumber",
                "MeetingNumber",
            ),
            "microsoftteams": (
                "MicrosoftTeamsJoinNumber",
                "TeamsMeetingNumber",
                "JoinMeetingNumber",
            ),
            "zoom": (
                "ZoomJoinNumber",
                "ZoomMeetingNumber",
                "JoinMeetingNumber",
            ),
        }
        candidate = self._first_string_value(
            booking, candidate_keys_by_method[join_method]
        )
        if candidate is None:
            return None
        stripped = candidate.strip()
        return stripped or None

    def _first_string_value(
        self, payload: dict[str, object], keys: tuple[str, ...]
    ) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _sort_key_for_timestamp(self, value: str | None) -> tuple[int, str]:
        if value is None:
            return (1, "")
        normalized = value.strip()
        if not normalized:
            return (1, "")
        iso_candidate = normalized.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso_candidate)
        except ValueError:
            return (0, normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (0, parsed.astimezone(UTC).isoformat())

    def _extract_network_string(
        self,
        payload: dict[str, object],
        path: Sequence[str | int],
    ) -> str | None:
        value = self._lookup_path(payload, path)
        return value if isinstance(value, str) else None

    def _extract_numeric_status(self, value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None

    def _extract_first_peripheral_numeric_status(
        self,
        payload: dict[str, object],
        relative_path: Sequence[str],
    ) -> float | None:
        peripherals = self._lookup_path(payload, ["Peripherals", "ConnectedDevice"])
        if not isinstance(peripherals, list):
            return None
        for raw_item in cast(list[object], peripherals):
            if not isinstance(raw_item, dict):
                continue
            current: object = cast(dict[str, object], raw_item)
            for key in relative_path:
                if not isinstance(current, dict):
                    current = None
                    break
                current = cast(dict[object, object], current).get(key)
            numeric_value = self._extract_numeric_status(current)
            if numeric_value is not None:
                return numeric_value
        return None

    def _lookup_path(
        self, payload: dict[str, object], path: Sequence[str | int]
    ) -> object | None:
        current: object = payload
        for key in path:
            if isinstance(key, int):
                if not isinstance(current, list):
                    return None
                current_list = cast(list[object], current)
                if key < 0 or key >= len(current_list):
                    return None
                current = current_list[key]
                continue
            if not isinstance(current, dict):
                return None
            current_dict = cast(dict[object, object], current)
            current = current_dict.get(key)
        return current

    def _build_microphone_mode_guidance(
        self,
        configurable_values: tuple[str, ...] | None,
    ) -> str:
        if configurable_values is None:
            return ""
        return (
            " Exact configurable microphone mode values reported by Webex: "
            f"{self._format_exact_values(configurable_values)}."
        )

    @classmethod
    def _normalize_layout_name(cls, layout_name: str) -> str:
        normalized = " ".join(layout_name.strip().replace("_", " ").split())
        alias_key = normalized.lower()
        camera_mode = cls.CAMERA_MODE_LAYOUT_MISNAMES.get(alias_key)
        if camera_mode is not None:
            raise ValueError(
                f"{normalized} is a camera mode, not a video layout. "
                f"Use set_camera_mode={camera_mode} instead of Video.Layout.SetLayout."
            )
        canonical = cls.LAYOUT_ALIASES.get(alias_key)
        if canonical is not None:
            return canonical
        candidates = ", ".join(cls.DOCUMENTED_LAYOUT_CANDIDATES)
        raise ValueError(
            f"Unsupported video layout {layout_name!r}. Supported layout candidates: {candidates}."
        )

    def _build_layout_guidance(self, current_layout: str | None) -> str:
        candidates = ", ".join(self.DOCUMENTED_LAYOUT_CANDIDATES)
        if current_layout is not None:
            return (
                f" Current layout reported by Webex before the change: {current_layout}."
                " Documented candidate layouts (best-effort guidance, not "
                f"device-reported support): {candidates}."
            )
        return (
            " Current layout could not be read from Webex status."
            " Documented candidate layouts (best-effort guidance, not "
            f"device-reported support): {candidates}."
        )

    def _extract_camera_mode_observation(
        self, payload: dict[str, object]
    ) -> CameraModeObservation:
        speakertrack_available = self._status_is_available(
            self._lookup_path(payload, ["Cameras", "SpeakerTrack", "Availability"])
        )
        frames_available = self._status_is_available(
            self._lookup_path(
                payload, ["Cameras", "SpeakerTrack", "Frames", "Availability"]
            )
        )
        presentertrack_available = self._status_is_available(
            self._lookup_path(payload, ["Cameras", "PresenterTrack", "Availability"])
        )

        raw_speakertrack_state = self._lookup_path(
            payload, ["Cameras", "SpeakerTrack", "State"]
        )
        speakertrack_state = (
            raw_speakertrack_state.strip()
            if isinstance(raw_speakertrack_state, str)
            and raw_speakertrack_state.strip()
            else None
        )
        speakertrack_state_token = self._normalize_mode_token(raw_speakertrack_state)
        frames_status = self._normalize_status_string(
            self._lookup_path(payload, ["Cameras", "SpeakerTrack", "Frames", "Status"])
        )
        frames_status_token = self._normalize_mode_token(
            self._lookup_path(payload, ["Cameras", "SpeakerTrack", "Frames", "Status"])
        )
        closeup_status = self._normalize_status_string(
            self._lookup_path(payload, ["Cameras", "SpeakerTrack", "Closeup", "Status"])
        )
        closeup_status_token = self._normalize_mode_token(
            self._lookup_path(payload, ["Cameras", "SpeakerTrack", "Closeup", "Status"])
        )
        raw_presentertrack_status = self._lookup_path(
            payload, ["Cameras", "PresenterTrack", "Status"]
        )
        presentertrack_status = (
            raw_presentertrack_status.strip()
            if isinstance(raw_presentertrack_status, str)
            and raw_presentertrack_status.strip()
            else None
        )
        presentertrack_status_token = self._normalize_mode_token(
            raw_presentertrack_status
        )

        speakertrack_active = speakertrack_state_token in {
            "active",
            "on",
            "bestoverview",
        }
        frames_active = frames_status_token in {"active", "on"} or (
            speakertrack_state_token == "frames"
        )
        closeup_active = closeup_status_token in {"active", "on"} or (
            speakertrack_state_token == "closeup"
        )
        presentertrack_active = presentertrack_status_token in {"active", "on"}

        available_modes: list[str] = []
        if speakertrack_available:
            available_modes.extend(["best_overview", "speaker_closeup"])
        if speakertrack_available and frames_available:
            available_modes.append("frames")

        current_mode: str | None = None
        if presentertrack_active:
            current_mode = "presenter_track"
        elif frames_active:
            current_mode = "frames"
        elif closeup_active:
            current_mode = "speaker_closeup"
        elif speakertrack_state_token == "whiteboard":
            current_mode = "whiteboard"
        elif speakertrack_active:
            current_mode = "best_overview"

        effective_mode = current_mode

        detail_parts = [
            f"speakertrack_available={speakertrack_available}",
            f"speakertrack_state={speakertrack_state or 'unknown'}",
            f"closeup_status={closeup_status or 'unknown'}",
            f"frames_available={frames_available}",
            f"frames_status={frames_status or 'unknown'}",
            f"presentertrack_available={presentertrack_available}",
            f"presentertrack_status={presentertrack_status or 'unknown'}",
        ]
        if presentertrack_active:
            detail_parts.append(
                "PresenterTrack is active and is reported separately from the writable camera mode slice."
            )
        elif not available_modes:
            detail_parts.append(
                "No supported writable camera modes were reported by the device."
            )

        return CameraModeObservation(
            current_mode=current_mode,
            effective_mode=effective_mode,
            available_modes=tuple(available_modes),
            detail="; ".join(detail_parts),
            speakertrack_state=speakertrack_state,
            presentertrack_status=presentertrack_status,
            speakertrack_available=speakertrack_available,
            frames_available=frames_available,
            presentertrack_available=presentertrack_available,
            closeup_active=closeup_active,
            frames_active=frames_active,
            presentertrack_active=presentertrack_active,
        )

    def _validate_writable_camera_mode(
        self,
        device_name: str,
        requested_mode: str,
        observation: CameraModeObservation,
    ) -> None:
        supported_modes = ", ".join(self.CAMERA_MODE_ORDER)
        reported_modes = ", ".join(observation.available_modes) or "(none)"
        if observation.presentertrack_active:
            raise RuntimeError(
                f"Cannot set camera mode to {requested_mode} on {device_name} because PresenterTrack is active. Use PresenterTrack controls separately, then retry a supported camera mode. "
                f"Writable camera modes in this slice are: {supported_modes}."
            )
        if requested_mode not in observation.available_modes:
            raise RuntimeError(
                f"Cannot set camera mode to {requested_mode} on {device_name} because the device reports available writable camera modes: {reported_modes}. "
                f"Supported camera modes in this slice are: {supported_modes}."
            )
        if (
            requested_mode in {"best_overview", "speaker_closeup"}
            and not observation.speakertrack_available
        ):
            raise RuntimeError(
                f"Cannot set camera mode to {requested_mode} on {device_name} because SpeakerTrack is not available. "
                f"Supported camera modes in this slice are: {supported_modes}."
            )
        if requested_mode == "frames" and not observation.frames_available:
            raise RuntimeError(
                f"Cannot set camera mode to frames on {device_name} because Frames is not available. "
                f"Supported camera modes in this slice are: {supported_modes}."
            )

    def _status_is_available(self, value: object) -> bool:
        normalized = self._normalize_status_string(value)
        return normalized in {"available", "true", "yes", "on", "active"}

    def _normalize_status_string(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized.casefold()

    def _normalize_mode_token(self, value: object) -> str | None:
        normalized = self._normalize_status_string(value)
        if normalized is None:
            return None
        return normalized.replace(" ", "").replace("-", "").replace("_", "")

    def _format_exact_values(self, values: tuple[str, ...]) -> str:
        if not values:
            return "(none)"
        return ", ".join(values)

    def _parse_camera_id(self, camera_id: str) -> int:
        stripped = camera_id.strip()
        if not stripped.isdigit():
            raise RuntimeError(f"Unsupported camera id: {camera_id}")
        parsed = int(stripped)
        if parsed <= 0:
            raise RuntimeError(f"Unsupported camera id: {camera_id}")
        return parsed

    def _build_camera_position_message(
        self,
        device_name: str,
        camera_id: str,
        pan: int | None,
        tilt: int | None,
        zoom: int | None,
    ) -> str:
        adjustment_parts: list[str] = []
        if pan is not None:
            adjustment_parts.append("left" if pan > 0 else "right")
        if tilt is not None:
            adjustment_parts.append("up" if tilt > 0 else "down")
        if zoom is not None:
            adjustment_parts.append("zoom in" if zoom < 0 else "zoom out")

        if len(adjustment_parts) == 1:
            verb = "Zoomed" if adjustment_parts[0].startswith("zoom") else "Moved"
            return f"{verb} camera {camera_id} {adjustment_parts[0]} on {device_name}."

        adjustment_summary = ", ".join(
            value
            for value in (
                f"pan={pan}" if pan is not None else None,
                f"tilt={tilt}" if tilt is not None else None,
                f"zoom={zoom}" if zoom is not None else None,
            )
            if value is not None
        )
        return f"Adjusted camera {camera_id} on {device_name} ({adjustment_summary})."

    def _render_microphone_mode_label(self, mode: str) -> str:
        return mode.replace("-", " ")

    def _resolve_input_source_id(self, source_id: str) -> str:
        return self.INPUT_SOURCE_ALIASES.get(source_id.casefold(), source_id)
