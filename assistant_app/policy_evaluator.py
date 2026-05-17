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

        try:
            policy = self._get_policy(proposal.intent)
        except Exception as exc:  # fail-closed on evaluator error
            return self._deny_decision(
                f"Policy lookup failed for intent={proposal.intent.value!r}: {exc!r}"
            )
        if policy is None:
            # fail-closed: unknown intents must not silently fall through to
            # the default execution mode. Require explicit approval.
            return self._deny_decision(
                f"No explicit policy registered for intent={proposal.intent.value!r}; "
                "denying by default (fail-closed)."
            )

        selected_mode = self._choose_mode(policy.allowed_modes, preferred_mode)
        return PolicyDecision(
            selected_mode=selected_mode,
            allowed_modes=policy.allowed_modes,
            risk_level=policy.risk_level,
            approval_state=policy.approval_state,
            reason=policy.reason,
        )

    def _deny_decision(self, reason: str) -> PolicyDecision:
        # Force approval-required (HIGH risk) so the action cannot execute
        # without a human-in-the-loop confirmation. We still surface a
        # concrete allowed_modes list so downstream rendering does not break.
        from shared.contracts import ApprovalState, RiskLevel

        return PolicyDecision(
            selected_mode=ExecutionMode.SEPARATED,
            allowed_modes=[ExecutionMode.SEPARATED],
            risk_level=RiskLevel.HIGH,
            approval_state=ApprovalState.REQUIRED,
            reason=reason,
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
