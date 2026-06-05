from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.signal import SignalStatus

PendingEntryIntentStatus = Literal[
    "pending",
    "triggered",
    "filling",
    "filled",
    "failed",
    "cancelled",
    "expired",
    "requires_reconfirmation",
]
PendingEntryIntentMode = Literal["virtual", "real"]
PendingEntryIntentSide = Literal["long", "short"]
PendingEntryViewTone = Literal["green", "red", "yellow", "blue", "purple", "neutral"]


class PendingEntryView(BaseModel):
    status_label: str
    status_tone: PendingEntryViewTone = "neutral"
    reason_code: str | None = None
    reason: str
    entry_zone: str
    current_price: Decimal | None = None


class PendingEntryIntentCreate(BaseModel):
    user_id: UUID
    signal_id: UUID
    strategy_id: UUID | None = None
    mode: PendingEntryIntentMode
    status: PendingEntryIntentStatus = "pending"

    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    side: PendingEntryIntentSide

    entry_min: Decimal = Field(..., gt=0)
    entry_max: Decimal = Field(..., gt=0)
    entry_price_policy: str = Field(..., min_length=1)
    stop_loss: Decimal = Field(..., gt=0)
    targets_snapshot: dict[str, Any] | list[Any] = Field(default_factory=list)

    accepted_trade_plan_snapshot: dict[str, Any] = Field(default_factory=dict)
    accepted_trade_plan_hash: str = Field(..., min_length=1)
    accepted_signal_status: SignalStatus
    accepted_signal_version: str | None = None
    accepted_signal_fingerprint: str | None = None

    execution_profile_snapshot: dict[str, Any] = Field(default_factory=dict)
    request_snapshot: dict[str, Any] = Field(default_factory=dict)

    idempotency_key: str = Field(..., min_length=1)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_entry_zone(self) -> "PendingEntryIntentCreate":
        if self.entry_max < self.entry_min:
            raise ValueError("entry_max must be greater than or equal to entry_min")
        return self


class PendingEntryIntentRead(PendingEntryIntentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
    triggered_at: datetime | None = None
    filled_at: datetime | None = None
    filled_trade_id: UUID | None = None
    failure_reason: str | None = None
    view: PendingEntryView | None = None
