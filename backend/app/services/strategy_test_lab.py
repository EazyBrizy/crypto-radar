from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from app.schemas.backtest import BacktestRunRequest
from app.schemas.strategy_lab import (
    StrategyLabComparisonResult,
    StrategyLabMatrixRequest,
    StrategyLabRunItem,
    StrategyLabRunRequest,
    StrategyLabRunStatus,
    StrategyLabRunSummary,
)
from app.services.backtest_runner import (
    BacktestDetailedRunResult,
    BacktestSimulatedTrade,
    ProductionBacktestRunner,
)


LAB_BACKTEST_MODE = "research_virtual"
LAB_SOURCE = "strategy_lab"


class StrategyLabBacktestRunner(Protocol):
    def run_detailed(
        self,
        request: BacktestRunRequest,
        *,
        mode: str = "production_like",
        options: dict[str, Any] | None = None,
    ) -> BacktestDetailedRunResult:
        ...


class StrategyTestLabService:
    def __init__(self, runner: StrategyLabBacktestRunner | None = None) -> None:
        self._runner = runner or ProductionBacktestRunner()

    def run(self, request: StrategyLabRunRequest) -> StrategyLabComparisonResult:
        matrix_request = StrategyLabMatrixRequest(**request.model_dump())
        return self.run_matrix(matrix_request)

    def run_matrix(self, request: StrategyLabMatrixRequest) -> StrategyLabComparisonResult:
        lab_run_id = uuid4()
        items: list[StrategyLabRunItem] = []

        for strategy in request.strategies:
            for symbol in request.symbols:
                for timeframe in request.timeframes:
                    tags = _lab_tags(
                        request_tags=request.tags,
                        lab_run_id=lab_run_id,
                        mode=request.mode,
                        strategy=strategy,
                        symbol=symbol,
                        timeframe=timeframe,
                    )
                    backtest_request = _backtest_request_from_lab(
                        request=request,
                        strategy=strategy,
                        symbol=symbol,
                        timeframe=timeframe,
                        tags=tags,
                    )
                    scenario_id = _scenario_id(strategy=strategy, symbol=symbol, timeframe=timeframe)
                    try:
                        detailed = self._runner.run_detailed(
                            backtest_request,
                            mode=LAB_BACKTEST_MODE,
                            options=_runner_options(request=request, lab_run_id=lab_run_id, tags=tags),
                        )
                    except ValueError as exc:
                        items.append(
                            _run_item_from_error(
                                lab_run_id=lab_run_id,
                                request=request,
                                scenario_id=scenario_id,
                                strategy=strategy,
                                symbol=symbol,
                                timeframe=timeframe,
                                tags=tags,
                                error=str(exc),
                            )
                        )
                        continue
                    except Exception as exc:
                        items.append(
                            _run_item_from_error(
                                lab_run_id=lab_run_id,
                                request=request,
                                scenario_id=scenario_id,
                                strategy=strategy,
                                symbol=symbol,
                                timeframe=timeframe,
                                tags=tags,
                                error=str(exc),
                                forced_status="failed",
                            )
                        )
                        continue

                    items.append(
                        _run_item_from_detailed_result(
                            lab_run_id=lab_run_id,
                            request=request,
                            scenario_id=scenario_id,
                            strategy=strategy,
                            symbol=symbol,
                            timeframe=timeframe,
                            tags=tags,
                            detailed=detailed,
                        )
                    )

        return StrategyLabComparisonResult(
            lab_run_id=lab_run_id,
            mode=request.mode,
            label=request.label,
            tags=dict(request.tags),
            scenario_count=len(request.strategies) * len(request.symbols) * len(request.timeframes),
            completed_runs=sum(1 for item in items if item.status == "completed"),
            no_data_runs=sum(1 for item in items if item.status == "no_data"),
            insufficient_data_runs=sum(1 for item in items if item.status == "insufficient_data"),
            failed_runs=sum(1 for item in items if item.status == "failed"),
            overall_summary=_aggregate_run_summaries(items),
            metrics_by_strategy=_group_summaries(items, "strategy"),
            metrics_by_symbol=_group_summaries(items, "symbol"),
            metrics_by_timeframe=_group_summaries(items, "timeframe"),
            runs=items,
            metadata={
                "source": LAB_SOURCE,
                "backtest_mode": LAB_BACKTEST_MODE,
                "candle_state": "closed",
                "real_execution_side_effects": False,
            },
        )


def _backtest_request_from_lab(
    *,
    request: StrategyLabMatrixRequest,
    strategy: str,
    symbol: str,
    timeframe: str,
    tags: Mapping[str, str],
) -> BacktestRunRequest:
    params = dict(request.params)
    params.setdefault("warmup_candles", request.warmup_bars)
    params.setdefault("signal_selection_policy", "all_non_overlapping")
    params.setdefault("max_concurrent_positions", 10)
    params.setdefault("max_positions_per_symbol", 1)
    params.setdefault("cooldown_bars_after_close", 0)
    params.setdefault("allow_opposite_signal_flip", False)
    if request.max_bars_in_trade is not None:
        params.setdefault("max_bars_in_trade", request.max_bars_in_trade)
    params["strategy_lab"] = {
        "source": LAB_SOURCE,
        "mode": request.mode,
        "label": request.label,
        "tags": dict(tags),
        "candle_state": "closed",
        "max_bars_in_trade": request.max_bars_in_trade,
        "warmup_bars": request.warmup_bars,
    }
    return BacktestRunRequest(
        user_id=request.user_id,
        strategy_code=strategy,
        strategy_version=request.strategy_version,
        exchange=request.exchange,
        symbol=symbol,
        timeframe=timeframe,
        start_at=request.start_time,
        end_at=request.end_time,
        initial_capital=request.initial_equity,
        fee_rate=_fee_rate_from_bps(request.fees_bps),
        slippage_bps=request.slippage_bps,
        params=params,
    )


def _runner_options(
    *,
    request: StrategyLabMatrixRequest,
    lab_run_id: UUID,
    tags: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "source": LAB_SOURCE,
        "lab_run_id": str(lab_run_id),
        "lab_mode": request.mode,
        "label": request.label,
        "tags": dict(tags),
        "mode": LAB_BACKTEST_MODE,
        "candle_state": "closed",
        "risk_gate_enabled": False,
        "rr_hard_gate_enabled": False,
        "virtual_execution_enabled": True,
        "lifecycle_enabled": True,
    }


def _run_item_from_detailed_result(
    *,
    lab_run_id: UUID,
    request: StrategyLabMatrixRequest,
    scenario_id: str,
    strategy: str,
    symbol: str,
    timeframe: str,
    tags: Mapping[str, str],
    detailed: BacktestDetailedRunResult,
) -> StrategyLabRunItem:
    result = detailed.run_result.result
    metrics = dict(result.metrics) if result is not None else {}
    summary = _summary_from_detailed(detailed)
    return StrategyLabRunItem(
        lab_run_id=lab_run_id,
        scenario_id=scenario_id,
        status=summary.status,
        strategy=strategy,
        exchange=request.exchange,
        symbol=symbol,
        timeframe=timeframe,
        mode=request.mode,
        label=request.label,
        tags=dict(tags),
        summary=summary,
        metrics=metrics,
        assumptions=dict(detailed.assumptions),
        backtest_run_id=result.run_id if result is not None else None,
        created_at=_now_utc(),
    )


def _run_item_from_error(
    *,
    lab_run_id: UUID,
    request: StrategyLabMatrixRequest,
    scenario_id: str,
    strategy: str,
    symbol: str,
    timeframe: str,
    tags: Mapping[str, str],
    error: str,
    forced_status: StrategyLabRunStatus | None = None,
) -> StrategyLabRunItem:
    status = forced_status or _status_from_error(error)
    return StrategyLabRunItem(
        lab_run_id=lab_run_id,
        scenario_id=scenario_id,
        status=status,
        strategy=strategy,
        exchange=request.exchange,
        symbol=symbol,
        timeframe=timeframe,
        mode=request.mode,
        label=request.label,
        tags=dict(tags),
        summary=StrategyLabRunSummary(status=status),
        error=error,
        created_at=_now_utc(),
    )


def _summary_from_detailed(detailed: BacktestDetailedRunResult) -> StrategyLabRunSummary:
    result = detailed.run_result.result
    metrics = result.metrics if result is not None else {}
    trades = detailed.trades
    total_trades = _int_metric(metrics, "trades_count", default=len(trades))
    return StrategyLabRunSummary(
        status="completed",
        total_trades=total_trades,
        win_rate=_rate_metric(metrics, "winrate", total_trades),
        profit_factor=_float_metric(metrics, "profit_factor"),
        expectancy_r=_float_metric(metrics, "expectancy_r"),
        avg_r=_average_realized_r(trades),
        max_drawdown=_float_metric(metrics, "max_drawdown_pct"),
        avg_bars_in_trade=_float_metric(metrics, "avg_bars_in_trade") if total_trades > 0 else None,
        stop_rate=_rate_metric(metrics, "stop_rate", total_trades),
        tp1_rate=_rate_metric(metrics, "tp1_rate", total_trades),
        final_target_rate=_final_target_rate(trades),
        fees_paid=_decimal_metric(metrics, "fees_total", default=_sum_decimal_trade_attr(trades, "fees")),
        slippage_paid=_decimal_metric(
            metrics,
            "slippage_total",
            default=_sum_decimal_trade_attr(trades, "slippage"),
        ),
        risk_rejections=detailed.risk_rejections,
        execution_rejections=detailed.execution_rejections,
        fallback_used_count=_count_truthy_metadata_flag(trades, "fallback_used"),
        incomplete_trade_plan_count=_count_false_metadata_flag(trades, "trade_plan_complete"),
        signals_seen=detailed.signals_seen,
    )


def _aggregate_run_summaries(items: Sequence[StrategyLabRunItem]) -> StrategyLabRunSummary:
    completed = [item.summary for item in items if item.status == "completed"]
    if not completed:
        return StrategyLabRunSummary(status=_aggregate_status(items))
    total_trades = sum(summary.total_trades or 0 for summary in completed)
    return StrategyLabRunSummary(
        status="completed" if total_trades > 0 else "insufficient_data",
        total_trades=total_trades,
        win_rate=_weighted_rate(completed, "win_rate", total_trades),
        profit_factor=_weighted_rate(completed, "profit_factor", total_trades),
        expectancy_r=_weighted_rate(completed, "expectancy_r", total_trades),
        avg_r=_weighted_rate(completed, "avg_r", total_trades),
        max_drawdown=_max_optional_float(summary.max_drawdown for summary in completed),
        avg_bars_in_trade=_weighted_rate(completed, "avg_bars_in_trade", total_trades),
        stop_rate=_weighted_rate(completed, "stop_rate", total_trades),
        tp1_rate=_weighted_rate(completed, "tp1_rate", total_trades),
        final_target_rate=_weighted_rate(completed, "final_target_rate", total_trades),
        fees_paid=sum((summary.fees_paid or Decimal("0")) for summary in completed),
        slippage_paid=sum((summary.slippage_paid or Decimal("0")) for summary in completed),
        risk_rejections=sum(summary.risk_rejections or 0 for summary in completed),
        execution_rejections=sum(summary.execution_rejections or 0 for summary in completed),
        fallback_used_count=_sum_optional_counts(summary.fallback_used_count for summary in completed),
        incomplete_trade_plan_count=_sum_optional_counts(
            summary.incomplete_trade_plan_count for summary in completed
        ),
        signals_seen=sum(summary.signals_seen or 0 for summary in completed),
    )


def _group_summaries(
    items: Sequence[StrategyLabRunItem],
    field_name: str,
) -> dict[str, StrategyLabRunSummary]:
    grouped: dict[str, list[StrategyLabRunItem]] = {}
    for item in items:
        grouped.setdefault(str(getattr(item, field_name)), []).append(item)
    return {key: _aggregate_run_summaries(group) for key, group in grouped.items()}


def _aggregate_status(items: Sequence[StrategyLabRunItem]) -> StrategyLabRunStatus:
    statuses = {item.status for item in items}
    if not statuses:
        return "no_data"
    if statuses == {"no_data"}:
        return "no_data"
    if statuses <= {"no_data", "insufficient_data"}:
        return "insufficient_data"
    return "failed"


def _weighted_rate(
    summaries: Sequence[StrategyLabRunSummary],
    field_name: str,
    total_trades: int,
) -> float | None:
    if total_trades <= 0:
        return None
    weighted_sum = 0.0
    sample = 0
    for summary in summaries:
        value = getattr(summary, field_name)
        trades = summary.total_trades or 0
        if value is None or trades <= 0:
            continue
        weighted_sum += float(value) * trades
        sample += trades
    if sample == 0:
        return None
    return weighted_sum / sample


def _status_from_error(error: str) -> StrategyLabRunStatus:
    normalized = error.lower()
    if "no_historical_data" in normalized or "no_data" in normalized:
        return "no_data"
    if "not_enough_data" in normalized or "insufficient_data" in normalized:
        return "insufficient_data"
    return "failed"


def _lab_tags(
    *,
    request_tags: Mapping[str, str],
    lab_run_id: UUID,
    mode: str,
    strategy: str,
    symbol: str,
    timeframe: str,
) -> dict[str, str]:
    tags = dict(request_tags)
    tags.update(
        {
            "source": LAB_SOURCE,
            "mode": mode,
            "lab_run_id": str(lab_run_id),
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "candle_state": "closed",
        }
    )
    return tags


def _scenario_id(*, strategy: str, symbol: str, timeframe: str) -> str:
    return f"{strategy}:{symbol}:{timeframe}"


def _fee_rate_from_bps(value: Decimal) -> Decimal:
    return value / Decimal("10000")


def _rate_metric(metrics: Mapping[str, Any], key: str, total_trades: int) -> float | None:
    if total_trades <= 0:
        return None
    return _float_metric(metrics, key)


def _float_metric(metrics: Mapping[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_metric(metrics: Mapping[str, Any], key: str, *, default: int) -> int:
    value = metrics.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decimal_metric(metrics: Mapping[str, Any], key: str, *, default: Decimal) -> Decimal:
    value = metrics.get(key)
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _average_realized_r(trades: Sequence[BacktestSimulatedTrade]) -> float | None:
    values = [float(trade.realized_r) for trade in trades if trade.realized_r is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _final_target_rate(trades: Sequence[BacktestSimulatedTrade]) -> float | None:
    if not trades:
        return None
    known = 0
    hits = 0
    for trade in trades:
        if not trade.targets:
            continue
        final_target = trade.targets[-1]
        if "hit" not in final_target:
            continue
        known += 1
        if bool(final_target.get("hit")):
            hits += 1
    if known == 0:
        return None
    return hits / known


def _sum_decimal_trade_attr(trades: Sequence[BacktestSimulatedTrade], attr: str) -> Decimal:
    total = Decimal("0")
    for trade in trades:
        value = getattr(trade, attr)
        if isinstance(value, Decimal):
            total += value
        elif value is not None:
            total += Decimal(str(value))
    return total


def _count_truthy_metadata_flag(
    trades: Sequence[BacktestSimulatedTrade],
    flag: str,
) -> int | None:
    seen = False
    count = 0
    for trade in trades:
        values = _metadata_values(trade, flag)
        if not values:
            continue
        seen = True
        if any(bool(value) for value in values):
            count += 1
    return count if seen else None


def _count_false_metadata_flag(
    trades: Sequence[BacktestSimulatedTrade],
    flag: str,
) -> int | None:
    seen = False
    count = 0
    for trade in trades:
        values = _metadata_values(trade, flag)
        if not values:
            continue
        seen = True
        if any(value is False for value in values):
            count += 1
    return count if seen else None


def _metadata_values(trade: BacktestSimulatedTrade, flag: str) -> list[Any]:
    values: list[Any] = []
    _collect_metadata_values(trade.trade_plan, flag, values)
    _collect_metadata_values(trade.features_snapshot, flag, values)
    return values


def _collect_metadata_values(value: Any, flag: str, values: list[Any]) -> None:
    if isinstance(value, Mapping):
        if flag in value:
            values.append(value[flag])
        for item in value.values():
            _collect_metadata_values(item, flag, values)
    elif isinstance(value, list):
        for item in value:
            _collect_metadata_values(item, flag, values)


def _sum_optional_counts(values: Iterable[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return sum(known)


def _max_optional_float(values: Iterable[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return max(known)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


strategy_test_lab_service = StrategyTestLabService()
