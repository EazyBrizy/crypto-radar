from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


TradePlanVersion = Literal["v1"]
TargetSource = Literal[
    "nearest_liquidity_pool",
    "previous_day_high",
    "previous_day_low",
    "session_high",
    "session_low",
    "range_midpoint",
    "range_opposite_boundary",
    "vwap",
    "vwap_deviation_band",
    "htf_support",
    "htf_resistance",
    "measured_move",
    "risk_multiple_fallback",
]


class TargetThesis(BaseModel):
    source: TargetSource
    price: float | None = None
    direction: Literal["LONG", "SHORT"]
    confidence: float = Field(..., ge=0, le=1)
    priority: int
    close_percent: float | None = None
    requires_acceptance: bool = False
    invalidation_hint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    thesis: TargetThesis | None = None
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
    has_entry: bool = False
    has_structural_stop: bool = False
    has_invalidation_thesis: bool = False
    has_structural_target: bool = False
    has_score: bool = False
    has_context: bool = False
    missing: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    execution_allowed_virtual: bool = False
    execution_allowed_real: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def sync_missing_field_aliases(self) -> "TradePlanCompletenessResult":
        if not self.missing_fields and self.missing:
            self.missing_fields = [_normalized_missing_field(value) for value in self.missing]
        if not self.missing and self.missing_fields:
            self.missing = [_legacy_missing_field(value) for value in self.missing_fields]
        if self.complete and not self.blockers:
            self.execution_allowed_virtual = True
            self.execution_allowed_real = True
        return self


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


def _normalized_missing_field(value: str) -> str:
    mapping = {
        "structural_stop": "stop",
        "invalidation_thesis": "invalidation",
        "structural_target": "target",
    }
    return mapping.get(value, value)


def _legacy_missing_field(value: str) -> str:
    mapping = {
        "stop": "structural_stop",
        "invalidation": "invalidation_thesis",
        "target": "structural_target",
    }
    return mapping.get(value, value)
