from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


SignalOutcomeStatus = Literal[
    "tracking",
    "entry_touched",
    "tp1",
    "tp2",
    "tp3",
    "stop_loss",
    "expired",
    "invalidated",
    "time_stop",
]
SignalOutcomeResult = Literal["win", "loss", "breakeven", "expired", "invalidated", "open"]
SameCandleResolution = Literal[
    "conservative_stop_first",
    "target_first",
    "intrabar_unknown",
    "stop_first",
    "ignore_ambiguous",
]


class SignalOutcomeTarget(BaseModel):
    label: str
    price: float
    r_multiple: float


class SignalOutcomeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    signal_id: UUID
    exchange: str
    symbol: str
    timeframe: str
    strategy: str
    direction: Literal["long", "short"]
    signal_score: float
    entry_price: float
    entry_min: float
    entry_max: float
    stop_loss: float
    targets: list[dict[str, Any]] = Field(default_factory=list)
    status: SignalOutcomeStatus
    outcome: SignalOutcomeResult
    selected_rr: float | None = None
    realized_r: float
    mfe_r: float
    mae_r: float
    bars_to_entry: int | None = None
    bars_to_outcome: int | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata", "metadata_"),
    )
