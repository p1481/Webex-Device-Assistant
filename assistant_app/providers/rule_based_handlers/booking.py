from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import (
    ActionProposal,
    GetRoomBookingParams,
    Intent,
    OrchestrationDecision,
    SessionContext,
)

if TYPE_CHECKING:
    from assistant_app.providers.rule_based import RuleBasedProvider


def handle(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    _ = text
    _ = mentioned_target_device
    _ = session

    if provider._is_get_room_booking_request(lowered):
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.GET_ROOM_BOOKING,
                summary="Get the current room booking and OBTP status.",
                get_room_booking=GetRoomBookingParams(target_device=target_device),
            )
        )

    return None
