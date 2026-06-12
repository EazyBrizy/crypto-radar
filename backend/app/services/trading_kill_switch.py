from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.risk import RiskContext
from app.schemas.user import RiskManagementSettings

try:
    from prometheus_client import Gauge
except ImportError:  # pragma: no cover - optional runtime integration
    Gauge = None  # type: ignore[assignment]


KillSwitchState = Literal["healthy", "degraded", "paused", "killed", "manual_unlock_required"]
KillSwitchSeverity = Literal["warning", "blocker"]

STATE_METRIC_VALUE: dict[str, int] = {
    "healthy": 0,
    "degraded": 1,
    "paused": 2,
    "killed": 3,
    "manual_unlock_required": 4,
}


class KillSwitchReason(BaseModel):
    code: str
    severity: KillSwitchSeverity = "blocker"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KillSwitchInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    market_data_status: str = "unknown"
    stale_data_seconds: float | None = Field(default=None, ge=0)
    max_stale_data_seconds: float | None = Field(default=None, ge=0)
    spread_bps: float | None = Field(default=None, ge=0)
    max_spread_bps: float | None = Field(default=None, ge=0)
    slippage_bps: float | None = Field(default=None, ge=0)
    max_slippage_bps: float | None = Field(default=None, ge=0)
    daily_loss_pct: float | None = Field(default=None, ge=0)
    max_daily_loss_pct: float | None = Field(default=None, ge=0)
    drawdown_pct: float | None = Field(default=None, ge=0)
    max_drawdown_pct: float | None = Field(default=None, ge=0)
    execution_rejections_count: int = Field(default=0, ge=0)
    max_execution_rejections: int | None = Field(default=None, ge=0)
    consecutive_losses: int = Field(default=0, ge=0)
    max_consecutive_losses: int | None = Field(default=None, ge=0)
    exchange_status: str = "unknown"
    external_kill: bool = False
    latched_state: KillSwitchState | None = None
    manual_unlock_requested: bool = False


class KillSwitchDecision(BaseModel):
    state: KillSwitchState
    execution_allowed: bool
    manual_unlock_required: bool = False
    reasons: list[KillSwitchReason] = Field(default_factory=list)
    metrics: dict[str, float | int] = Field(default_factory=dict)

    @property
    def reason_codes(self) -> list[str]:
        return [reason.code for reason in self.reasons]


class TradingKillSwitchService:
    def evaluate(self, snapshot: KillSwitchInput | Mapping[str, Any]) -> KillSwitchDecision:
        data = snapshot if isinstance(snapshot, KillSwitchInput) else KillSwitchInput.model_validate(dict(snapshot))
        blockers: list[KillSwitchReason] = []
        warnings: list[KillSwitchReason] = []

        if data.latched_state in {"killed", "manual_unlock_required"} and not data.manual_unlock_requested:
            blockers.append(
                _reason(
                    "kill_switch_manual_unlock_required",
                    "Manual unlock is required before execution can resume.",
                    {"latched_state": data.latched_state},
                )
            )

        if data.external_kill:
            blockers.append(_reason("kill_switch_external_kill", "Execution kill-switch is active."))

        market_status = data.market_data_status.strip().lower()
        if market_status in {"stale", "missing"}:
            blockers.append(
                _reason(
                    "kill_switch_stale_market_data",
                    "Market data is stale or unavailable; execution is paused.",
                    {
                        "market_data_status": market_status,
                        "stale_data_seconds": data.stale_data_seconds,
                        "max_stale_data_seconds": data.max_stale_data_seconds,
                    },
                )
            )
        elif (
            data.max_stale_data_seconds is not None
            and data.max_stale_data_seconds > 0
            and data.stale_data_seconds is not None
            and data.stale_data_seconds > data.max_stale_data_seconds
        ):
            blockers.append(
                _reason(
                    "kill_switch_stale_market_data",
                    "Market data is older than the configured execution threshold.",
                    {
                        "stale_data_seconds": data.stale_data_seconds,
                        "max_stale_data_seconds": data.max_stale_data_seconds,
                    },
                )
            )

        if _over_limit(data.spread_bps, data.max_spread_bps):
            blockers.append(
                _reason(
                    "kill_switch_spread_too_wide",
                    "Spread is above the kill-switch threshold.",
                    {"spread_bps": data.spread_bps, "max_spread_bps": data.max_spread_bps},
                )
            )
        if _over_limit(data.slippage_bps, data.max_slippage_bps):
            blockers.append(
                _reason(
                    "kill_switch_slippage_too_high",
                    "Expected slippage is above the kill-switch threshold.",
                    {"slippage_bps": data.slippage_bps, "max_slippage_bps": data.max_slippage_bps},
                )
            )
        if _over_limit(data.daily_loss_pct, data.max_daily_loss_pct):
            blockers.append(
                _reason(
                    "kill_switch_daily_loss_exceeded",
                    "Daily loss limit exceeded; manual unlock is required.",
                    {"daily_loss_pct": data.daily_loss_pct, "max_daily_loss_pct": data.max_daily_loss_pct},
                )
            )
        if _over_limit(data.drawdown_pct, data.max_drawdown_pct):
            blockers.append(
                _reason(
                    "kill_switch_drawdown_exceeded",
                    "Account drawdown limit exceeded; manual unlock is required.",
                    {"drawdown_pct": data.drawdown_pct, "max_drawdown_pct": data.max_drawdown_pct},
                )
            )
        if _count_over_limit(data.execution_rejections_count, data.max_execution_rejections):
            blockers.append(
                _reason(
                    "kill_switch_execution_rejections",
                    "Too many execution rejections; execution is paused.",
                    {
                        "execution_rejections_count": data.execution_rejections_count,
                        "max_execution_rejections": data.max_execution_rejections,
                    },
                )
            )
        if _count_over_limit(data.consecutive_losses, data.max_consecutive_losses):
            blockers.append(
                _reason(
                    "kill_switch_consecutive_losses",
                    "Consecutive loss limit reached; execution is paused.",
                    {
                        "consecutive_losses": data.consecutive_losses,
                        "max_consecutive_losses": data.max_consecutive_losses,
                    },
                )
            )

        exchange_status = data.exchange_status.strip().lower()
        if exchange_status == "degraded":
            warnings.append(
                _reason(
                    "kill_switch_exchange_degraded",
                    "Exchange health is degraded.",
                    {"exchange_status": exchange_status},
                    severity="warning",
                )
            )

        reasons = [*blockers, *warnings]
        state = _state_for(blockers, warnings)
        metrics = _metrics(data, state)
        _publish_metrics(metrics)
        return KillSwitchDecision(
            state=state,
            execution_allowed=state in {"healthy", "degraded"},
            manual_unlock_required=state == "manual_unlock_required",
            reasons=reasons,
            metrics=metrics,
        )

    def evaluate_from_risk_context(
        self,
        context: RiskContext,
        risk_settings: RiskManagementSettings,
    ) -> KillSwitchDecision:
        equity = context.account_equity if context.account_equity > 0 else 0.0
        daily_loss_pct = (context.daily_loss_amount / equity * 100) if equity > 0 else None
        exchange_status = "degraded" if context.exchange_rule_status in {"missing", "stale"} else "healthy"
        market_data_status = (
            context.market_data_status
            if context.stage in {"pre_execution", "confirm"}
            else "fresh"
        )
        return self.evaluate(
            KillSwitchInput(
                market_data_status=market_data_status,
                spread_bps=context.spread_bps,
                max_spread_bps=risk_settings.max_spread_bps,
                slippage_bps=context.slippage_bps,
                max_slippage_bps=risk_settings.max_slippage_bps,
                daily_loss_pct=daily_loss_pct,
                max_daily_loss_pct=risk_settings.max_daily_loss_percent,
                drawdown_pct=context.account_drawdown_percent,
                max_drawdown_pct=(
                    context.max_account_drawdown_percent
                    if context.max_account_drawdown_percent > 0
                    else risk_settings.max_account_drawdown_percent
                ),
                consecutive_losses=context.strategy_losses_today,
                max_consecutive_losses=risk_settings.max_strategy_losses_per_day,
                exchange_status=exchange_status,
            )
        )


def kill_switch_payload(decision: KillSwitchDecision) -> dict[str, Any]:
    payload = decision.model_dump(mode="json")
    payload["reason_codes"] = list(decision.reason_codes)
    return payload


def scanner_kill_switch_payload(
    scanner_status: Mapping[str, Any],
    *,
    scanner_running: bool,
    max_stale_data_seconds: float,
) -> dict[str, Any]:
    market_data_status = str(scanner_status.get("market_data_status") or "unknown").strip().lower()
    last_tick_age = _float_or_none(scanner_status.get("last_tick_age_seconds"))
    if not scanner_running and market_data_status in {"offline", "waiting", "unknown"}:
        snapshot_status = "fresh"
    elif market_data_status in {"stale", "missing"}:
        snapshot_status = "stale"
    else:
        snapshot_status = "fresh"
    exchange_status = "degraded" if market_data_status == "error" else "healthy"
    return kill_switch_payload(
        trading_kill_switch_service.evaluate(
            KillSwitchInput(
                market_data_status=snapshot_status,
                stale_data_seconds=last_tick_age,
                max_stale_data_seconds=max_stale_data_seconds if scanner_running else None,
                exchange_status=exchange_status,
            )
        )
    )


def _state_for(
    blockers: list[KillSwitchReason],
    warnings: list[KillSwitchReason],
) -> KillSwitchState:
    codes = {reason.code for reason in blockers}
    if "kill_switch_external_kill" in codes:
        return "killed"
    if codes & {
        "kill_switch_daily_loss_exceeded",
        "kill_switch_drawdown_exceeded",
        "kill_switch_manual_unlock_required",
    }:
        return "manual_unlock_required"
    if blockers:
        return "paused"
    if warnings:
        return "degraded"
    return "healthy"


def _reason(
    code: str,
    message: str,
    metadata: Mapping[str, Any] | None = None,
    *,
    severity: KillSwitchSeverity = "blocker",
) -> KillSwitchReason:
    return KillSwitchReason(code=code, severity=severity, message=message, metadata=dict(metadata or {}))


def _over_limit(value: float | None, limit: float | None) -> bool:
    return value is not None and limit is not None and limit > 0 and value >= limit


def _count_over_limit(value: int, limit: int | None) -> bool:
    return limit is not None and limit > 0 and value >= limit


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _metrics(data: KillSwitchInput, state: KillSwitchState) -> dict[str, float | int]:
    return {
        "kill_switch_state": STATE_METRIC_VALUE[state],
        "execution_rejections_count": data.execution_rejections_count,
        "stale_data_seconds": data.stale_data_seconds or 0.0,
        "daily_loss_pct": data.daily_loss_pct or 0.0,
        "drawdown_pct": data.drawdown_pct or 0.0,
    }


def _metric_gauges() -> dict[str, Any]:
    if Gauge is None:
        return {}
    if not hasattr(_metric_gauges, "_gauges"):
        _metric_gauges._gauges = {  # type: ignore[attr-defined]
            name: Gauge(name, description)
            for name, description in {
                "kill_switch_state": "Trading kill-switch state: 0 healthy, 1 degraded, 2 paused, 3 killed, 4 manual unlock required.",
                "execution_rejections_count": "Execution rejections counted by the trading kill-switch.",
                "stale_data_seconds": "Age of market data considered by the trading kill-switch.",
                "daily_loss_pct": "Daily loss percentage considered by the trading kill-switch.",
                "drawdown_pct": "Account drawdown percentage considered by the trading kill-switch.",
            }.items()
        }
    return _metric_gauges._gauges  # type: ignore[attr-defined]


def _publish_metrics(metrics: Mapping[str, float | int]) -> None:
    for name, value in metrics.items():
        gauge = _metric_gauges().get(name)
        if gauge is not None:
            gauge.set(value)


trading_kill_switch_service = TradingKillSwitchService()
