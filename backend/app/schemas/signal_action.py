from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.signal import RadarSignal
from app.schemas.trade import RealExecutionResult, VirtualTrade

SignalActionMode = Literal["virtual", "real"]
SignalActionKind = Literal[
    "enter_now",
    "arm_pending_entry",
    "cancel_pending_entry",
    "reconfirm_pending_entry",
]
SignalActionSeverity = Literal["blocker", "warning", "info"]


class SignalActionBlocker(BaseModel):
    code: str = Field(..., min_length=1)
    reason_code: str | None = None
    severity: SignalActionSeverity = "blocker"
    message: str | None = None
    display_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def default_reason_code(self) -> "SignalActionBlocker":
        if self.reason_code is None:
            self.reason_code = self.code
        return self


class SignalActionState(BaseModel):
    can_enter_now: bool = False
    can_arm_pending: bool = False
    can_reconfirm: bool = False
    can_cancel: bool = False
    mode: SignalActionMode = "virtual"
    environment: str = "virtual"
    primary_action: SignalActionKind | None = None
    disabled_reason_code: str | None = None
    blockers: list[SignalActionBlocker] = Field(default_factory=list)
    warnings: list[SignalActionBlocker] = Field(default_factory=list)
    accepted_trade_plan_snapshot: dict[str, Any] | None = None
    display_labels: dict[str, str] = Field(default_factory=dict)


class SignalActionRequest(BaseModel):
    kind: SignalActionKind
    mode: SignalActionMode = "virtual"
    connection_id: str | None = None


class SignalActionResponse(BaseModel):
    state: SignalActionState
    signal: RadarSignal
    virtual_trade: VirtualTrade | None = None
    real_execution: RealExecutionResult | None = None
    real_execution_result: RealExecutionResult | None = None
    pending_entry_intent: PendingEntryIntentRead | None = None
    message: str
