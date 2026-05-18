from __future__ import annotations

import httpx

from device_executor.device_client._base import _DeviceClientBase
from shared.contracts import (
    OrganizationDeviceRecord,
)


class SystemMixin(_DeviceClientBase):
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

        async with httpx.AsyncClient(base_url=self.config.webex_api_base, timeout=10.0) as client:
            items = await self._fetch_device_items(client)

        return self._build_candidate_devices(items)
