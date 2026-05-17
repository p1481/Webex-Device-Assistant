from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import (
    ActionProposal,
    DialParams,
    HangUpParams,
    Intent,
    JoinObtpParams,
    OrchestrationDecision,
    PendingActionProposal,
    SendDtmfParams,
    SessionContext,
    WebexJoinParams,
)

if TYPE_CHECKING:
    from assistant_app.providers.rule_based import RuleBasedProvider


def handle(
    *,
    text: str,
    lowered: str,
    target_device: str,
    mentioned_target_device: str | None,
    message_target_device: str | None,
    session: SessionContext,
    provider: RuleBasedProvider,
) -> OrchestrationDecision | None:
    """Meeting-related dispatch: OBTP join, Webex join, dial, hang up, DTMF.

    Fires after GET_CAMERA_MODE in ``analyze_message``.
    """
    _ = session

    if provider._is_join_obtp_request(lowered):
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.JOIN_OBTP,
                summary="Join the next joinable scheduled meeting from the target device.",
                join_obtp=JoinObtpParams(target_device=target_device),
            )
        )

    if provider._is_webex_join_request(lowered):
        meeting_identifier = provider._extract_webex_meeting_identifier(text)
        if meeting_identifier is not None:
            action_target_device = mentioned_target_device or message_target_device
            if action_target_device is None:
                return OrchestrationDecision(
                    pending_action=PendingActionProposal(
                        intent=Intent.WEBEX_JOIN,
                        summary="Join a Webex meeting from the target device.",
                        meeting_identifier=meeting_identifier,
                    )
                )
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.WEBEX_JOIN,
                    summary="Join a Webex meeting from the target device.",
                    webex_join=WebexJoinParams(
                        target_device=action_target_device,
                        meeting_identifier=meeting_identifier,
                    ),
                )
            )
        return OrchestrationDecision(
            pending_action=PendingActionProposal(
                intent=Intent.WEBEX_JOIN,
                summary="Join a Webex meeting from the target device.",
                target_device=mentioned_target_device,
            )
        )

    if any(
        phrase in lowered
        for phrase in {"dial ", "sip ", "call ", "join sip", "전화", "통화"}
    ):
        address = provider._extract_dial_address(text)
        if address is not None:
            if mentioned_target_device is None:
                return OrchestrationDecision(
                    pending_action=PendingActionProposal(
                        intent=Intent.DIAL,
                        summary="Dial from the target device.",
                        address=address,
                    )
                )
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.DIAL,
                    summary="Dial from the target device.",
                    dial=DialParams(target_device=target_device, address=address),
                )
            )
        return OrchestrationDecision(
            pending_action=PendingActionProposal(
                intent=Intent.DIAL,
                summary="Dial from the target device.",
                target_device=mentioned_target_device,
            )
        )

    if any(
        phrase in lowered
        for phrase in {
            "hang up",
            "hangup",
            "disconnect call",
            "drop call",
            "drop meeting",
        }
    ) or lowered.strip().endswith(" drop"):
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.HANG_UP,
                summary="Disconnect the current device call.",
                hang_up=HangUpParams(
                    target_device=target_device,
                    call_id=provider._extract_call_id(text),
                ),
            )
        )

    if "dtmf" in lowered or "send tone" in lowered or "send digits" in lowered:
        tones = provider._extract_dtmf_tones(text)
        if tones is not None:
            return OrchestrationDecision(
                action_proposal=ActionProposal(
                    intent=Intent.SEND_DTMF,
                    summary="Send DTMF tones on the current call.",
                    send_dtmf=SendDtmfParams(
                        target_device=target_device,
                        tones=tones,
                        call_id=provider._extract_call_id(text),
                    ),
                )
            )

    return None
