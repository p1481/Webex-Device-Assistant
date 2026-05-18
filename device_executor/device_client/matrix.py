from __future__ import annotations

import httpx

from device_executor.device_client._base import _DeviceClientBase


class MatrixMixin(_DeviceClientBase):
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
            if isinstance(exc, RuntimeError) or (
                response is not None and response.status_code == 400
            ):
                raise RuntimeError(
                    f"Cannot switch input source to {source_id} on "
                    f"{device.display_name or target_device}. Webex rejected "
                    f"connector {connector_id}; check that the source is connected "
                    "and supported by this device."
                ) from exc
            raise
        return f"Switched input source to {source_id} on {device.display_name or target_device}."

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
            return f"Mock video matrix assign requested for output {output} on {target_device}."

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
        return f"Assigned video matrix output {output} on {device.display_name or target_device}."

    async def unassign_matrix(
        self,
        target_device: str,
        output: str,
        source_id: str | None = None,
        remote_main: bool | None = None,
    ) -> str:
        if self.config.device_mock_mode:
            return f"Mock video matrix unassign requested for output {output} on {target_device}."

        device = await self._with_resolved_device(target_device)
        arguments: dict[str, object] = {"Output": output}
        if source_id is not None:
            arguments["SourceId"] = source_id
        if remote_main is not None:
            arguments["RemoteMain"] = "On" if remote_main else "Off"
        _ = await self._execute_command(device.id, "Video.Matrix.Unassign", arguments)
        return f"Unassigned video matrix output {output} on {device.display_name or target_device}."

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
