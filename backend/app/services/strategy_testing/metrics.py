from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median
from typing import Callable, Sequence

from app.services.strategy_testing.schemas import StrategyTestTrade


MetricValue = float | int | None
MetricCompute = Callable[[Sequence[StrategyTestTrade]], MetricValue]

SUPPORTED_GROUPINGS = (
    "strategy",
    "symbol",
    "timeframe",
    "regime",
    "score_bucket",
    "direction",
)

BASE_METRIC_CODES = (
    "trades_count",
    "signals_count",
    "entry_touch_rate",
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
    "regime": "market_regime",
    "score_bucket": "score_bucket",
    "direction": "direction",
}

_STOP_REASONS = {"stop_loss", "breakeven_stop", "trailing_stop", "stop"}
_TARGET_REASONS = {"target", "take_profit", "partial_take_profit"}
_INVALIDATION_REASONS = {"invalidation", "invalidated"}
_FUNDING_COST_KEYS = ("funding_total", "funding_cost", "funding_fee", "funding_paid")


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
        metric_set: Sequence[str] | None = None,
        group_by: Sequence[str] | None = None,
    ) -> list[MetricResult]:
        definitions = self._definitions_for(metric_set)
        groups = _grouped_trades(trades, group_by)
        results: list[MetricResult] = []

        for group, group_trades in groups:
            for definition in definitions:
                value = _normalize_metric_value(definition.compute(group_trades))
                warnings = _metric_warnings(definition, group_trades, value)
                results.append(
                    MetricResult(
                        code=definition.code,
                        label=definition.label,
                        value=value,
                        sample_size=len(group_trades),
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
            description="Number of evaluated signals. Not derivable from trade rows alone.",
            groupings=groupings,
            compute=_metric_unavailable,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="entry_touch_rate",
            label="Entry Touch Rate",
            description="Share of signals whose entry was touched. Requires signal rows, not only trade rows.",
            groupings=groupings,
            compute=_metric_unavailable,
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
            description="Expectancy after costs in R. Requires cost-to-risk conversion metadata.",
            groupings=groupings,
            compute=_metric_unavailable,
            min_sample_size=0,
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
            description="Median bars from signal to final outcome when entry and holding bars are available.",
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
            description="Share of rows marked as risk rejected.",
            groupings=groupings,
            compute=_metric_risk_rejection_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="execution_rejection_rate",
            label="Execution Rejection Rate",
            description="Share of rows marked as execution rejected.",
            groupings=groupings,
            compute=_metric_execution_rejection_rate,
            min_sample_size=0,
        ),
        MetricDefinition(
            code="false_signal_rate",
            label="False Signal Rate",
            description="Share of false signals. Requires signal rows and false-signal labeling.",
            groupings=groupings,
            compute=_metric_unavailable,
            min_sample_size=0,
        ),
    )


def _grouped_trades(
    trades: Sequence[StrategyTestTrade],
    group_by: Sequence[str] | None,
) -> list[tuple[dict[str, str], list[StrategyTestTrade]]]:
    normalized_group_by = _normalize_group_by(group_by)
    groups: list[tuple[dict[str, str], list[StrategyTestTrade]]] = [({"all": "all"}, list(trades))]
    if not normalized_group_by:
        return groups

    grouped: dict[tuple[str, ...], list[StrategyTestTrade]] = {}
    group_values: dict[tuple[str, ...], dict[str, str]] = {}
    for trade in trades:
        group = {key: _group_value(trade, key) for key in normalized_group_by}
        group_key = tuple(group[key] for key in normalized_group_by)
        grouped.setdefault(group_key, []).append(trade)
        group_values[group_key] = group

    for group_key in sorted(grouped):
        groups.append((group_values[group_key], grouped[group_key]))
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


def _group_value(trade: StrategyTestTrade, group_key: str) -> str:
    value = getattr(trade, _GROUP_FIELD_MAP[group_key], None)
    text = str(value).strip() if value is not None else ""
    return text or "unknown"


def _metric_warnings(
    definition: MetricDefinition,
    trades: Sequence[StrategyTestTrade],
    value: MetricValue,
) -> list[str]:
    warnings: list[str] = []
    if len(trades) < definition.min_sample_size:
        warnings.append("insufficient_sample")

    code = definition.code
    if code == "signals_count" and value is None:
        warnings.append("signals_count_not_available_from_trade_rows")
    elif code == "entry_touch_rate" and value is None:
        warnings.append("signals_count_not_available_from_trade_rows")
    elif code == "expectancy_after_costs_r" and value is None:
        warnings.append("costs_r_not_available")
    elif code == "max_drawdown_pct" and value is None:
        warnings.append("equity_curve_not_available")
    elif code == "funding_total" and value is None:
        warnings.append("funding_not_modeled")
    elif code == "false_signal_rate" and value is None:
        warnings.append("false_signal_not_modeled")
    elif code in {"winrate", "expectancy_r"} and value is None:
        warnings.append("no_realized_trades")
    elif code == "avg_win_r" and value is None:
        warnings.append("no_winning_trades")
    elif code == "avg_loss_r" and value is None:
        warnings.append("no_losing_trades")
    elif code == "profit_factor" and value is None:
        if _realized_r_values(trades):
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


def _metric_unavailable(_trades: Sequence[StrategyTestTrade]) -> None:
    return None


def _metric_trades_count(trades: Sequence[StrategyTestTrade]) -> int:
    return len(_executed_trades(trades))


def _metric_winrate(trades: Sequence[StrategyTestTrade]) -> float | None:
    values = _realized_r_values(trades)
    if not values:
        return None
    return _rate(sum(1 for value in values if value > 0), len(values))


def _metric_avg_win_r(trades: Sequence[StrategyTestTrade]) -> float | None:
    return _mean([value for value in _realized_r_values(trades) if value > 0])


def _metric_avg_loss_r(trades: Sequence[StrategyTestTrade]) -> float | None:
    return _mean([value for value in _realized_r_values(trades) if value < 0])


def _metric_expectancy_r(trades: Sequence[StrategyTestTrade]) -> float | None:
    return _mean(_realized_r_values(trades))


def _metric_profit_factor(trades: Sequence[StrategyTestTrade]) -> float | None:
    values = _realized_r_values(trades)
    wins_total = sum(value for value in values if value > 0)
    losses_total = abs(sum(value for value in values if value < 0))
    if losses_total <= 0:
        return None
    return wins_total / losses_total


def _metric_max_drawdown_r(trades: Sequence[StrategyTestTrade]) -> float:
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in _ordered_realized_r_values(trades):
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return max_drawdown


def _metric_tp1_rate(trades: Sequence[StrategyTestTrade]) -> float | None:
    executed = _executed_trades(trades)
    if not executed or not _has_target_hit_metadata(executed):
        return None
    hits = sum(1 for trade in executed if _target_hit(trade, {"tp1", "target_1"}) or _target_reason(trade))
    return _rate(hits, len(executed))


def _metric_tp2_rate(trades: Sequence[StrategyTestTrade]) -> float | None:
    executed = _executed_trades(trades)
    if not executed or not _has_target_hit_metadata(executed):
        return None
    hits = sum(
        1
        for trade in executed
        if _target_hit(trade, {"tp2", "tp3", "target_2", "target_3"})
    )
    return _rate(hits, len(executed))


def _metric_stop_rate(trades: Sequence[StrategyTestTrade]) -> float | None:
    executed = _executed_trades(trades)
    if not executed:
        return None
    hits = sum(1 for trade in executed if _normalized_reason(trade.close_reason) in _STOP_REASONS)
    return _rate(hits, len(executed))


def _metric_invalidation_rate(trades: Sequence[StrategyTestTrade]) -> float:
    if not trades:
        return 0.0
    count = sum(
        1
        for trade in trades
        if _normalized_reason(trade.close_reason) in _INVALIDATION_REASONS
        or _normalized_reason(trade.outcome) in _INVALIDATION_REASONS
    )
    return count / len(trades)


def _metric_time_stop_rate(trades: Sequence[StrategyTestTrade]) -> float | None:
    executed = _executed_trades(trades)
    if not executed:
        return None
    hits = sum(1 for trade in executed if _normalized_reason(trade.close_reason) == "time_stop")
    return _rate(hits, len(executed))


def _metric_avg_mfe_r(trades: Sequence[StrategyTestTrade]) -> float | None:
    return _mean([value for value in (_finite_float(trade.mfe_r) for trade in _executed_trades(trades)) if value is not None])


def _metric_avg_mae_r(trades: Sequence[StrategyTestTrade]) -> float | None:
    return _mean([value for value in (_finite_float(trade.mae_r) for trade in _executed_trades(trades)) if value is not None])


def _metric_median_bars_to_entry(trades: Sequence[StrategyTestTrade]) -> float | None:
    return _median([trade.bars_to_entry for trade in _executed_trades(trades) if trade.bars_to_entry is not None])


def _metric_median_bars_to_outcome(trades: Sequence[StrategyTestTrade]) -> float | None:
    values = [
        trade.bars_to_entry + trade.bars_in_trade
        for trade in _executed_trades(trades)
        if trade.bars_to_entry is not None and trade.bars_in_trade is not None
    ]
    return _median(values)


def _metric_avg_bars_in_trade(trades: Sequence[StrategyTestTrade]) -> float | None:
    return _mean([trade.bars_in_trade for trade in _executed_trades(trades) if trade.bars_in_trade is not None])


def _metric_fees_total(trades: Sequence[StrategyTestTrade]) -> float:
    return _decimal_to_float(sum((trade.fees for trade in trades), Decimal("0")))


def _metric_slippage_total(trades: Sequence[StrategyTestTrade]) -> float:
    return _decimal_to_float(sum((trade.slippage for trade in trades), Decimal("0")))


def _metric_funding_total(trades: Sequence[StrategyTestTrade]) -> float | None:
    if not trades:
        return 0.0

    values: list[Decimal] = []
    for trade in trades:
        value = _funding_cost_value(trade)
        if value is None:
            return None
        values.append(value)
    return _decimal_to_float(sum(values, Decimal("0")))


def _metric_risk_rejection_rate(trades: Sequence[StrategyTestTrade]) -> float:
    if not trades:
        return 0.0
    return sum(1 for trade in trades if trade.risk_rejected) / len(trades)


def _metric_execution_rejection_rate(trades: Sequence[StrategyTestTrade]) -> float:
    if not trades:
        return 0.0
    return sum(1 for trade in trades if trade.execution_rejected) / len(trades)


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
