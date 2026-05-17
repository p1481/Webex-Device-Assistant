from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, computed_field


class ExecutionMode(StrEnum):
    SEPARATED = "separated"
    ALL_LLM = "all-llm"


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    HIGH = "high"


class ApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    APPROVED = "approved"
    REJECTED = "rejected"


class CommandPolicy(BaseModel):
    allowed_modes: list[ExecutionMode]
    risk_level: RiskLevel
    approval_state: ApprovalState
    reason: str


class PolicyDecision(BaseModel):
    selected_mode: ExecutionMode
    allowed_modes: list[ExecutionMode]
    risk_level: RiskLevel
    approval_state: ApprovalState
    reason: str

    @computed_field
    @property
    def requires_approval(self) -> bool:
        return self.approval_state == ApprovalState.REQUIRED
