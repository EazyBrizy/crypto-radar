from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field

from app.services.strategy_testing.schemas import StrategyTestSameCandlePolicy


BacktestMode = Literal["discovery", "research_virtual", "production_like"]


class StrategyTestAssumptions(BaseModel):
    mode: BacktestMode
    fee_rate: Decimal = Field(ge=0)
    slippage_bps: Decimal = Field(ge=0)
    same_candle_policy: StrategyTestSameCandlePolicy = "stop_first"
    initial_capital: Decimal = Field(gt=0)
    rr_hard_gate_enabled: bool
    risk_gate_enabled: bool
    virtual_execution_enabled: bool
    lifecycle_enabled: bool
    notes: list[str] = Field(default_factory=list)


def build_strategy_test_assumptions(
    *,
    mode: BacktestMode,
    fee_rate: Decimal,
    slippage_bps: Decimal,
    same_candle_policy: StrategyTestSameCandlePolicy,
    initial_capital: Decimal,
    params: Mapping[str, Any] | None = None,
) -> StrategyTestAssumptions:
    request_params = params or {}
    if mode == "discovery":
        return StrategyTestAssumptions(
            mode=mode,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
            same_candle_policy=same_candle_policy,
            initial_capital=initial_capital,
            rr_hard_gate_enabled=False,
            risk_gate_enabled=False,
            virtual_execution_enabled=False,
            lifecycle_enabled=False,
            notes=[
                "Discovery mode treats risk-gate and RR hard blocks as research warnings.",
                "Discovery mode uses minimal simulated outcomes and never mutates execution state.",
            ],
        )
    if mode == "research_virtual":
        return StrategyTestAssumptions(
            mode=mode,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
            same_candle_policy=same_candle_policy,
            initial_capital=initial_capital,
            rr_hard_gate_enabled=False,
            risk_gate_enabled=False,
            virtual_execution_enabled=True,
            lifecycle_enabled=True,
            notes=[
                "Research virtual mode evaluates risk context but converts hard rejections into warnings.",
                "Research virtual mode uses simulated virtual execution only.",
            ],
        )

    rr_hard_gate_enabled = not _explicitly_disabled(request_params, "rr_hard_gate_enabled")
    return StrategyTestAssumptions(
        mode=mode,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        same_candle_policy=same_candle_policy,
        initial_capital=initial_capital,
        rr_hard_gate_enabled=rr_hard_gate_enabled,
        risk_gate_enabled=True,
        virtual_execution_enabled=True,
        lifecycle_enabled=True,
        notes=[
            "Production-like mode keeps the risk gate enabled.",
            "Production-like mode uses hard RR gating unless request params disable it explicitly.",
        ],
    )


def _explicitly_disabled(params: Mapping[str, Any], key: str) -> bool:
    value = params.get(key)
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return value.strip().lower() in {"0", "false", "no", "off", "disabled"}
    risk_settings = params.get("risk_settings")
    if key == "rr_hard_gate_enabled" and isinstance(risk_settings, Mapping):
        guard_mode = risk_settings.get("backtest_rr_guard_mode") or risk_settings.get("rr_guard_mode")
        if isinstance(guard_mode, str):
            return guard_mode.strip().lower() in {"off", "soft"}
    return False
