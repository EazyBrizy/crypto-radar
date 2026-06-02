from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TradePlanVersion = Literal["v1"]


class TradePlanEntry(BaseModel):
    price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    source: str = "legacy_fields"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradePlanTarget(BaseModel):
    label: str
    price: float | None = None
    r_multiple: float | None = Field(default=None, ge=0)
    action: str | None = None
    close_percent: float | str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradePlanInvalidation(BaseModel):
    price: float | None = None
    hard_stop: float | None = None
    conditions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradePlanRiskRules(BaseModel):
    risk_reward: float | None = Field(default=None, ge=0)
    first_target_rr: float | None = Field(default=None, ge=0)
    final_target_rr: float | None = Field(default=None, ge=0)
    selected_rr: float | None = Field(default=None, ge=0)
    selected_rr_target: str | None = None
    min_rr_ratio: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradePlan(BaseModel):
    version: TradePlanVersion = "v1"
    entry: TradePlanEntry = Field(default_factory=TradePlanEntry)
    stop_loss: float | None = None
    targets: list[TradePlanTarget] = Field(default_factory=list)
    invalidation: TradePlanInvalidation | None = None
    risk_rules: TradePlanRiskRules = Field(default_factory=TradePlanRiskRules)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradePlanCompletenessResult(BaseModel):
    complete: bool
    fallback_used: bool = False
    fallback_stop_used: bool = False
    fallback_targets_used: bool = False
    has_structural_stop: bool = False
    has_invalidation_thesis: bool = False
    has_structural_target: bool = False
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_trade_plan_from_legacy_fields(
    *,
    entry_min: float | None = None,
    entry_max: float | None = None,
    stop_loss: float | None = None,
    take_profit_1: float | None = None,
    take_profit_2: float | None = None,
    risk_reward: float | None = None,
    first_target_rr: float | None = None,
    final_target_rr: float | None = None,
    selected_rr: float | None = None,
    selected_rr_target: str | None = None,
    min_rr_ratio: float | None = None,
    source: str = "legacy_fields",
) -> TradePlan:
    targets = [
        TradePlanTarget(label=label, price=price, source=source)
        for label, price in (("TP1", take_profit_1), ("TP2", take_profit_2))
        if price is not None
    ]
    return TradePlan(
        entry=TradePlanEntry(
            price=_entry_price(entry_min, entry_max),
            min_price=entry_min,
            max_price=entry_max,
            source=source,
        ),
        stop_loss=stop_loss,
        targets=targets,
        invalidation=TradePlanInvalidation(
            price=stop_loss,
            hard_stop=stop_loss,
            metadata={"source": source},
        ),
        risk_rules=TradePlanRiskRules(
            risk_reward=risk_reward,
            first_target_rr=first_target_rr,
            final_target_rr=final_target_rr,
            selected_rr=selected_rr,
            selected_rr_target=selected_rr_target,
            min_rr_ratio=min_rr_ratio,
        ),
        metadata={"source": source},
    )


def _entry_price(entry_min: float | None, entry_max: float | None) -> float | None:
    if entry_min is not None and entry_max is not None:
        return (entry_min + entry_max) / 2
    return entry_min if entry_min is not None else entry_max
