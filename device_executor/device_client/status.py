from __future__ import annotations

import httpx

from device_executor.device_client._base import _DeviceClientBase
from shared.contracts import (
    DeviceStatusSnapshot,
    EnvironmentInfoStatus,
    RoomBookingStatus,
)


class StatusMixin(_DeviceClientBase):
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

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
            device = await self._resolve_device(client, target_device)
            status_payload = await self._fetch_status(client, device.id, self.STATUS_NAMES)

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

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
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

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
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
        availability_timestamp = self._extract_booking_availability_timestamp(status_payload)
        current_booking_id = self._extract_booking_current_id(status_payload)
        next_booking = self._extract_next_booking(bookings_payload)
        next_booking_id = next_booking.booking_id if next_booking is not None else None
        next_meeting_title = next_booking.title if next_booking is not None else None
        next_meeting_start_time = next_booking.start_time if next_booking is not None else None
        next_meeting_end_time = next_booking.end_time if next_booking is not None else None
        obtp_available = next_booking.obtp_available if next_booking is not None else None
        obtp_join_method = next_booking.join_method if next_booking is not None else None

        return RoomBookingStatus(
            target_device=target_device,
            source="webex-cloud-xapi",
            device_id=device.id,
            display_name=device.display_name,
            availability_status=availability_status,
            availability_timestamp=availability_timestamp,
            current_booking_id=current_booking_id,
            is_booked_now=self._derive_is_booked_now(availability_status, current_booking_id),
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
