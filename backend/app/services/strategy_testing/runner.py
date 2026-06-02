from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from app.schemas.backtest import BacktestRunRequest
from app.services.backtest_runner import (
    BacktestDetailedRunResult,
    BacktestSimulatedTrade,
    ProductionBacktestRunner,
)
from app.services.strategy_testing.assumptions import build_strategy_test_assumptions
from app.services.strategy_testing.schemas import (
    StrategyTestPair,
    StrategyTestRunRequest,
    StrategyTestTrade,
)


@dataclass(frozen=True)
class StrategyTestScenarioResult:
    run_id: UUID
    strategy: str
    pair: StrategyTestPair
    timeframe: str
    summary: dict[str, Any]
    trades: list[StrategyTestTrade] = field(default_factory=list)
    assumptions: dict[str, Any] = field(default_factory=dict)


class StrategyTestScenarioRunner:
    def __init__(self, backtest_runner: ProductionBacktestRunner | None = None) -> None:
        self._backtest_runner = backtest_runner or ProductionBacktestRunner()

    def run_scenario(
        self,
        *,
        run_id: UUID,
        user_id: UUID,
        request: StrategyTestRunRequest,
        strategy: str,
        pair: StrategyTestPair,
        timeframe: str,
    ) -> StrategyTestScenarioResult:
        assumptions = build_strategy_test_assumptions(
            mode=request.mode,
            fee_rate=request.fee_rate,
            slippage_bps=request.slippage_bps,
            same_candle_policy=request.same_candle_policy,
            initial_capital=request.initial_capital,
            params=request.params,
        )
        detailed = self._backtest_runner.run_detailed(
            _backtest_request_from_scenario(
                request=request,
                strategy=strategy,
                pair=pair,
                timeframe=timeframe,
            ),
            mode=request.mode,
            options=assumptions.model_dump(mode="json"),
        )
        trades = [
            _strategy_test_trade_from_backtest_trade(
                run_id=run_id,
                user_id=user_id,
                request=request,
                trade=trade,
            )
            for trade in detailed.trades
        ]
        return StrategyTestScenarioResult(
            run_id=run_id,
            strategy=strategy,
            pair=pair,
            timeframe=timeframe,
            summary=_scenario_summary(detailed, strategy=strategy, pair=pair, timeframe=timeframe),
            trades=trades,
            assumptions=detailed.assumptions,
        )


def strategy_test_user_uuid(user_id: str | UUID) -> UUID:
    if isinstance(user_id, UUID):
        return user_id
    try:
        return UUID(user_id)
    except ValueError:
        return uuid5(NAMESPACE_DNS, f"crypto-radar-strategy-test:{user_id}")


def _backtest_request_from_scenario(
    *,
    request: StrategyTestRunRequest,
    strategy: str,
    pair: StrategyTestPair,
    timeframe: str,
) -> BacktestRunRequest:
    params = _backtest_params_from_strategy_test_request(request)
    params["same_candle_policy"] = request.same_candle_policy
    return BacktestRunRequest(
        user_id=request.user_id,
        strategy_code=strategy,
        strategy_version=_strategy_version(request.params, strategy),
        exchange=pair.exchange,
        symbol=pair.symbol,
        timeframe=timeframe,
        start_at=request.start_at,
        end_at=request.end_at,
        initial_capital=request.initial_capital,
        fee_rate=request.fee_rate,
        slippage_bps=request.slippage_bps,
        params=params,
    )


def _backtest_params_from_strategy_test_request(request: StrategyTestRunRequest) -> dict[str, Any]:
    params = dict(request.params)
    if request.mode in {"discovery", "research_virtual"}:
        params.setdefault("signal_selection_policy", "all_non_overlapping")
        params.setdefault("max_concurrent_positions", 10)
    else:
        params.setdefault("signal_selection_policy", "first_actionable")
        params.setdefault("max_concurrent_positions", 1)
    params.setdefault("max_positions_per_symbol", 1)
    params.setdefault("cooldown_bars_after_close", 0)
    params.setdefault("allow_opposite_signal_flip", False)
    return params


def _strategy_version(params: dict[str, Any], strategy: str) -> str | None:
    versions = params.get("strategy_versions")
    if isinstance(versions, dict):
        version = versions.get(strategy)
        if version is not None:
            return str(version)
    version = params.get("strategy_version")
    return str(version) if version is not None else None


def _strategy_test_trade_from_backtest_trade(
    *,
    run_id: UUID,
    user_id: UUID,
    request: StrategyTestRunRequest,
    trade: BacktestSimulatedTrade,
) -> StrategyTestTrade:
    return StrategyTestTrade(
        run_id=run_id,
        trade_id=trade.trade_id,
        user_id=user_id,
        mode=request.mode,
        strategy_code=trade.strategy_code,
        strategy_version=trade.strategy_version,
        exchange=trade.exchange,
        symbol=trade.symbol,
        timeframe=trade.timeframe,
        direction=trade.direction,
        signal_score=trade.signal_score,
        market_regime=trade.market_regime,
        score_bucket=trade.score_bucket,
        entry_time=trade.entry_time,
        exit_time=trade.exit_time,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        stop_loss=trade.stop_loss,
        targets=trade.targets,
        selected_rr=trade.selected_rr,
        realized_r=trade.realized_r,
        pnl=trade.pnl,
        pnl_pct=trade.pnl_pct,
        fees=trade.fees,
        slippage=trade.slippage,
        mfe_r=trade.mfe_r,
        mae_r=trade.mae_r,
        bars_to_entry=trade.bars_to_entry,
        bars_in_trade=trade.bars_in_trade,
        close_reason=trade.close_reason,
        outcome=trade.outcome,
        risk_rejected=trade.risk_rejected,
        execution_rejected=trade.execution_rejected,
        warnings=trade.warnings,
        features_snapshot=trade.features_snapshot,
        trade_plan=trade.trade_plan,
        tags=_trade_tags(request.tags, trade.tags),
        created_at=_as_utc(trade.created_at),
    )


def _trade_tags(request_tags: list[str], trade_tags: list[str]) -> list[str]:
    tags: list[str] = []
    for tag in [*request_tags, *trade_tags, "backtest"]:
        if tag not in tags:
            tags.append(tag)
    return tags


def _scenario_summary(
    detailed: BacktestDetailedRunResult,
    *,
    strategy: str,
    pair: StrategyTestPair,
    timeframe: str,
) -> dict[str, Any]:
    result = detailed.run_result.result
    metrics = result.metrics if result is not None else {}
    return {
        "strategy": strategy,
        "exchange": pair.exchange,
        "symbol": pair.symbol,
        "timeframe": timeframe,
        "status": detailed.run_result.status,
        "trades_count": len(detailed.trades),
        "signals_seen": detailed.signals_seen,
        "risk_rejections": detailed.risk_rejections,
        "execution_rejections": detailed.execution_rejections,
        "pnl": str(result.pnl) if result is not None else str(Decimal("0")),
        "pnl_pct": result.pnl_pct if result is not None else 0.0,
        "metrics": metrics,
        "assumptions": detailed.assumptions,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
