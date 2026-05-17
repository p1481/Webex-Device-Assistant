"""Execution-result formatting helpers extracted from ``Orchestrator``.

Pure presentation logic. No state. Functions accept the data they need
explicitly so the orchestrator can keep thin wrapper methods.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from assistant_app.providers.base import LLMProvider
from shared.contracts import (
    ExecutionResult,
    ExecutionStatus,
    Intent,
    OrganizationDeviceRecord,
)


async def render_execution_markdown(
    provider: LLMProvider,
    execution_result: ExecutionResult,
    policy_reason: str,
    canonical_text: str,
) -> str | None:
    try:
        rendered = await provider.render_execution_reply(
            execution_result,
            policy_reason,
            canonical_text,
        )
    except Exception:
        return None
    if not isinstance(rendered, str):
        return None
    normalized = rendered.strip()
    if not normalized or normalized == canonical_text:
        return None
    return normalized


def format_device_status_detail(
    status: object,
    message: str,
    policy_reason: str,
) -> str:
    display_name = getattr(status, "display_name", None) or getattr(
        status, "target_device", "장치"
    )
    product = getattr(status, "product", None)
    device_label = f"{display_name} ({product})" if product else str(display_name)
    lines = ["**상태 상세**", f"장치: {device_label}"]
    if message:
        lines.append(f"요약: {message}")
    identity_parts = []
    for label, value in (
        ("display_name", getattr(status, "display_name", None)),
        ("product", getattr(status, "product", None)),
        ("product_platform", getattr(status, "product_platform", None)),
        ("place", getattr(status, "place", None)),
        ("software_version", getattr(status, "software_version", None)),
        ("software_display_name", getattr(status, "software_display_name", None)),
        ("serial_number", getattr(status, "serial_number", None)),
        ("device_id", getattr(status, "device_id", None)),
    ):
        if value is not None:
            identity_parts.append(f"{label}={value}")
    if identity_parts:
        lines.append("식별: " + ", ".join(identity_parts))
    connection_parts = [f"online={getattr(status, 'online', None)}"]
    for label, value in (
        ("connection", getattr(status, "connection_status", None)),
        ("system", getattr(status, "system_state", None)),
        ("standby", getattr(status, "standby_state", None)),
    ):
        if value is not None:
            connection_parts.append(f"{label}={value}")
    lines.append("연결: " + ", ".join(connection_parts))
    network_parts = []
    for label, value in (
        ("interface", getattr(status, "active_interface", None)),
        ("ipv4", getattr(status, "ipv4_address", None)),
        ("wifi", getattr(status, "wifi_status", None)),
    ):
        if value is not None:
            network_parts.append(f"{label}={value}")
    if network_parts:
        lines.append("네트워크: " + ", ".join(network_parts))
    audio_parts = []
    for label, value in (
        ("volume", getattr(status, "volume", None)),
        ("volume_muted", getattr(status, "volume_muted", None)),
        ("microphones_muted", getattr(status, "microphones_muted", None)),
    ):
        if value is not None:
            audio_parts.append(f"{label}={value}")
    if audio_parts:
        audio_line = "오디오: " + ", ".join(audio_parts)
        if "volume_muted=" in audio_line:
            audio_line += " (muted=" + str(getattr(status, "volume_muted", None)) + ")"
            audio_line += "\n오디오: volume=" + str(getattr(status, "volume", None))
            audio_line += ", muted=" + str(getattr(status, "volume_muted", None))
            if getattr(status, "microphones_muted", None) is not None:
                audio_line += ", microphones_muted=" + str(getattr(status, "microphones_muted", None))
        lines.append(audio_line)
    call_parts = []
    for label, value in (
        ("call_active", getattr(status, "call_active", None)),
        ("active_call_count", getattr(status, "active_call_count", None)),
        ("presentation_active", getattr(status, "presentation_active", None)),
        ("presentation_mode", getattr(status, "presentation_mode", None)),
    ):
        if value is not None:
            call_parts.append(f"{label}={value}")
    if call_parts:
        lines.append("통화/공유: " + ", ".join(call_parts))
    camera_parts = []
    for label, value in (
        ("selfview_mode", getattr(status, "selfview_mode", None)),
        ("selfview_fullscreen", getattr(status, "selfview_fullscreen", None)),
        ("speakertrack_state", getattr(status, "speakertrack_state", None)),
        ("presentertrack", getattr(status, "presentertrack_status", None)),
    ):
        if value is not None:
            camera_parts.append(f"{label}={value}")
    if camera_parts:
        camera_line = "카메라/화면: " + ", ".join(camera_parts)
        if getattr(status, "selfview_mode", None) is not None or getattr(status, "speakertrack_state", None) is not None:
            compat_parts = []
            if getattr(status, "selfview_mode", None) is not None:
                compat_parts.append("selfview=" + str(getattr(status, "selfview_mode", None)))
            if getattr(status, "speakertrack_state", None) is not None:
                compat_parts.append("speakertrack=" + str(getattr(status, "speakertrack_state", None)))
            if compat_parts:
                camera_line += "\n카메라/화면: " + ", ".join(compat_parts)
        lines.append(camera_line)
    detail = getattr(status, "detail", None)
    if detail is not None:
        lines.append(f"상세: {detail}")
    lines.append(f"Policy: {policy_reason}")
    return "\n".join(lines)


def format_device_list(
    devices: list[OrganizationDeviceRecord],
    policy_reason: str,
    *,
    device_capabilities: Callable[[OrganizationDeviceRecord], Any],
    capability_labels: Callable[[Any], list[str]],
) -> str:
    if not devices:
        return f"**디바이스 목록**\n조건에 맞는 디바이스가 없습니다. Policy: {policy_reason}"

    lines = [f"**디바이스 목록** ({len(devices)}대)"]
    for device in devices[:10]:
        status = (
            "online"
            if device.online
            else "offline"
            if device.online is False
            else "unknown"
        )
        product = f" ({device.product})" if device.product else ""
        place = f" [{device.place}]" if device.place else ""
        connection = (
            f", connection={device.connection_status}"
            if device.connection_status is not None
            else ""
        )
        details: list[str] = []
        if device.software_version:
            details.append(f"software={device.software_version}")
        if device.serial_number:
            details.append(f"serial={device.serial_number}")
        capabilities = capability_labels(device_capabilities(device))
        if capabilities:
            details.append("지원 기능: " + ", ".join(capabilities[:8]))
        detail_text = f"; {'; '.join(details)}" if details else ""
        lines.append(
            f"- {device.display_name}{product} - {status}{place}{connection}{detail_text}"
        )
    return "\n".join(lines) + f"\n\nPolicy: {policy_reason}"


def format_device_resolution_failure(
    execution_result: ExecutionResult,
    policy_reason: str,
) -> str:
    target_device = execution_result.failed_target_device or "requested device"
    if execution_result.resolution_error == "ambiguous":
        title = f"'{target_device}'에 해당하는 디바이스가 여러 대입니다."
    else:
        title = f"'{target_device}'와 일치하는 디바이스를 찾지 못했습니다."

    candidate_devices = execution_result.candidate_devices or []
    if not candidate_devices:
        return f"{title} Policy: {policy_reason}"

    lines = [title, "다음 디바이스 중 하나로 다시 요청해 주세요:"]
    for device in candidate_devices[:10]:
        status = (
            "online"
            if device.online
            else "offline"
            if device.online is False
            else "unknown"
        )
        product = f" ({device.product})" if device.product else ""
        lines.append(f"- {device.display_name}{product} - {status}")
    return "\n".join(lines) + f"\n\nPolicy: {policy_reason}"


def format_execution_result(
    execution_result: ExecutionResult,
    policy_reason: str,
    *,
    device_capabilities: Callable[[OrganizationDeviceRecord], Any],
    capability_labels: Callable[[Any], list[str]],
) -> str:
    if (
        execution_result.status == ExecutionStatus.SUCCESS
        and execution_result.device_status is not None
    ):
        return format_device_status_detail(
            execution_result.device_status,
            execution_result.message,
            policy_reason,
        )

    if (
        execution_result.status == ExecutionStatus.SUCCESS
        and execution_result.camera_mode_status is not None
    ):
        camera_mode_status = execution_result.camera_mode_status
        camera_metadata_parts: list[str] = []
        if camera_mode_status.display_name is not None:
            camera_metadata_parts.append(
                f"display_name={camera_mode_status.display_name}"
            )
        if camera_mode_status.device_id is not None:
            camera_metadata_parts.append(
                f"device_id={camera_mode_status.device_id}"
            )
        camera_metadata_parts.append(
            f"current_mode={camera_mode_status.current_mode}"
        )
        camera_metadata_parts.append(
            f"effective_mode={camera_mode_status.effective_mode}"
        )
        camera_metadata_parts.append(
            "available_modes=" + ",".join(camera_mode_status.available_modes)
            if camera_mode_status.available_modes
            else "available_modes="
        )
        if camera_mode_status.detail is not None:
            camera_metadata_parts.append(f"detail={camera_mode_status.detail}")
        return (
            f"{execution_result.message} "
            f"{', '.join(camera_metadata_parts)}. Policy: {policy_reason}"
        )

    if (
        execution_result.status == ExecutionStatus.SUCCESS
        and execution_result.room_booking_status is not None
    ):
        booking_status = execution_result.room_booking_status
        lines: list[str] = [execution_result.message]
        current_parts: list[str] = []
        if booking_status.is_booked_now is True:
            current_parts.append("Booked now")
        elif booking_status.is_booked_now is False:
            current_parts.append("Available now")
        if booking_status.current_booking_id is not None:
            current_parts.append(
                f"current booking ID {booking_status.current_booking_id}"
            )
        if current_parts:
            lines.append("Current: " + ", ".join(current_parts) + ".")

        next_parts: list[str] = []
        if booking_status.next_meeting_title is not None:
            next_parts.append(booking_status.next_meeting_title)
        if booking_status.next_meeting_start_time is not None:
            next_parts.append(f"starts {booking_status.next_meeting_start_time}")
        if booking_status.next_meeting_end_time is not None:
            next_parts.append(f"ends {booking_status.next_meeting_end_time}")
        if booking_status.next_booking_id is not None:
            next_parts.append(f"booking ID {booking_status.next_booking_id}")
        if next_parts:
            lines.append("Next: " + ", ".join(next_parts) + ".")

        obtp_parts: list[str] = []
        if booking_status.obtp_available is True:
            obtp_parts.append("OBTP available")
        elif booking_status.obtp_available is False:
            obtp_parts.append("OBTP not available")
        if booking_status.obtp_join_method is not None:
            obtp_parts.append(f"join method {booking_status.obtp_join_method}")
        if obtp_parts:
            lines.append("Join: " + ", ".join(obtp_parts) + ".")

        if booking_status.availability_status is not None:
            availability_line = (
                f"Availability: {booking_status.availability_status}"
            )
            if booking_status.availability_timestamp is not None:
                availability_line += f" at {booking_status.availability_timestamp}"
            lines.append(availability_line + ".")

        return " ".join(lines) + f" Policy: {policy_reason}"

    if (
        execution_result.status == ExecutionStatus.SUCCESS
        and execution_result.environment_info_status is not None
    ):
        environment_info = execution_result.environment_info_status
        metadata_parts: list[str] = []
        if environment_info.display_name is not None:
            metadata_parts.append(f"display_name={environment_info.display_name}")
        if environment_info.device_id is not None:
            metadata_parts.append(f"device_id={environment_info.device_id}")
        metadata_parts.append(
            f"temperature_celsius={environment_info.temperature_celsius}"
        )
        metadata_parts.append(
            f"relative_humidity_percent={environment_info.relative_humidity_percent}"
        )
        metadata_parts.append(
            f"ambient_noise_db={environment_info.ambient_noise_db}"
        )
        metadata_parts.append(f"people_count={environment_info.people_count}")
        metadata_parts.append(
            f"air_quality_index={environment_info.air_quality_index}"
        )
        if environment_info.detail is not None:
            metadata_parts.append(f"detail={environment_info.detail}")
        return (
            f"{execution_result.message} "
            f"{', '.join(metadata_parts)}. Policy: {policy_reason}"
        )

    if (
        execution_result.status == ExecutionStatus.SUCCESS
        and execution_result.intent == Intent.LIST_DEVICES
        and execution_result.devices is not None
    ):
        return format_device_list(
            execution_result.devices,
            policy_reason,
            device_capabilities=device_capabilities,
            capability_labels=capability_labels,
        )

    if execution_result.status == ExecutionStatus.BLOCKED:
        return f"Blocked: {execution_result.message}"

    if execution_result.status == ExecutionStatus.UNSUPPORTED:
        return f"Not enabled yet: {execution_result.message}"

    if execution_result.status == ExecutionStatus.SUCCESS:
        return f"{execution_result.message} Policy: {policy_reason}"

    if (
        execution_result.status == ExecutionStatus.ERROR
        and execution_result.failed_target_device is not None
        and execution_result.resolution_error is not None
    ):
        return format_device_resolution_failure(execution_result, policy_reason)

    return f"Execution failed: {execution_result.message}"
