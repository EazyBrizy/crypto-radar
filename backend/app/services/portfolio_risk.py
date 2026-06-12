from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


PortfolioRiskAction = Literal["allow", "reduce_size", "block_trade", "pause_strategy", "stop_agent"]


@dataclass(frozen=True)
class PortfolioRiskContext:
    account_equity: float
    proposed_risk_amount: float
    open_risk_amount: float = 0.0
    symbol_open_risk_amount: float = 0.0
    strategy_open_risk_amount: float = 0.0
    correlated_open_risk_amount: float = 0.0
    daily_loss_amount: float = 0.0
    account_drawdown_percent: float | None = None
    open_position_count: int = 0
    strategy_losses_today: int = 0


@dataclass(frozen=True)
class PortfolioRiskLimits:
    max_open_risk_percent: float = 0.0
    max_symbol_risk_percent: float = 0.0
    max_strategy_exposure_percent: float = 0.0
    max_correlated_risk_percent: float = 0.0
    max_daily_loss_percent: float = 0.0
    max_account_drawdown_percent: float = 0.0
    max_concurrent_positions: int = 0
    max_strategy_losses_per_day: int = 0


@dataclass(frozen=True)
class PortfolioRiskDecision:
    action: PortfolioRiskAction
    can_enter: bool
    reason_code: str
    reason_codes: list[str] = field(default_factory=list)
    message: str = ""
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    proposed_risk_amount: float = 0.0
    approved_risk_amount: float = 0.0
    size_multiplier: float = 1.0
    metrics: dict[str, float | int | None] = field(default_factory=dict)


class PortfolioRiskService:
    def evaluate(
        self,
        context: PortfolioRiskContext,
        limits: PortfolioRiskLimits,
    ) -> PortfolioRiskDecision:
        equity = max(0.0, float(context.account_equity or 0.0))
        proposed = max(0.0, float(context.proposed_risk_amount or 0.0))
        metrics = _metrics(context, limits)

        stop_reason = _stop_agent_reason(context, limits)
        if stop_reason is not None:
            return _decision(
                action="stop_agent",
                reason_code=stop_reason[0],
                message=stop_reason[1],
                proposed_risk_amount=proposed,
                approved_risk_amount=0.0,
                metrics=metrics,
            )

        pause_reason = _pause_strategy_reason(context, limits)
        if pause_reason is not None:
            return _decision(
                action="pause_strategy",
                reason_code=pause_reason[0],
                message=pause_reason[1],
                proposed_risk_amount=proposed,
                approved_risk_amount=0.0,
                metrics=metrics,
            )

        block_reason = _block_trade_reason(context, limits)
        if block_reason is not None:
            return _decision(
                action="block_trade",
                reason_code=block_reason[0],
                message=block_reason[1],
                proposed_risk_amount=proposed,
                approved_risk_amount=0.0,
                metrics=metrics,
            )

        open_risk_limit = _amount_limit(equity, limits.max_open_risk_percent)
        if open_risk_limit is not None:
            remaining = open_risk_limit - max(0.0, context.open_risk_amount)
            if 0 < remaining < proposed:
                return _decision(
                    action="reduce_size",
                    reason_code="max_open_risk_exceeded",
                    message="Portfolio open risk budget only allows a smaller trade size.",
                    proposed_risk_amount=proposed,
                    approved_risk_amount=remaining,
                    metrics=metrics,
                )

        return PortfolioRiskDecision(
            action="allow",
            can_enter=True,
            reason_code="portfolio_risk_allowed",
            reason_codes=["portfolio_risk_allowed"],
            message="Portfolio risk limits allow this trade.",
            proposed_risk_amount=proposed,
            approved_risk_amount=proposed,
            size_multiplier=1.0,
            metrics=metrics,
        )


def _stop_agent_reason(
    context: PortfolioRiskContext,
    limits: PortfolioRiskLimits,
) -> tuple[str, str] | None:
    if _reaches_amount_limit(context.daily_loss_amount, context.account_equity, limits.max_daily_loss_percent):
        return "daily_loss_limit_exceeded", "Daily loss limit is reached; stop the autonomous agent."
    if (
        context.account_drawdown_percent is not None
        and _limit_enabled(limits.max_account_drawdown_percent)
        and context.account_drawdown_percent >= limits.max_account_drawdown_percent
    ):
        return "max_account_drawdown_exceeded", "Account drawdown limit is reached; stop the autonomous agent."
    return None


def _pause_strategy_reason(
    context: PortfolioRiskContext,
    limits: PortfolioRiskLimits,
) -> tuple[str, str] | None:
    if (
        limits.max_strategy_losses_per_day > 0
        and context.strategy_losses_today >= limits.max_strategy_losses_per_day
    ):
        return (
            "max_strategy_losses_per_day_exceeded",
            "Strategy daily loss count reached its limit; pause this strategy.",
        )
    return None


def _block_trade_reason(
    context: PortfolioRiskContext,
    limits: PortfolioRiskLimits,
) -> tuple[str, str] | None:
    proposed = max(0.0, context.proposed_risk_amount)
    if limits.max_concurrent_positions > 0 and context.open_position_count >= limits.max_concurrent_positions:
        return "max_concurrent_positions_exceeded", "Max concurrent position count is reached."
    if _exceeds_amount_limit(
        context.symbol_open_risk_amount + proposed,
        context.account_equity,
        limits.max_symbol_risk_percent,
    ):
        return "max_symbol_risk_exceeded", "Max symbol risk would be exceeded."
    if _exceeds_amount_limit(
        context.strategy_open_risk_amount + proposed,
        context.account_equity,
        limits.max_strategy_exposure_percent,
    ):
        return "max_strategy_exposure_exceeded", "Max strategy exposure would be exceeded."
    if _exceeds_amount_limit(
        context.correlated_open_risk_amount + proposed,
        context.account_equity,
        limits.max_correlated_risk_percent,
    ):
        return "max_correlated_risk_exceeded", "Max correlated risk would be exceeded."
    open_risk_limit = _amount_limit(context.account_equity, limits.max_open_risk_percent)
    if open_risk_limit is not None and context.open_risk_amount >= open_risk_limit:
        return "max_open_risk_exceeded", "Max open risk would be exceeded."
    return None


def _decision(
    *,
    action: PortfolioRiskAction,
    reason_code: str,
    message: str,
    proposed_risk_amount: float,
    approved_risk_amount: float,
    metrics: dict[str, float | int | None],
) -> PortfolioRiskDecision:
    can_enter = action in {"allow", "reduce_size"}
    size_multiplier = (
        max(0.0, min(1.0, approved_risk_amount / proposed_risk_amount))
        if proposed_risk_amount > 0
        else 0.0
    )
    return PortfolioRiskDecision(
        action=action,
        can_enter=can_enter,
        reason_code=reason_code,
        reason_codes=[reason_code],
        message=message,
        blockers=[] if can_enter else [message],
        warnings=[message] if action == "reduce_size" else [],
        proposed_risk_amount=proposed_risk_amount,
        approved_risk_amount=approved_risk_amount,
        size_multiplier=size_multiplier,
        metrics=metrics,
    )


def _amount_limit(account_equity: float, percent: float) -> float | None:
    if not _limit_enabled(percent) or account_equity <= 0:
        return None
    return account_equity * percent / 100


def _exceeds_amount_limit(value: float, account_equity: float, percent: float) -> bool:
    limit = _amount_limit(account_equity, percent)
    return limit is not None and value > limit


def _reaches_amount_limit(value: float, account_equity: float, percent: float) -> bool:
    limit = _amount_limit(account_equity, percent)
    return limit is not None and value >= limit


def _limit_enabled(value: float | int | None) -> bool:
    return value is not None and float(value) > 0


def _metrics(
    context: PortfolioRiskContext,
    limits: PortfolioRiskLimits,
) -> dict[str, float | int | None]:
    equity = max(0.0, float(context.account_equity or 0.0))
    return {
        "account_equity": equity,
        "proposed_risk_amount": max(0.0, context.proposed_risk_amount),
        "open_risk_amount": max(0.0, context.open_risk_amount),
        "open_risk_percent": _percent(context.open_risk_amount, equity),
        "symbol_open_risk_amount": max(0.0, context.symbol_open_risk_amount),
        "symbol_open_risk_percent": _percent(context.symbol_open_risk_amount, equity),
        "strategy_open_risk_amount": max(0.0, context.strategy_open_risk_amount),
        "strategy_open_risk_percent": _percent(context.strategy_open_risk_amount, equity),
        "correlated_open_risk_amount": max(0.0, context.correlated_open_risk_amount),
        "correlated_open_risk_percent": _percent(context.correlated_open_risk_amount, equity),
        "daily_loss_amount": max(0.0, context.daily_loss_amount),
        "daily_loss_percent": _percent(context.daily_loss_amount, equity),
        "account_drawdown_percent": context.account_drawdown_percent,
        "open_position_count": context.open_position_count,
        "strategy_losses_today": context.strategy_losses_today,
        "max_open_risk_percent": limits.max_open_risk_percent,
        "max_symbol_risk_percent": limits.max_symbol_risk_percent,
        "max_strategy_exposure_percent": limits.max_strategy_exposure_percent,
        "max_correlated_risk_percent": limits.max_correlated_risk_percent,
        "max_daily_loss_percent": limits.max_daily_loss_percent,
        "max_account_drawdown_percent": limits.max_account_drawdown_percent,
        "max_concurrent_positions": limits.max_concurrent_positions,
        "max_strategy_losses_per_day": limits.max_strategy_losses_per_day,
    }


def _percent(amount: float, equity: float) -> float | None:
    if equity <= 0:
        return None
    return max(0.0, amount) / equity * 100


portfolio_risk_service = PortfolioRiskService()
