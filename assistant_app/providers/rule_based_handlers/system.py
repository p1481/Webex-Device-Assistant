from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import (
    ActionProposal,
    FactoryResetParams,
    GetEnvironmentInfoParams,
    Intent,
    ListDevicesParams,
    OrchestrationDecision,
    RebootParams,
    SessionContext,
)

if TYPE_CHECKING:
    from assistant_app.providers.rule_based import RuleBasedProvider


def handle_early(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    """System patterns that fire near the top of ``analyze_message``."""
    _ = text
    _ = mentioned_target_device
    _ = session

    if lowered in {"/reset", "/clear-context", "reset context", "clear context"}:
        return OrchestrationDecision(
            reply_text="I cleared the session context. Ask for a device status whenever you're ready.",
            action_proposal=ActionProposal(
                intent=Intent.RESET_CONTEXT, summary="Reset conversation context."
            ),
        )

    if provider._is_list_devices_request(lowered):
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.LIST_DEVICES,
                summary="List devices in the Webex organization.",
                list_devices=ListDevicesParams(
                    limit=10,
                    online_only=("online" in lowered or "온라인" in lowered),
                ),
            )
        )

    if provider._is_get_environment_info_request(lowered):
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.GET_ENVIRONMENT_INFO,
                summary="Get the current environment sensor information.",
                get_environment_info=GetEnvironmentInfoParams(
                    target_device=target_device
                ),
            )
        )

    return None


def handle_late(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    """System patterns (reboot / factory reset) that fire near the tail of
    ``analyze_message`` — preserved at their original dispatch position so
    earlier intent checks keep priority."""
    _ = text
    _ = mentioned_target_device
    _ = session
    _ = provider

    if "reboot" in lowered:
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.REBOOT,
                summary="Reboot the target device.",
                reboot=RebootParams(target_device=target_device),
            )
        )

    if "factory reset" in lowered:
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.FACTORY_RESET,
                summary="Factory reset the target device.",
                factory_reset=FactoryResetParams(
                    target_device=target_device,
                    acknowledged=(
                        "confirm" in lowered or "yes" in lowered or "ack" in lowered
                    ),
                ),
            )
        )

    return None
