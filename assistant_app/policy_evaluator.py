from __future__ import annotations

from shared.contracts import (
    ActionProposal,
    CommandPolicy,
    ExecutionMode,
    Intent,
    PolicyDecision,
)
from shared.policy_defaults import DEFAULT_COMMAND_POLICIES

from .state_store import InMemoryStateStore


class PolicyEvaluator:
    def __init__(
        self, default_mode: ExecutionMode, state_store: InMemoryStateStore | None = None
    ) -> None:
        self.default_mode: ExecutionMode = default_mode
        self.state_store = state_store

    def evaluate(
        self, proposal: ActionProposal, preferred_mode: ExecutionMode | None
    ) -> PolicyDecision:
        if proposal.intent == Intent.RESET_CONTEXT:
            return PolicyDecision(
                selected_mode=self.default_mode,
                allowed_modes=[self.default_mode],
                risk_level=DEFAULT_COMMAND_POLICIES[Intent.GET_STATUS].risk_level,
                approval_state=DEFAULT_COMMAND_POLICIES[
                    Intent.GET_STATUS
                ].approval_state,
                reason="Resetting conversation state is local to the assistant session.",
            )

        policy = self._get_policy(proposal.intent)
        if policy is None:
            return PolicyDecision(
                selected_mode=self.default_mode,
                allowed_modes=[self.default_mode],
                risk_level=DEFAULT_COMMAND_POLICIES[Intent.GET_STATUS].risk_level,
                approval_state=DEFAULT_COMMAND_POLICIES[
                    Intent.GET_STATUS
                ].approval_state,
                reason="No explicit policy found; falling back to the default execution mode.",
            )

        selected_mode = self._choose_mode(policy.allowed_modes, preferred_mode)
        return PolicyDecision(
            selected_mode=selected_mode,
            allowed_modes=policy.allowed_modes,
            risk_level=policy.risk_level,
            approval_state=policy.approval_state,
            reason=policy.reason,
        )

    def _choose_mode(
        self,
        allowed_modes: list[ExecutionMode],
        preferred_mode: ExecutionMode | None,
    ) -> ExecutionMode:
        if preferred_mode and preferred_mode in allowed_modes:
            return preferred_mode
        if self.default_mode in allowed_modes:
            return self.default_mode
        return allowed_modes[0]

    def _get_policy(self, intent: Intent) -> CommandPolicy | None:
        if self.state_store is not None:
            stored = self.state_store.get_policy(intent)
            if stored is not None:
                return stored
        return DEFAULT_COMMAND_POLICIES.get(intent)
