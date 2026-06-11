from __future__ import annotations

from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from app.schemas.decision import SignalDecisionSnapshot
from app.schemas.signal import (
    MarketQualitySnapshot,
    MarketRegimeSnapshot,
    NoTradeFilterResult,
    RadarSignal,
    SignalConfirmationSnapshot,
    SignalEdgeSnapshot,
    SignalExecutionGateSnapshot,
    SignalExitPlanSnapshot,
    SignalInvalidationSnapshot,
    SignalTriggerSnapshot,
    StrategySetupSnapshot,
    StrategySignal,
)
from app.schemas.trade_plan import TradePlan

SignalSnapshotCarrier = TypeVar("SignalSnapshotCarrier", RadarSignal, StrategySignal)
SnapshotModel = TypeVar("SnapshotModel", bound=BaseModel)

_OPTIONAL_SNAPSHOT_FIELDS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("quality", MarketQualitySnapshot),
    ("regime", MarketRegimeSnapshot),
    ("setup", StrategySetupSnapshot),
    ("confirmation", SignalConfirmationSnapshot),
    ("trigger", SignalTriggerSnapshot),
    ("invalidation", SignalInvalidationSnapshot),
    ("exit_plan", SignalExitPlanSnapshot),
    ("trade_plan", TradePlan),
    ("edge", SignalEdgeSnapshot),
    ("no_trade_filter", NoTradeFilterResult),
    ("decision", SignalDecisionSnapshot),
    ("execution_gate", SignalExecutionGateSnapshot),
)


def normalize_signal_snapshots(signal: SignalSnapshotCarrier) -> SignalSnapshotCarrier:
    """Coerce snapshot dicts at backend boundaries before service/view access."""

    updates: dict[str, Any] = {}
    for field, model_type in _OPTIONAL_SNAPSHOT_FIELDS:
        value = getattr(signal, field, None)
        normalized = normalize_optional_snapshot(value, model_type)
        if normalized is not value:
            updates[field] = normalized
    if not updates:
        return signal
    return cast(SignalSnapshotCarrier, signal.model_copy(update=updates))


def normalize_confirmation_snapshot(value: Any) -> SignalConfirmationSnapshot | None:
    return normalize_optional_snapshot(value, SignalConfirmationSnapshot)


def normalize_optional_snapshot(
    value: Any,
    model_type: type[SnapshotModel],
) -> SnapshotModel | None:
    if value is None:
        return None
    if isinstance(value, model_type):
        return value
    if isinstance(value, dict):
        try:
            return model_type.model_validate(value)
        except (TypeError, ValueError, ValidationError):
            return None
    return None
