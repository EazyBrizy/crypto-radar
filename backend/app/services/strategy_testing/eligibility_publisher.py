from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence
from uuid import UUID

from app.core.config import settings
from app.services.strategy_testing.eligibility_profiles import (
    PostgresStrategyExecutionEligibilityProfileStore,
    StrategyExecutionEligibilityProfileRecord,
    StrategyExecutionEligibilityProfileStore,
)
from app.services.strategy_testing.metrics import MetricResult, build_base_metric_registry
from app.services.strategy_testing.schemas import (
    StrategyTestCalibrationPublishResponse,
    StrategyTestCalibrationSource,
    StrategyTestRunDetailResponse,
    StrategyTestSignal,
    StrategyTestTrade,
)


class EligibilityPublisherRunStore(Protocol):
    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        ...


class EligibilityPublisherAnalyticsStore(Protocol):
    def list_trades(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestTrade]:
        ...

    def list_signals(self, run_id: UUID, limit: int = 500, offset: int = 0) -> list[StrategyTestSignal]:
        ...


@dataclass(frozen=True)
class EligibilityThresholds:
    min_sample_size: int
    min_expectancy_after_costs_r: float
    min_profit_factor: float
    min_entry_touch_rate: float
    max_no_entry_rate: float
    max_drawdown_r: float


@dataclass(frozen=True, order=True)
class _ProfileKey:
    strategy_code: str
    exchange: str
    symbol_scope: str
    timeframe: str
    market_regime: str
    score_bucket: str
    direction: str


class StrategyTestEligibilityPublisher:
    def __init__(
        self,
        *,
        run_store: EligibilityPublisherRunStore,
        analytics_store: EligibilityPublisherAnalyticsStore,
        profile_store: StrategyExecutionEligibilityProfileStore | None = None,
        thresholds: dict[str, float | int] | EligibilityThresholds | None = None,
    ) -> None:
        self._run_store = run_store
        self._analytics_store = analytics_store
        self.profile_store = profile_store or PostgresStrategyExecutionEligibilityProfileStore()
        self._thresholds = _thresholds(thresholds)
        self._metric_registry = build_base_metric_registry()

    def publish_run(self, run_id: UUID) -> StrategyTestCalibrationPublishResponse:
        run_detail = self._run_store.get_run(run_id)
        if run_detail is None:
            raise ValueError(f"Strategy test run is not found: {run_id}")
        run = run_detail.run
        if run.status != "completed":
            raise ValueError("Strategy test calibration can only be published from a completed run.")

        source = _source_from_run(run.requested_matrix)
        signals = self._analytics_store.list_signals(run_id, limit=5000, offset=0)
        trades = self._analytics_store.list_trades(run_id, limit=5000, offset=0)
        profiles = [_profile_from_group(key, group_signals, group_trades, source, run_id, self._thresholds, self._metric_registry.compute(
            group_trades,
            signals=group_signals,
        )) for key, group_signals, group_trades in _group_rows(signals, trades)]
        updated = self.profile_store.upsert_profiles(profiles)
        eligible_count = sum(1 for profile in updated if profile.eligible)
        blocked_count = len(updated) - eligible_count
        return StrategyTestCalibrationPublishResponse(
            run_id=run_id,
            source=source,
            profiles_updated=len(updated),
            eligible_count=eligible_count,
            blocked_count=blocked_count,
        )


def _profile_from_group(
    key: _ProfileKey,
    signals: Sequence[StrategyTestSignal],
    trades: Sequence[StrategyTestTrade],
    source: StrategyTestCalibrationSource,
    run_id: UUID,
    thresholds: EligibilityThresholds,
    metrics: Sequence[MetricResult],
) -> StrategyExecutionEligibilityProfileRecord:
    metric_map = {metric.code: metric for metric in metrics if metric.group == {"all": "all"}}
    values = {code: _metric_value(metric_map, code) for code in _metric_codes()}
    sample_size = int(values["trades_count"] or 0)
    signals_count = int(values["signals_count"] or len(signals))
    trades_count = int(values["trades_count"] or len(trades))
    expectancy_after_costs_r = _float_or_none(values["expectancy_after_costs_r"])
    profit_factor = _float_or_none(values["profit_factor"])
    entry_touch_rate = _float_or_none(values["entry_touch_rate"])
    no_entry_rate = _float_or_none(values["no_entry_rate"])
    max_drawdown_r = _float_or_none(values["max_drawdown_r"])
    eligible, reason_code, reason = _evaluate_profile(
        sample_size=sample_size,
        expectancy_after_costs_r=expectancy_after_costs_r,
        profit_factor=profit_factor,
        entry_touch_rate=entry_touch_rate,
        no_entry_rate=no_entry_rate,
        max_drawdown_r=max_drawdown_r,
        thresholds=thresholds,
    )
    profile_metrics = {
        **values,
        "signals_count": signals_count,
        "trades_count": trades_count,
        "validation_sample_size": sample_size,
        "validation_expectancy_r": expectancy_after_costs_r,
        "validation_profit_factor": profit_factor,
        "validation_max_drawdown_r": max_drawdown_r,
        "source": source,
        "run_ids": [str(run_id)],
    }
    return StrategyExecutionEligibilityProfileRecord(
        strategy_code=key.strategy_code,
        exchange=key.exchange,
        symbol_scope=key.symbol_scope,
        timeframe=key.timeframe,
        market_regime=key.market_regime,
        score_bucket=key.score_bucket,
        direction=key.direction,
        eligible=eligible,
        source=source,
        metrics=profile_metrics,
        sample_size=sample_size,
        expectancy_after_costs_r=expectancy_after_costs_r,
        profit_factor=profit_factor,
        entry_touch_rate=entry_touch_rate,
        no_entry_rate=no_entry_rate,
        max_drawdown_r=max_drawdown_r,
        run_ids=[str(run_id)],
        reason_code=reason_code,
        reason=reason,
    )


def _group_rows(
    signals: Sequence[StrategyTestSignal],
    trades: Sequence[StrategyTestTrade],
) -> list[tuple[_ProfileKey, list[StrategyTestSignal], list[StrategyTestTrade]]]:
    groups: dict[_ProfileKey, tuple[list[StrategyTestSignal], list[StrategyTestTrade]]] = {}
    for signal in signals:
        key = _signal_key(signal)
        groups.setdefault(key, ([], []))[0].append(signal)
    for trade in trades:
        key = _trade_key(trade)
        groups.setdefault(key, ([], []))[1].append(trade)
    return [(key, values[0], values[1]) for key, values in sorted(groups.items(), key=lambda item: item[0])]


def _signal_key(signal: StrategyTestSignal) -> _ProfileKey:
    return _ProfileKey(
        strategy_code=_dimension(signal.strategy_code),
        exchange=_dimension(signal.exchange).lower(),
        symbol_scope=_symbol_scope(signal.symbol),
        timeframe=_dimension(signal.timeframe),
        market_regime=_dimension(signal.metadata.get("market_regime") or signal.metadata.get("regime")),
        score_bucket=_dimension(signal.metadata.get("score_bucket") or _score_bucket(signal.signal_score)),
        direction=_direction(signal.direction),
    )


def _trade_key(trade: StrategyTestTrade) -> _ProfileKey:
    return _ProfileKey(
        strategy_code=_dimension(trade.strategy_code),
        exchange=_dimension(trade.exchange).lower(),
        symbol_scope=_symbol_scope(trade.symbol),
        timeframe=_dimension(trade.timeframe),
        market_regime=_dimension(trade.market_regime),
        score_bucket=_dimension(trade.score_bucket),
        direction=_direction(trade.direction),
    )


def _evaluate_profile(
    *,
    sample_size: int,
    expectancy_after_costs_r: float | None,
    profit_factor: float | None,
    entry_touch_rate: float | None,
    no_entry_rate: float | None,
    max_drawdown_r: float | None,
    thresholds: EligibilityThresholds,
) -> tuple[bool, str, str]:
    if sample_size < thresholds.min_sample_size:
        return False, "insufficient_sample", "Strategy test sample size is below the execution threshold."
    if expectancy_after_costs_r is None or expectancy_after_costs_r < thresholds.min_expectancy_after_costs_r:
        return False, "expectancy_below_threshold", "Strategy test expectancy after costs is below threshold."
    if profit_factor is None or profit_factor < thresholds.min_profit_factor:
        return False, "profit_factor_below_threshold", "Strategy test profit factor is below threshold."
    if entry_touch_rate is not None and entry_touch_rate < thresholds.min_entry_touch_rate:
        return False, "entry_touch_rate_below_threshold", "Strategy test entry touch rate is below threshold."
    if no_entry_rate is not None and no_entry_rate > thresholds.max_no_entry_rate:
        return False, "no_entry_rate_above_threshold", "Strategy test no-entry rate is above threshold."
    if max_drawdown_r is not None and max_drawdown_r > thresholds.max_drawdown_r:
        return False, "drawdown_above_threshold", "Strategy test drawdown is above threshold."
    return True, "eligible", "Strategy test metrics pass execution eligibility thresholds."


def _thresholds(value: dict[str, float | int] | EligibilityThresholds | None) -> EligibilityThresholds:
    if isinstance(value, EligibilityThresholds):
        return value
    data = value or {}
    return EligibilityThresholds(
        min_sample_size=int(data.get("min_sample_size", settings.execution_edge_min_sample_size)),
        min_expectancy_after_costs_r=float(
            data.get("min_expectancy_after_costs_r", settings.execution_edge_min_expectancy_after_costs_r)
        ),
        min_profit_factor=float(data.get("min_profit_factor", settings.execution_edge_min_profit_factor)),
        min_entry_touch_rate=float(data.get("min_entry_touch_rate", settings.execution_edge_min_entry_touch_rate)),
        max_no_entry_rate=float(data.get("max_no_entry_rate", settings.execution_edge_max_no_entry_rate)),
        max_drawdown_r=float(data.get("max_drawdown_r", settings.execution_max_validation_drawdown_r)),
    )


def _source_from_run(requested_matrix: dict[str, Any]) -> StrategyTestCalibrationSource:
    value = requested_matrix.get("test_type")
    if value == "forward_virtual":
        return "forward_virtual"
    return "historical_backtest"


def _metric_codes() -> tuple[str, ...]:
    return (
        "signals_count",
        "trades_count",
        "entry_touch_rate",
        "fill_rate",
        "no_entry_rate",
        "winrate",
        "expectancy_r",
        "expectancy_after_costs_r",
        "profit_factor",
        "max_drawdown_r",
        "risk_rejection_rate",
        "execution_rejection_rate",
    )


def _metric_value(metric_map: dict[str, MetricResult], code: str) -> float | int | None:
    result = metric_map.get(code)
    return result.value if result is not None else None


def _float_or_none(value: float | int | None) -> float | None:
    return None if value is None else float(value)


def _dimension(value: object) -> str:
    text = str(value or "unknown").strip()
    return text or "unknown"


def _symbol_scope(symbol: object) -> str:
    return _dimension(symbol).replace("/", "").replace(":PERP", "").upper()


def _direction(value: object) -> str:
    text = _dimension(value).lower()
    if text in {"long", "short"}:
        return text
    return text


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    value = max(0.0, min(100.0, float(score)))
    if value < 50:
        return "0-49"
    if value < 60:
        return "50-59"
    if value < 70:
        return "60-69"
    if value < 80:
        return "70-79"
    if value < 90:
        return "80-89"
    return "90-100"
