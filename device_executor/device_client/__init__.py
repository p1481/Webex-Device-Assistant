"""DeviceClient package — split by domain.

This package preserves backward compatibility with the original monolithic
``device_executor.device_client`` module by re-exporting all public symbols
(``DeviceClient``, ``DeviceResolutionError``, dataclasses) and ``httpx`` so
existing ``monkeypatch.setattr("device_executor.device_client.httpx.AsyncClient", ...)``
calls continue to work.
"""

from __future__ import annotations

import httpx  # re-exported for test monkeypatching

from device_executor.device_client._base import (
    BookingObservation,
    CameraModeObservation,
    DeviceResolutionError,
    ResolvedDevice,
    _DeviceClientBase,
)
from device_executor.device_client.audio import AudioMixin
from device_executor.device_client.calling import CallingMixin
from device_executor.device_client.camera import CameraMixin
from device_executor.device_client.matrix import MatrixMixin
from device_executor.device_client.status import StatusMixin
from device_executor.device_client.system import SystemMixin
from device_executor.device_client.video import VideoMixin


class DeviceClient(
    StatusMixin,
    AudioMixin,
    VideoMixin,
    CameraMixin,
    CallingMixin,
    MatrixMixin,
    SystemMixin,
    _DeviceClientBase,
):
    """Webex device control facade composed from per-domain mixins."""


__all__ = [
    "BookingObservation",
    "CameraModeObservation",
    "DeviceClient",
    "DeviceResolutionError",
    "ResolvedDevice",
    "httpx",
]
