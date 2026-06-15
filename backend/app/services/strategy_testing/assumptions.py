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
    same_candle_policy: StrategyTestSameCandlePolicy = "conservative_stop_first"
    initial_capital: Decimal = Field(gt=0)
    rr_hard_gate_enabled: bool
    risk_gate_enabled: bool
    virtual_execution_enabled: bool
    lifecycle_enabled: bool
    historical_pending_entries_enabled: bool
    historical_pending_max_wait_bars: int = Field(default=12, ge=1)
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
    historical_pending_entries_enabled = _historical_pending_entries_enabled(mode, request_params)
    historical_pending_max_wait_bars = _historical_pending_max_wait_bars(request_params)
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
            historical_pending_entries_enabled=False,
            historical_pending_max_wait_bars=historical_pending_max_wait_bars,
            notes=[
                "Discovery mode records signals only and does not execute virtual trades.",
                "Discovery mode does not arm historical pending-entry chains.",
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
            historical_pending_entries_enabled=historical_pending_entries_enabled,
            historical_pending_max_wait_bars=historical_pending_max_wait_bars,
            notes=[
                "Research virtual mode evaluates risk context but converts hard rejections into warnings.",
                "Research virtual mode uses simulated virtual execution only.",
                "Research virtual mode replays historical pending-entry chains unless request params disable them.",
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
        historical_pending_entries_enabled=historical_pending_entries_enabled,
        historical_pending_max_wait_bars=historical_pending_max_wait_bars,
        notes=[
            "Production-like mode keeps the risk gate enabled.",
            "Production-like mode uses hard RR gating unless request params disable it explicitly.",
            "Production-like mode replays historical pending-entry chains unless request params disable them.",
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


def _historical_pending_entries_enabled(mode: BacktestMode, params: Mapping[str, Any]) -> bool:
    if mode == "discovery" or _optional_bool(params, "preserve_legacy_backtest") is True:
        return False
    explicit = _optional_bool(params, "historical_pending_entries_enabled")
    if explicit is not None:
        return explicit
    return mode in {"research_virtual", "production_like"}


def _historical_pending_max_wait_bars(params: Mapping[str, Any]) -> int:
    for key in ("historical_pending_max_wait_bars", "pending_entry_max_wait_bars", "max_wait_bars"):
        try:
            value = params.get(key)
            parsed = int(value) if value is not None else 0
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    return 12


def _optional_bool(params: Mapping[str, Any], key: str) -> bool | None:
    if key not in params or params.get(key) is None:
        return None
    value = params.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None
