from typing import Any, Literal

from pydantic import BaseModel, Field


DecisionReasonSource = Literal[
    "setup",
    "market_quality",
    "rr",
    "no_trade",
    "risk",
    "execution",
    "data",
]
DecisionReasonSeverity = Literal["info", "warning", "blocker"]
DecisionReasonScope = Literal["discovery", "virtual", "real", "backtest"]


class DecisionReason(BaseModel):
    code: str
    message: str
    source: DecisionReasonSource
    severity: DecisionReasonSeverity
    scope: DecisionReasonScope
    metadata: dict[str, Any] = Field(default_factory=dict)


class SignalDecisionSnapshot(BaseModel):
    setup_valid: bool
    trade_plan_valid: bool
    market_context_score: float
    signal_actionable: bool
    execution_allowed_virtual: bool | None = None
    execution_allowed_real: bool | None = None
    blockers: list[DecisionReason] = Field(default_factory=list)
    warnings: list[DecisionReason] = Field(default_factory=list)
