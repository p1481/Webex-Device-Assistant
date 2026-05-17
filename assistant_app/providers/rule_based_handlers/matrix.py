from __future__ import annotations

from typing import TYPE_CHECKING

from shared.contracts import (
    ActionProposal,
    AssignMatrixParams,
    Intent,
    OrchestrationDecision,
    PendingActionProposal,
    SessionContext,
    SwapMatrixParams,
    SwitchInputSourceParams,
    UnassignMatrixParams,
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
    """Matrix assign/unassign/swap and source input switching dispatch."""
    _ = lowered
    _ = session

    matrix_assign = provider._extract_matrix_assign(text)
    if matrix_assign is not None:
        if mentioned_target_device is None:
            return OrchestrationDecision(
                pending_action=PendingActionProposal(
                    intent=Intent.ASSIGN_MATRIX,
                    summary="Assign a video matrix source to an output.",
                    action_proposal=ActionProposal(
                        intent=Intent.ASSIGN_MATRIX,
                        summary="Assign a video matrix source to an output.",
                        assign_matrix=AssignMatrixParams(
                            target_device="",
                            output=matrix_assign["output"],
                            mode=matrix_assign["mode"],
                            layout=matrix_assign["layout"],
                            source_id=matrix_assign["source_id"],
                            remote_main=matrix_assign["remote_main"],
                        ),
                    ),
                )
            )
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.ASSIGN_MATRIX,
                summary="Assign a video matrix source to an output.",
                assign_matrix=AssignMatrixParams(
                    target_device=target_device,
                    output=matrix_assign["output"],
                    mode=matrix_assign["mode"],
                    layout=matrix_assign["layout"],
                    source_id=matrix_assign["source_id"],
                    remote_main=matrix_assign["remote_main"],
                ),
            )
        )

    matrix_unassign = provider._extract_matrix_unassign(text)
    if matrix_unassign is not None:
        if mentioned_target_device is None:
            return OrchestrationDecision(
                pending_action=PendingActionProposal(
                    intent=Intent.UNASSIGN_MATRIX,
                    summary="Unassign a video matrix source from an output.",
                    action_proposal=ActionProposal(
                        intent=Intent.UNASSIGN_MATRIX,
                        summary="Unassign a video matrix source from an output.",
                        unassign_matrix=UnassignMatrixParams(
                            target_device="",
                            output=matrix_unassign["output"],
                            source_id=matrix_unassign["source_id"],
                            remote_main=matrix_unassign["remote_main"],
                        ),
                    ),
                )
            )
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.UNASSIGN_MATRIX,
                summary="Unassign a video matrix source from an output.",
                unassign_matrix=UnassignMatrixParams(
                    target_device=target_device,
                    output=matrix_unassign["output"],
                    source_id=matrix_unassign["source_id"],
                    remote_main=matrix_unassign["remote_main"],
                ),
            )
        )

    matrix_swap = provider._extract_matrix_swap(text)
    if matrix_swap is not None:
        if mentioned_target_device is None:
            return OrchestrationDecision(
                pending_action=PendingActionProposal(
                    intent=Intent.SWAP_MATRIX,
                    summary="Swap two video matrix outputs.",
                    action_proposal=ActionProposal(
                        intent=Intent.SWAP_MATRIX,
                        summary="Swap two video matrix outputs.",
                        swap_matrix=SwapMatrixParams(
                            target_device="",
                            output_a=matrix_swap["output_a"],
                            output_b=matrix_swap["output_b"],
                        ),
                    ),
                )
            )
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.SWAP_MATRIX,
                summary="Swap two video matrix outputs.",
                swap_matrix=SwapMatrixParams(
                    target_device=target_device,
                    output_a=matrix_swap["output_a"],
                    output_b=matrix_swap["output_b"],
                ),
            )
        )

    source_id = provider._extract_source_id(text)
    if source_id is not None:
        return OrchestrationDecision(
            action_proposal=ActionProposal(
                intent=Intent.SWITCH_INPUT_SOURCE,
                summary="Switch the main video input source.",
                switch_input_source=SwitchInputSourceParams(
                    target_device=target_device,
                    source_id=source_id,
                ),
            )
        )

    return None
