from __future__ import annotations

import httpx

from device_executor.device_client._base import _DeviceClientBase


class CallingMixin(_DeviceClientBase):
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

    async def join_obtp(self, target_device: str) -> str:
        if self.config.device_mock_mode:
            return f"Mock OBTP join requested on {target_device} for the next Webex meeting."

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
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
        arguments: dict[str, object] | None = {"CallId": call_id} if call_id is not None else None
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
