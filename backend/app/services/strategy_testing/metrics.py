from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median
from typing import Callable, Sequence

from app.services.strategy_testing.schemas import StrategyTestSignal, StrategyTestTrade


MetricValue = float | int | None
MetricCompute = Callable[["StrategyTestMetricContext"], MetricValue]

SUPPORTED_GROUPINGS = (
    "strategy",
    "symbol",
    "timeframe",
    "regime",
    "score_bucket",
    "direction",
    "feed_kind",
    "edge_status",
)

BASE_METRIC_CODES = (
    "trades_count",
    "signals_count",
    "execution_candidates_count",
    "execution_gate_pass_rate",
    "blocked_rate",
    "entry_touch_rate",
    "fill_rate",
    "no_entry_rate",
    "winrate",
    "avg_win_r",
    "avg_loss_r",
    "expectancy_r",
    "expectancy_after_costs_r",
    "profit_factor",
    "max_drawdown_r",
    "max_drawdown_pct",
    "tp1_rate",
    "tp2_rate",
    "stop_rate",
    "invalidation_rate",
    "time_stop_rate",
    "avg_mfe_r",
    "avg_mae_r",
    "median_bars_to_entry",
    "median_bars_to_outcome",
    "avg_bars_in_trade",
    "fees_total",
    "slippage_total",
    "funding_total",
    "risk_rejection_rate",
    "execution_rejection_rate",
    "false_signal_rate",
)

_GROUP_FIELD_MAP = {
    "strategy": "strategy_code",
    "symbol": "symbol",
    "timeframe": "timeframe",
    "direction": "direction",
    "feed_kind": "feed_kind",
    "edge_status": "edge_status",
}

_SIGNAL_SAMPLE_METRICS = {
    "signals_count",
    "execution_candidates_count",
    "execution_gate_pass_rate",
    "blocked_rate",
    "entry_touch_rate",
    "fill_rate",
    "no_entry_rate",
    "risk_rejection_rate",
    "execution_rejection_rate",
    "false_signal_rate",
    "median_bars_to_entry",
    "median_bars_to_outcome",
}

_STOP_REASONS = {"stop_loss", "breakeven_stop", "trailing_stop", "stop"}
_TARGET_REASONS = {"target", "take_profit", "partial_take_profit"}
_INVALIDATION_REASONS = {"invalidation", "invalidated"}
_FUNDING_COST_KEYS = ("funding_total", "funding_cost", "funding_fee", "funding_paid")


@dataclass(frozen=True)
class StrategyTestMetricContext:
    trades: list[StrategyTestTrade] = field(default_factory=list)
    signals: list[StrategyTestSignal] = field(default_factory=list)


@dataclass(frozen=True)
class MetricDefinition:
    code: str
    label: str
    description: str
    groupings: list[str]
    compute: MetricCompute
    min_sample_size: int = 1

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("metric code must be non-empty")
        if self.min_sample_size < 0:
            raise ValueError("min_sample_size must be non-negative")
        object.__setattr__(self, "groupings", list(self.groupings))
        unknown_groupings = [key for key in self.groupings if key not in SUPPORTED_GROUPINGS]
        if unknown_groupings:
            raise ValueError(f"Unknown metric grouping: {unknown_groupings[0]}")


@dataclass(frozen=True)
class MetricResult:
    code: str
    label: str
    value: MetricValue
    sample_size: int
    group: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class MetricRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, MetricDefinition] = {}

    def register(self, definition: MetricDefinition) -> None:
        if definition.code in self._definitions:
            raise ValueError(f"Metric is already registered: {definition.code}")
        self._definitions[definition.code] = definition

    def get(self, code: str) -> MetricDefinition:
        try:
            return self._definitions[code]
        except KeyError as exc:
            raise ValueError(f"Unknown metric code: {code}") from exc

    def list_definitions(self) -> list[MetricDefinition]:
        return list(self._definitions.values())

    def compute(
        self,
        trades: Sequence[StrategyTestTrade],
        signals: Sequence[StrategyTestSignal] | None = None,
        metric_set: Sequence[str] | None = None,
        group_by: Sequence[str] | None = None,
    ) -> list[MetricResult]:
        definitions = self._definitions_for(metric_set)
        groups = _grouped_contexts(trades, signals or [], group_by)
        results: list[MetricResult] = []

        for group, context in groups:
            for definition in definitions:
                value = _normalize_metric_value(definition.compute(context))
                sample_size = _sample_size(definition, context)
                warnings = _metric_warnings(definition, context, value, sample_size)
                results.append(
                    MetricResult(
                        code=definition.code,
                        label=definition.label,
                        value=value,
                        sample_size=sample_size,
                        group=group,
                        warnings=warnings,
                    )
                )
        return results

    def _definitions_for(self, metric_set: Sequence[str] | None) -> list[MetricDefinition]:
        if not metric_set:
            return self.list_definitions()

        definitions: list[MetricDefinition] = []
        seen: set[str] = set()
        for code in metric_set:
            if code in seen:
                continue
            definitions.append(self.get(code))
            seen.add(code)
        return definitions


def build_base_metric_registry() -> MetricRegistry:
    registry = MetricRegistry()
    for definition in base_metric_definitions():
        registry.register(definition)
    return registry


def base_metric_definitions() -> tuple[MetricDefinition, ...]:
    groupings = list(SUPPORTED_GROUPINGS)
    return (
        MetricDefinition(
            code="trades_count",
            label="Trades Count",
            description="Number of simulated trade rows that passed risk and execution rejection checks.",
            groupings=groupings,
            compute=_metric_trades_count,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="signals_count",
            label="Signals Count",
            description="Number of evaluated signal rows.",
            groupings=groupings,
            compute=_metric_signals_count,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="execution_candidates_count",
            label="Execution Candidates Count",
            description="Number of signals admitted to the execution feed.",
            groupings=groupings,
            compute=_metric_execution_candidates_count,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="execution_gate_pass_rate",
            label="Execution Gate Pass Rate",
            description="Share of evaluated signals with a passed execution gate.",
            groupings=groupings,
            compute=_metric_execution_gate_pass_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="blocked_rate",
            label="Blocked Rate",
            description="Share of evaluated signals blocked before execution.",
            groupings=groupings,
            compute=_metric_blocked_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="entry_touch_rate",
            label="Entry Touch Rate",
            description="Share of signals whose entry was touched.",
            groupings=groupings,
            compute=_metric_entry_touch_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="fill_rate",
            label="Fill Rate",
            description="Share of evaluated signals filled by virtual execution.",
            groupings=groupings,
            compute=_metric_fill_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="no_entry_rate",
            label="No Entry Rate",
            description="Share of evaluated signals that never opened a virtual trade.",
            groupings=groupings,
            compute=_metric_no_entry_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="winrate",
            label="Winrate",
            description="Share of realized trades with positive R.",
            groupings=groupings,
            compute=_metric_winrate,
        ),
        MetricDefinition(
            code="avg_win_r",
            label="Average Win R",
            description="Mean positive realized R.",
            groupings=groupings,
            compute=_metric_avg_win_r,
        ),
        MetricDefinition(
            code="avg_loss_r",
            label="Average Loss R",
            description="Mean negative realized R.",
            groupings=groupings,
            compute=_metric_avg_loss_r,
        ),
        MetricDefinition(
            code="expectancy_r",
            label="Expectancy R",
            description="Mean realized R across realized trades.",
            groupings=groupings,
            compute=_metric_expectancy_r,
        ),
        MetricDefinition(
            code="expectancy_after_costs_r",
            label="Expectancy After Costs R",
            description="Mean realized R after modeled fees/slippage/funding.",
            groupings=groupings,
            compute=_metric_expectancy_after_costs_r,
        ),
        MetricDefinition(
            code="profit_factor",
            label="Profit Factor",
            description="Gross positive R divided by absolute gross negative R.",
            groupings=groupings,
            compute=_metric_profit_factor,
        ),
        MetricDefinition(
            code="max_drawdown_r",
            label="Max Drawdown R",
            description="Maximum peak-to-trough cumulative realized R drawdown.",
            groupings=groupings,
            compute=_metric_max_drawdown_r,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="max_drawdown_pct",
            label="Max Drawdown Percent",
            description="Maximum equity curve drawdown percent. Requires equity curve data.",
            groupings=groupings,
            compute=_metric_unavailable,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="tp1_rate",
            label="TP1 Rate",
            description="Share of executed trades with an explicitly hit first target.",
            groupings=groupings,
            compute=_metric_tp1_rate,
        ),
        MetricDefinition(
            code="tp2_rate",
            label="TP2 Rate",
            description="Share of executed trades with an explicitly hit second or later target.",
            groupings=groupings,
            compute=_metric_tp2_rate,
        ),
        MetricDefinition(
            code="stop_rate",
            label="Stop Rate",
            description="Share of executed trades closed by stop-like reasons.",
            groupings=groupings,
            compute=_metric_stop_rate,
        ),
        MetricDefinition(
            code="invalidation_rate",
            label="Invalidation Rate",
            description="Share of rows closed or marked by invalidation.",
            groupings=groupings,
            compute=_metric_invalidation_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="time_stop_rate",
            label="Time Stop Rate",
            description="Share of executed trades closed by time stop.",
            groupings=groupings,
            compute=_metric_time_stop_rate,
        ),
        MetricDefinition(
            code="avg_mfe_r",
            label="Average MFE R",
            description="Mean maximum favorable excursion in R.",
            groupings=groupings,
            compute=_metric_avg_mfe_r,
        ),
        MetricDefinition(
            code="avg_mae_r",
            label="Average MAE R",
            description="Mean maximum adverse excursion in R.",
            groupings=groupings,
            compute=_metric_avg_mae_r,
        ),
        MetricDefinition(
            code="median_bars_to_entry",
            label="Median Bars To Entry",
            description="Median number of bars from signal to entry.",
            groupings=groupings,
            compute=_metric_median_bars_to_entry,
        ),
        MetricDefinition(
            code="median_bars_to_outcome",
            label="Median Bars To Outcome",
            description="Median bars from signal to final outcome.",
            groupings=groupings,
            compute=_metric_median_bars_to_outcome,
        ),
        MetricDefinition(
            code="avg_bars_in_trade",
            label="Average Bars In Trade",
            description="Mean number of bars spent in an executed trade.",
            groupings=groupings,
            compute=_metric_avg_bars_in_trade,
        ),
        MetricDefinition(
            code="fees_total",
            label="Fees Total",
            description="Total modeled fees across rows.",
            groupings=groupings,
            compute=_metric_fees_total,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="slippage_total",
            label="Slippage Total",
            description="Total modeled slippage across rows.",
            groupings=groupings,
            compute=_metric_slippage_total,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="funding_total",
            label="Funding Total",
            description="Total modeled funding when explicit funding cost metadata exists.",
            groupings=groupings,
            compute=_metric_funding_total,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="risk_rejection_rate",
            label="Risk Rejection Rate",
            description="Share of signal rows or legacy trade rows marked as risk rejected.",
            groupings=groupings,
            compute=_metric_risk_rejection_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="execution_rejection_rate",
            label="Execution Rejection Rate",
            description="Share of signal rows or legacy trade rows marked as execution rejected.",
            groupings=groupings,
            compute=_metric_execution_rejection_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="false_signal_rate",
            label="False Signal Rate",
            description="Share of signal rows marked as false/no-entry signals.",
            groupings=groupings,
            compute=_metric_false_signal_rate,
            min_sample_size=0,
        ),
    )


def _grouped_contexts(
    trades: Sequence[StrategyTestTrade],
    signals: Sequence[StrategyTestSignal],
    group_by: Sequence[str] | None,
) -> list[tuple[dict[str, str], StrategyTestMetricContext]]:
    normalized_group_by = _normalize_group_by(group_by)
    aggregate = StrategyTestMetricContext(trades=list(trades), signals=list(signals))
    groups: list[tuple[dict[str, str], StrategyTestMetricContext]] = [({"all": "all"}, aggregate)]
    if not normalized_group_by:
        return groups

    grouped_trades: dict[tuple[str, ...], list[StrategyTestTrade]] = {}
    grouped_signals: dict[tuple[str, ...], list[StrategyTestSignal]] = {}
    group_values: dict[tuple[str, ...], dict[str, str]] = {}

    for trade in trades:
        group = {key: _group_value(trade, key) for key in normalized_group_by}
        group_key = tuple(group[key] for key in normalized_group_by)
        grouped_trades.setdefault(group_key, []).append(trade)
        group_values[group_key] = group

    for signal in signals:
        group = {key: _group_value(signal, key) for key in normalized_group_by}
        group_key = tuple(group[key] for key in normalized_group_by)
        grouped_signals.setdefault(group_key, []).append(signal)
        group_values[group_key] = group

    for group_key in sorted(group_values):
        groups.append(
            (
                group_values[group_key],
                StrategyTestMetricContext(
                    trades=grouped_trades.get(group_key, []),
                    signals=grouped_signals.get(group_key, []),
                ),
            )
        )
    return groups


def _normalize_group_by(group_by: Sequence[str] | None) -> list[str]:
    if not group_by:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for key in group_by:
        value = key.strip()
        if value not in SUPPORTED_GROUPINGS:
            raise ValueError(f"Unknown metric grouping: {key}")
        if value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _group_value(row: StrategyTestTrade | StrategyTestSignal, group_key: str) -> str:
    if group_key == "regime":
        if isinstance(row, StrategyTestSignal):
            value = row.metadata.get("market_regime") or row.metadata.get("regime")
        else:
            value = row.market_regime
    elif group_key == "score_bucket":
        if isinstance(row, StrategyTestSignal):
            value = row.metadata.get("score_bucket")
        else:
            value = row.score_bucket
    else:
        value = getattr(row, _GROUP_FIELD_MAP[group_key], None)
    text = str(value).strip() if value is not None else ""
    return text or "unknown"


def _sample_size(definition: MetricDefinition, context: StrategyTestMetricContext) -> int:
    if definition.code in _SIGNAL_SAMPLE_METRICS and context.signals:
        return len(context.signals)
    return len(context.trades)


def _metric_warnings(
    definition: MetricDefinition,
    context: StrategyTestMetricContext,
    value: MetricValue,
    sample_size: int,
) -> list[str]:
    warnings: list[str] = []
    if sample_size < definition.min_sample_size:
        warnings.append("insufficient_sample")

    code = definition.code
    if code in {
        "signals_count",
        "execution_candidates_count",
        "execution_gate_pass_rate",
        "blocked_rate",
        "entry_touch_rate",
        "fill_rate",
        "no_entry_rate",
        "false_signal_rate",
    } and not context.signals:
        warnings.append("signal_rows_not_available")
    elif code == "max_drawdown_pct" and value is None:
        warnings.append("equity_curve_not_available")
    elif code == "funding_total" and value is None:
        warnings.append("funding_not_modeled")
    elif code in {"winrate", "expectancy_r", "expectancy_after_costs_r"} and value is None:
        warnings.append("no_realized_trades")
    elif code == "avg_win_r" and value is None:
        warnings.append("no_winning_trades")
    elif code == "avg_loss_r" and value is None:
        warnings.append("no_losing_trades")
    elif code == "profit_factor" and value is None:
        if _realized_r_values(context.trades):
            warnings.append("profit_factor_infinite_or_no_losses")
        else:
            warnings.append("no_realized_trades")
    elif code in {"tp1_rate", "tp2_rate"} and value is None:
        warnings.append("target_hits_not_available")
    elif code in {"stop_rate", "time_stop_rate"} and value is None:
        warnings.append("no_executed_trades")
    elif code == "avg_mfe_r" and value is None:
        warnings.append("mfe_not_available")
    elif code == "avg_mae_r" and value is None:
        warnings.append("mae_not_available")
    elif code in {"median_bars_to_entry", "median_bars_to_outcome", "avg_bars_in_trade"} and value is None:
        warnings.append("bars_not_available")

    return _dedupe_strings(warnings)


def _metric_unavailable(_context: StrategyTestMetricContext) -> None:
    return None


def _metric_trades_count(context: StrategyTestMetricContext) -> int:
    return len(_executed_trades(context.trades))


def _metric_signals_count(context: StrategyTestMetricContext) -> int:
    return len(context.signals)


def _metric_execution_candidates_count(context: StrategyTestMetricContext) -> int:
    return sum(1 for signal in context.signals if _is_execution_candidate(signal))


def _metric_execution_gate_pass_rate(context: StrategyTestMetricContext) -> float | None:
    if not context.signals:
        return None
    passed = sum(1 for signal in context.signals if _normalized_reason(signal.gate_status) == "passed")
    return _rate(passed, len(context.signals))


def _metric_blocked_rate(context: StrategyTestMetricContext) -> float | None:
    if not context.signals:
        return None
    blocked = sum(1 for signal in context.signals if _is_blocked_signal(signal))
    return _rate(blocked, len(context.signals))


def _metric_entry_touch_rate(context: StrategyTestMetricContext) -> float | None:
    if not context.signals:
        return None
    return _rate(sum(1 for signal in context.signals if signal.entry_touched), len(context.signals))


def _metric_fill_rate(context: StrategyTestMetricContext) -> float | None:
    if not context.signals:
        return None
    return _rate(sum(1 for signal in context.signals if signal.filled), len(context.signals))


def _metric_no_entry_rate(context: StrategyTestMetricContext) -> float | None:
    if not context.signals:
        return None
    return _rate(sum(1 for signal in context.signals if signal.no_entry), len(context.signals))


def _metric_winrate(context: StrategyTestMetricContext) -> float | None:
    values = _realized_r_values(context.trades)
    if not values:
        return None
    return _rate(sum(1 for value in values if value > 0), len(values))


def _metric_avg_win_r(context: StrategyTestMetricContext) -> float | None:
    return _mean([value for value in _realized_r_values(context.trades) if value > 0])


def _metric_avg_loss_r(context: StrategyTestMetricContext) -> float | None:
    return _mean([value for value in _realized_r_values(context.trades) if value < 0])


def _metric_expectancy_r(context: StrategyTestMetricContext) -> float | None:
    return _mean(_realized_r_values(context.trades))


def _metric_expectancy_after_costs_r(context: StrategyTestMetricContext) -> float | None:
    return _mean(_realized_r_values(context.trades))


def _metric_profit_factor(context: StrategyTestMetricContext) -> float | None:
    values = _realized_r_values(context.trades)
    wins_total = sum(value for value in values if value > 0)
    losses_total = abs(sum(value for value in values if value < 0))
    if losses_total <= 0:
        return None
    return wins_total / losses_total


def _metric_max_drawdown_r(context: StrategyTestMetricContext) -> float:
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in _ordered_realized_r_values(context.trades):
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return max_drawdown


def _metric_tp1_rate(context: StrategyTestMetricContext) -> float | None:
    executed = _executed_trades(context.trades)
    if not executed or not _has_target_hit_metadata(executed):
        return None
    hits = sum(1 for trade in executed if _target_hit(trade, {"tp1", "target_1"}) or _target_reason(trade))
    return _rate(hits, len(executed))


def _metric_tp2_rate(context: StrategyTestMetricContext) -> float | None:
    executed = _executed_trades(context.trades)
    if not executed or not _has_target_hit_metadata(executed):
        return None
    hits = sum(
        1
        for trade in executed
        if _target_hit(trade, {"tp2", "tp3", "target_2", "target_3"})
    )
    return _rate(hits, len(executed))


def _metric_stop_rate(context: StrategyTestMetricContext) -> float | None:
    executed = _executed_trades(context.trades)
    if not executed:
        return None
    hits = sum(1 for trade in executed if _normalized_reason(trade.close_reason) in _STOP_REASONS)
    return _rate(hits, len(executed))


def _metric_invalidation_rate(context: StrategyTestMetricContext) -> float:
    if not context.trades:
        return 0.0
    count = sum(
        1
        for trade in context.trades
        if _normalized_reason(trade.close_reason) in _INVALIDATION_REASONS
        or _normalized_reason(trade.outcome) in _INVALIDATION_REASONS
    )
    return count / len(context.trades)


def _metric_time_stop_rate(context: StrategyTestMetricContext) -> float | None:
    executed = _executed_trades(context.trades)
    if not executed:
        return None
    hits = sum(1 for trade in executed if _normalized_reason(trade.close_reason) == "time_stop")
    return _rate(hits, len(executed))


def _metric_avg_mfe_r(context: StrategyTestMetricContext) -> float | None:
    return _mean([value for value in (_finite_float(trade.mfe_r) for trade in _executed_trades(context.trades)) if value is not None])


def _metric_avg_mae_r(context: StrategyTestMetricContext) -> float | None:
    return _mean([value for value in (_finite_float(trade.mae_r) for trade in _executed_trades(context.trades)) if value is not None])


def _metric_median_bars_to_entry(context: StrategyTestMetricContext) -> float | None:
    signal_values = [signal.bars_to_entry for signal in context.signals if signal.bars_to_entry is not None]
    if signal_values:
        return _median(signal_values)
    return _median([trade.bars_to_entry for trade in _executed_trades(context.trades) if trade.bars_to_entry is not None])


def _metric_median_bars_to_outcome(context: StrategyTestMetricContext) -> float | None:
    signal_values = [signal.bars_to_outcome for signal in context.signals if signal.bars_to_outcome is not None]
    if signal_values:
        return _median(signal_values)
    values = [
        trade.bars_to_entry + trade.bars_in_trade
        for trade in _executed_trades(context.trades)
        if trade.bars_to_entry is not None and trade.bars_in_trade is not None
    ]
    return _median(values)


def _metric_avg_bars_in_trade(context: StrategyTestMetricContext) -> float | None:
    return _mean([trade.bars_in_trade for trade in _executed_trades(context.trades) if trade.bars_in_trade is not None])


def _metric_fees_total(context: StrategyTestMetricContext) -> float:
    return _decimal_to_float(sum((trade.fees for trade in context.trades), Decimal("0")))


def _metric_slippage_total(context: StrategyTestMetricContext) -> float:
    return _decimal_to_float(sum((trade.slippage for trade in context.trades), Decimal("0")))


def _metric_funding_total(context: StrategyTestMetricContext) -> float | None:
    if not context.trades:
        return 0.0

    values: list[Decimal] = []
    for trade in context.trades:
        value = _funding_cost_value(trade)
        if value is None:
            return None
        values.append(value)
    return _decimal_to_float(sum(values, Decimal("0")))


def _metric_risk_rejection_rate(context: StrategyTestMetricContext) -> float:
    if context.signals:
        return sum(1 for signal in context.signals if signal.risk_rejected) / len(context.signals)
    if not context.trades:
        return 0.0
    return sum(1 for trade in context.trades if trade.risk_rejected) / len(context.trades)


def _metric_execution_rejection_rate(context: StrategyTestMetricContext) -> float:
    if context.signals:
        return sum(1 for signal in context.signals if signal.execution_rejected) / len(context.signals)
    if not context.trades:
        return 0.0
    return sum(1 for trade in context.trades if trade.execution_rejected) / len(context.trades)


def _metric_false_signal_rate(context: StrategyTestMetricContext) -> float | None:
    if not context.signals:
        return None
    false_count = sum(1 for signal in context.signals if signal.no_entry or _normalized_reason(signal.outcome) == "false_signal")
    return _rate(false_count, len(context.signals))


def _is_execution_candidate(signal: StrategyTestSignal) -> bool:
    feed_kind = _normalized_reason(signal.feed_kind)
    if feed_kind in {"blocked", "blocked_signal"}:
        return False
    return feed_kind in {"execution_signal", "execution_candidate"} or _normalized_reason(signal.gate_status) == "passed"


def _is_blocked_signal(signal: StrategyTestSignal) -> bool:
    return _normalized_reason(signal.feed_kind) in {"blocked", "blocked_signal"} or _normalized_reason(signal.gate_status) == "blocked"


def _executed_trades(trades: Sequence[StrategyTestTrade]) -> list[StrategyTestTrade]:
    return [trade for trade in trades if not trade.risk_rejected and not trade.execution_rejected]


def _realized_r_values(trades: Sequence[StrategyTestTrade]) -> list[float]:
    return [
        value
        for value in (_finite_float(trade.realized_r) for trade in _executed_trades(trades))
        if value is not None
    ]


def _ordered_realized_r_values(trades: Sequence[StrategyTestTrade]) -> list[float]:
    ordered = sorted(
        _executed_trades(trades),
        key=lambda trade: (trade.exit_time or trade.entry_time, trade.trade_id),
    )
    return [
        value
        for value in (_finite_float(trade.realized_r) for trade in ordered)
        if value is not None
    ]


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return count / total


def _mean(values: Sequence[float | int]) -> float | None:
    if not values:
        return None
    return sum(float(value) for value in values) / len(values)


def _median(values: Sequence[float | int]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _has_target_hit_metadata(trades: Sequence[StrategyTestTrade]) -> bool:
    return any(any(isinstance(target, dict) and "hit" in target for target in trade.targets) for trade in trades)


def _target_hit(trade: StrategyTestTrade, labels: set[str]) -> bool:
    for target in trade.targets:
        if not isinstance(target, dict):
            continue
        label = _normalized_reason(target.get("label"))
        if label in labels and bool(target.get("hit")):
            return True
    return False


def _target_reason(trade: StrategyTestTrade) -> bool:
    return _normalized_reason(trade.close_reason) in _TARGET_REASONS


def _normalized_reason(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _funding_cost_value(trade: StrategyTestTrade) -> Decimal | None:
    for source in (trade.features_snapshot, trade.trade_plan):
        for key in _FUNDING_COST_KEYS:
            if key in source:
                return _decimal_from(source[key])
    return None


def _decimal_from(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _decimal_to_float(value: Decimal) -> float:
    try:
        return float(value)
    except (OverflowError, ValueError):
        return math.inf


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_metric_value(value: object) -> MetricValue:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        value = _decimal_to_float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
