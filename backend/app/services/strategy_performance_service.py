from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Any, Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.clickhouse_client import create_clickhouse_client
from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.pending_entry_reason import VIRTUAL_EXECUTION_REJECTED
from app.models.signal import SignalOutcome, TradingSignal
from app.schemas.strategy_performance import (
    EdgeProfileConfidence,
    EdgeProfileSource,
    ScoreBucket,
    StrategyEdgeProfile,
    StrategyPerformanceDaily,
)
from app.services.strategy_testing.eligibility_profiles import (
    PostgresStrategyExecutionEligibilityProfileStore,
    StrategyExecutionEligibilityProfileRecord,
    StrategyExecutionEligibilityProfileStore,
)

logger = logging.getLogger(__name__)

TARGET_STATUSES = {"tp1", "tp2", "tp3"}

STRATEGY_PERFORMANCE_DAILY_DDL = """
CREATE TABLE IF NOT EXISTS analytics.strategy_performance_daily
(
    date Date,
    strategy_code LowCardinality(String),
    strategy_version String,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    market_regime LowCardinality(String),
    score_bucket LowCardinality(String),
    direction LowCardinality(String),
    signals_count UInt64,
    wins_count UInt64,
    losses_count UInt64,
    pending_armed_count UInt64,
    filled_count UInt64,
    no_entry_count UInt64,
    execution_rejected_count UInt64,
    avg_rr Float64,
    avg_pnl_pct Float64,
    max_drawdown_pct Float64,
    sample_size UInt64,
    trades_count UInt64,
    entry_touch_rate Float64,
    fill_rate Float64,
    no_entry_rate Float64,
    execution_rejected_rate Float64,
    winrate Float64,
    tp1_rate Float64,
    tp2_rate Float64,
    stop_rate Float64,
    invalidation_rate Float64,
    avg_win_r Float64,
    avg_loss_r Float64,
    expectancy_r Float64,
    profit_factor Nullable(Float64),
    max_drawdown_r Float64,
    median_bars_to_entry Nullable(Float64),
    median_bars_to_outcome Nullable(Float64),
    avg_mfe_r Float64,
    avg_mae_r Float64,
    fees_bps Float64,
    slippage_bps Float64,
    updated_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(date)
ORDER BY (
    strategy_code,
    exchange,
    symbol,
    timeframe,
    strategy_version,
    market_regime,
    score_bucket,
    direction,
    date
)
"""

STRATEGY_PERFORMANCE_DAILY_ALTERS = [
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS market_regime LowCardinality(String) DEFAULT 'unknown'",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS score_bucket LowCardinality(String) DEFAULT '0-49'",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS direction LowCardinality(String) DEFAULT 'long'",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS sample_size UInt64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS trades_count UInt64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS pending_armed_count UInt64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS filled_count UInt64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS no_entry_count UInt64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS execution_rejected_count UInt64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS entry_touch_rate Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS fill_rate Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS no_entry_rate Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS execution_rejected_rate Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS winrate Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS tp1_rate Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS tp2_rate Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS stop_rate Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS invalidation_rate Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS avg_win_r Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS avg_loss_r Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS expectancy_r Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS profit_factor Nullable(Float64)",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS max_drawdown_r Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS median_bars_to_entry Nullable(Float64)",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS median_bars_to_outcome Nullable(Float64)",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS avg_mfe_r Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS avg_mae_r Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS fees_bps Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS slippage_bps Float64 DEFAULT 0",
    "ALTER TABLE analytics.strategy_performance_daily ADD COLUMN IF NOT EXISTS updated_at DateTime64(3, 'UTC') DEFAULT now64(3)",
]


@dataclass(frozen=True)
class StrategyPerformanceOutcome:
    date: date
    exchange: str
    symbol: str
    timeframe: str
    strategy: str
    strategy_version: str
    market_regime: str
    score_bucket: ScoreBucket
    direction: str
    status: str
    outcome: str
    realized_r: float
    mfe_r: float
    mae_r: float
    bars_to_entry: int | None = None
    bars_to_outcome: int | None = None
    fees_bps: float = 0.0
    slippage_bps: float = 0.0
    closed_at: datetime | None = None
    pending_entry_reason_code: str | None = None


@dataclass(frozen=True)
class StrategyPerformanceProfileQuery:
    strategy: str
    exchange: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    market_regime: str | None = None
    score_bucket: ScoreBucket | None = None
    direction: str | None = None


@dataclass(frozen=True)
class StrategyPerformanceSummary:
    sample_size: int
    trades_count: int
    signals_count: int
    wins_count: int
    losses_count: int
    entry_touch_rate: float
    winrate: float
    tp1_rate: float
    tp2_rate: float
    stop_rate: float
    invalidation_rate: float
    avg_win_r: float
    avg_loss_r: float
    expectancy_r: float
    profit_factor: float | None
    max_drawdown_r: float
    median_bars_to_entry: float | None
    median_bars_to_outcome: float | None
    avg_mfe_r: float
    avg_mae_r: float
    fees_bps: float
    slippage_bps: float
    pending_armed_count: int = 0
    filled_count: int = 0
    no_entry_count: int = 0
    execution_rejected_count: int = 0
    fill_rate: float = 0.0
    no_entry_rate: float = 0.0
    execution_rejected_rate: float = 0.0

    @staticmethod
    def empty() -> "StrategyPerformanceSummary":
        return StrategyPerformanceSummary(
            sample_size=0,
            trades_count=0,
            signals_count=0,
            wins_count=0,
            losses_count=0,
            entry_touch_rate=0.0,
            winrate=0.0,
            tp1_rate=0.0,
            tp2_rate=0.0,
            stop_rate=0.0,
            invalidation_rate=0.0,
            avg_win_r=0.0,
            avg_loss_r=0.0,
            expectancy_r=0.0,
            profit_factor=None,
            max_drawdown_r=0.0,
            median_bars_to_entry=None,
            median_bars_to_outcome=None,
            avg_mfe_r=0.0,
            avg_mae_r=0.0,
            fees_bps=0.0,
            slippage_bps=0.0,
            pending_armed_count=0,
            filled_count=0,
            no_entry_count=0,
            execution_rejected_count=0,
            fill_rate=0.0,
            no_entry_rate=0.0,
            execution_rejected_rate=0.0,
        )


class SignalOutcomeSource(Protocol):
    def list_closed_outcomes(self, *, day: date) -> list[StrategyPerformanceOutcome]:
        ...


class StrategyPerformanceStore(Protocol):
    def ensure_schema(self) -> None:
        ...

    def write_daily(self, rows: Sequence[StrategyPerformanceDaily]) -> None:
        ...

    def query_profile(self, query: StrategyPerformanceProfileQuery) -> StrategyPerformanceSummary | None:
        ...


class PostgresSignalOutcomeSource:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def list_closed_outcomes(self, *, day: date) -> list[StrategyPerformanceOutcome]:
        start_at = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end_at = start_at + timedelta(days=1)
        with self._session_factory() as session:
            records = session.scalars(
                select(SignalOutcome)
                .options(joinedload(SignalOutcome.signal).joinedload(TradingSignal.strategy_version))
                .where(
                    SignalOutcome.closed_at >= start_at,
                    SignalOutcome.closed_at < end_at,
                    SignalOutcome.outcome != "open",
                )
                .order_by(SignalOutcome.closed_at.asc(), SignalOutcome.created_at.asc())
            ).all()
            return [_outcome_to_input(record) for record in records]


class ClickHouseStrategyPerformanceStore:
    _columns = [
        "date",
        "strategy_code",
        "strategy_version",
        "exchange",
        "symbol",
        "timeframe",
        "market_regime",
        "score_bucket",
        "direction",
        "signals_count",
        "wins_count",
        "losses_count",
        "pending_armed_count",
        "filled_count",
        "no_entry_count",
        "execution_rejected_count",
        "avg_rr",
        "avg_pnl_pct",
        "max_drawdown_pct",
        "sample_size",
        "trades_count",
        "entry_touch_rate",
        "fill_rate",
        "no_entry_rate",
        "execution_rejected_rate",
        "winrate",
        "tp1_rate",
        "tp2_rate",
        "stop_rate",
        "invalidation_rate",
        "avg_win_r",
        "avg_loss_r",
        "expectancy_r",
        "profit_factor",
        "max_drawdown_r",
        "median_bars_to_entry",
        "median_bars_to_outcome",
        "avg_mfe_r",
        "avg_mae_r",
        "fees_bps",
        "slippage_bps",
        "updated_at",
    ]

    def __init__(self, clickhouse_client_factory: Any = create_clickhouse_client) -> None:
        self._clickhouse_client_factory = clickhouse_client_factory

    def ensure_schema(self) -> None:
        client = self._client()
        try:
            client.command("CREATE DATABASE IF NOT EXISTS analytics")
            client.command(STRATEGY_PERFORMANCE_DAILY_DDL)
            for command in STRATEGY_PERFORMANCE_DAILY_ALTERS:
                client.command(command)
        finally:
            self._close_client(client)

    def write_daily(self, rows: Sequence[StrategyPerformanceDaily]) -> None:
        if not rows:
            return
        client = self._client()
        try:
            client.insert(
                "analytics.strategy_performance_daily",
                [_daily_row_to_clickhouse(row) for row in rows],
                column_names=self._columns,
            )
        finally:
            self._close_client(client)

    def query_profile(self, query: StrategyPerformanceProfileQuery) -> StrategyPerformanceSummary | None:
        where, parameters = _profile_where(query)
        sql = f"""
            SELECT
                sum(sample_size) AS sample_size,
                sum(trades_count) AS trades_count,
                sum(signals_count) AS signals_count,
                sum(wins_count) AS wins_count,
                sum(losses_count) AS losses_count,
                sum(pending_armed_count) AS pending_armed_count,
                sum(filled_count) AS filled_count,
                sum(no_entry_count) AS no_entry_count,
                sum(execution_rejected_count) AS execution_rejected_count,
                if(sum(signals_count) > 0, sum(entry_touch_rate * signals_count) / sum(signals_count), 0) AS entry_touch_rate,
                if(sum(signals_count) > 0, sum(fill_rate * signals_count) / sum(signals_count), 0) AS fill_rate,
                if(sum(signals_count) > 0, sum(no_entry_rate * signals_count) / sum(signals_count), 0) AS no_entry_rate,
                if(sum(signals_count) > 0, sum(execution_rejected_rate * signals_count) / sum(signals_count), 0) AS execution_rejected_rate,
                if(sum(sample_size) > 0, sum(winrate * sample_size) / sum(sample_size), 0) AS winrate,
                if(sum(trades_count) > 0, sum(tp1_rate * trades_count) / sum(trades_count), 0) AS tp1_rate,
                if(sum(trades_count) > 0, sum(tp2_rate * trades_count) / sum(trades_count), 0) AS tp2_rate,
                if(sum(trades_count) > 0, sum(stop_rate * trades_count) / sum(trades_count), 0) AS stop_rate,
                if(sum(signals_count) > 0, sum(invalidation_rate * signals_count) / sum(signals_count), 0) AS invalidation_rate,
                if(sum(wins_count) > 0, sum(avg_win_r * wins_count) / sum(wins_count), 0) AS avg_win_r,
                if(sum(losses_count) > 0, sum(avg_loss_r * losses_count) / sum(losses_count), 0) AS avg_loss_r,
                if(sum(sample_size) > 0, sum(expectancy_r * sample_size) / sum(sample_size), 0) AS expectancy_r,
                if(abs(sum(avg_loss_r * losses_count)) > 0,
                    sum(avg_win_r * wins_count) / abs(sum(avg_loss_r * losses_count)),
                    NULL
                ) AS profit_factor,
                max(max_drawdown_r) AS max_drawdown_r,
                if(sum(trades_count) > 0, sum(ifNull(median_bars_to_entry, 0) * trades_count) / sum(trades_count), NULL) AS median_bars_to_entry,
                if(sum(trades_count) > 0, sum(ifNull(median_bars_to_outcome, 0) * trades_count) / sum(trades_count), NULL) AS median_bars_to_outcome,
                if(sum(trades_count) > 0, sum(avg_mfe_r * trades_count) / sum(trades_count), 0) AS avg_mfe_r,
                if(sum(trades_count) > 0, sum(avg_mae_r * trades_count) / sum(trades_count), 0) AS avg_mae_r,
                if(sum(signals_count) > 0, sum(fees_bps * signals_count) / sum(signals_count), 0) AS fees_bps,
                if(sum(signals_count) > 0, sum(slippage_bps * signals_count) / sum(signals_count), 0) AS slippage_bps
            FROM analytics.strategy_performance_daily
            WHERE {where}
        """
        client = self._client()
        try:
            result = client.query(sql, parameters=parameters)
            rows = result.named_results() if hasattr(result, "named_results") else []
            if not rows:
                return None
            return _summary_from_row(rows[0])
        finally:
            self._close_client(client)

    def _client(self) -> Any:
        return self._clickhouse_client_factory()

    @staticmethod
    def _close_client(client: Any) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()


class StrategyPerformanceService:
    def __init__(
        self,
        *,
        outcome_source: SignalOutcomeSource | None = None,
        performance_store: StrategyPerformanceStore | None = None,
        eligibility_store: StrategyExecutionEligibilityProfileStore | None = None,
        min_sample_size: int | None = None,
    ) -> None:
        self._outcome_source = outcome_source or PostgresSignalOutcomeSource()
        self._performance_store = performance_store or ClickHouseStrategyPerformanceStore()
        self._eligibility_store = eligibility_store
        self._min_sample_size = (
            int(settings.strategy_performance_min_sample_size)
            if min_sample_size is None
            else int(min_sample_size)
        )

    def ensure_schema(self) -> None:
        self._performance_store.ensure_schema()

    def aggregate_daily(
        self,
        *,
        day: date,
        outcomes: Sequence[StrategyPerformanceOutcome] | None = None,
        write: bool = True,
    ) -> list[StrategyPerformanceDaily]:
        source_outcomes = list(outcomes) if outcomes is not None else self._outcome_source.list_closed_outcomes(day=day)
        rows = build_daily_performance(day=day, outcomes=source_outcomes)
        if write:
            self._performance_store.write_daily(rows)
        return rows

    async def get_edge_profile(
        self,
        *,
        strategy: str,
        exchange: str,
        symbol: str,
        timeframe: str,
        market_regime: str | None,
        score: float | None,
        direction: str | None = None,
    ) -> StrategyEdgeProfile:
        normalized_regime = _normalize_dimension(market_regime) if market_regime else None
        score_bucket = score_bucket_for(score) if score is not None else None
        normalized_direction = _direction(direction) if direction else None
        eligibility_profile = await self._get_strategy_test_profile(
            strategy=strategy,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            market_regime=normalized_regime,
            score_bucket=score_bucket,
            direction=normalized_direction,
        )
        if eligibility_profile is not None:
            return _edge_profile_from_eligibility(
                eligibility_profile,
                strategy=strategy,
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                market_regime=normalized_regime,
                score_bucket=score_bucket,
                min_sample_size=self._min_sample_size,
            )
        attempts: list[tuple[EdgeProfileSource, StrategyPerformanceProfileQuery]] = [
            (
                "exact",
                StrategyPerformanceProfileQuery(
                    strategy=strategy,
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    market_regime=normalized_regime,
                    score_bucket=score_bucket,
                    direction=normalized_direction,
                ),
            ),
            (
                "strategy_timeframe_regime",
                StrategyPerformanceProfileQuery(
                    strategy=strategy,
                    timeframe=timeframe,
                    market_regime=normalized_regime,
                    direction=normalized_direction,
                ),
            ),
            ("strategy_global", StrategyPerformanceProfileQuery(strategy=strategy)),
        ]

        last_summary: StrategyPerformanceSummary | None = None
        last_source: EdgeProfileSource = "none"
        for source, query in attempts:
            summary = await asyncio.to_thread(self._performance_store.query_profile, query)
            if summary is None or summary.signals_count == 0:
                continue
            last_summary = summary
            last_source = source
            if summary.sample_size >= self._min_sample_size:
                confidence = "high" if source == "exact" else "medium"
                return _edge_profile(
                    summary,
                    source=source,
                    confidence=confidence,
                    strategy=strategy,
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    market_regime=normalized_regime,
                    score_bucket=score_bucket,
                )

        if last_summary is not None:
            return _edge_profile(
                last_summary,
                source=last_source,
                confidence="low",
                strategy=strategy,
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                market_regime=normalized_regime,
                score_bucket=score_bucket,
            )

        return _edge_profile(
            StrategyPerformanceSummary.empty(),
            source="none",
            confidence="insufficient_sample",
            strategy=strategy,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            market_regime=normalized_regime,
            score_bucket=score_bucket,
        )

    async def _get_strategy_test_profile(
        self,
        *,
        strategy: str,
        exchange: str,
        symbol: str,
        timeframe: str,
        market_regime: str | None,
        score_bucket: ScoreBucket | None,
        direction: str | None,
    ) -> StrategyExecutionEligibilityProfileRecord | None:
        if self._eligibility_store is None:
            return None
        return await asyncio.to_thread(
            self._eligibility_store.find_best_profile,
            strategy=strategy,
            exchange=exchange,
            symbol=_normalize_symbol_scope(symbol),
            timeframe=timeframe,
            market_regime=market_regime,
            score_bucket=score_bucket,
            direction=direction,
        )


def build_daily_performance(
    *,
    day: date,
    outcomes: Sequence[StrategyPerformanceOutcome],
) -> list[StrategyPerformanceDaily]:
    grouped: dict[tuple[Any, ...], list[StrategyPerformanceOutcome]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.date != day:
            continue
        grouped[_group_key(outcome)].append(outcome)

    rows = [_daily_performance_row(group) for group in grouped.values()]
    return sorted(
        rows,
        key=lambda row: (
            row.date,
            row.strategy,
            row.exchange,
            row.symbol,
            row.timeframe,
            row.market_regime,
            row.score_bucket,
            row.direction,
        ),
    )


def score_bucket_for(score: float | Decimal | None) -> ScoreBucket:
    value = _float(score)
    value = max(0.0, min(100.0, value))
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


def _group_key(outcome: StrategyPerformanceOutcome) -> tuple[Any, ...]:
    return (
        outcome.date,
        outcome.exchange,
        outcome.symbol,
        outcome.timeframe,
        outcome.strategy,
        outcome.strategy_version,
        outcome.market_regime,
        outcome.score_bucket,
        outcome.direction,
    )


def _daily_performance_row(group: Sequence[StrategyPerformanceOutcome]) -> StrategyPerformanceDaily:
    first = group[0]
    signals_count = len(group)
    trades = [outcome for outcome in group if outcome.bars_to_entry is not None]
    trade_rs = [outcome.realized_r for outcome in trades]
    wins = [value for value in trade_rs if value > 0]
    losses = [value for value in trade_rs if value < 0]
    sample_size = len(trades)
    execution_rejected_count = sum(
        1
        for outcome in group
        if _is_execution_rejected_outcome(outcome)
    )
    no_entry_count = max(signals_count - sample_size - execution_rejected_count, 0)
    gross_loss = abs(sum(losses))
    profit_factor = sum(wins) / gross_loss if gross_loss > 0 else None

    return StrategyPerformanceDaily(
        date=first.date,
        exchange=first.exchange,
        symbol=first.symbol,
        timeframe=first.timeframe,
        strategy=first.strategy,
        strategy_version=first.strategy_version,
        market_regime=first.market_regime,
        score_bucket=first.score_bucket,
        direction=_direction(first.direction),
        sample_size=sample_size,
        trades_count=sample_size,
        signals_count=signals_count,
        wins_count=len(wins),
        losses_count=len(losses),
        pending_armed_count=signals_count,
        filled_count=sample_size,
        no_entry_count=no_entry_count,
        execution_rejected_count=execution_rejected_count,
        entry_touch_rate=_rate(sample_size, signals_count),
        fill_rate=_rate(sample_size, signals_count),
        no_entry_rate=_rate(no_entry_count, signals_count),
        execution_rejected_rate=_rate(execution_rejected_count, signals_count),
        winrate=_rate(len(wins), sample_size),
        tp1_rate=_rate(sum(1 for outcome in trades if outcome.status in TARGET_STATUSES), sample_size),
        tp2_rate=_rate(sum(1 for outcome in trades if outcome.status in {"tp2", "tp3"}), sample_size),
        stop_rate=_rate(sum(1 for outcome in trades if outcome.status == "stop_loss"), sample_size),
        invalidation_rate=_rate(sum(1 for outcome in group if outcome.status == "invalidated"), signals_count),
        avg_win_r=_mean(wins),
        avg_loss_r=_mean(losses),
        expectancy_r=_mean(trade_rs),
        profit_factor=profit_factor,
        max_drawdown_r=_max_drawdown_r(_ordered_trade_rs(trades)),
        median_bars_to_entry=_median([outcome.bars_to_entry for outcome in trades]),
        median_bars_to_outcome=_median([outcome.bars_to_outcome for outcome in trades]),
        avg_mfe_r=_mean([outcome.mfe_r for outcome in trades]),
        avg_mae_r=_mean([outcome.mae_r for outcome in trades]),
        fees_bps=_mean([outcome.fees_bps for outcome in group]),
        slippage_bps=_mean([outcome.slippage_bps for outcome in group]),
        updated_at=datetime.now(timezone.utc),
    )


def _ordered_trade_rs(trades: Sequence[StrategyPerformanceOutcome]) -> list[float]:
    ordered = sorted(
        trades,
        key=lambda outcome: outcome.closed_at or datetime.combine(outcome.date, time.min, tzinfo=timezone.utc),
    )
    return [outcome.realized_r for outcome in ordered]


def _daily_row_to_clickhouse(row: StrategyPerformanceDaily) -> list[Any]:
    return [
        row.date,
        row.strategy,
        row.strategy_version,
        row.exchange,
        row.symbol,
        row.timeframe,
        row.market_regime,
        row.score_bucket,
        row.direction,
        row.signals_count,
        row.wins_count,
        row.losses_count,
        row.pending_armed_count,
        row.filled_count,
        row.no_entry_count,
        row.execution_rejected_count,
        row.expectancy_r,
        0.0,
        row.max_drawdown_r,
        row.sample_size,
        row.trades_count,
        row.entry_touch_rate,
        row.fill_rate,
        row.no_entry_rate,
        row.execution_rejected_rate,
        row.winrate,
        row.tp1_rate,
        row.tp2_rate,
        row.stop_rate,
        row.invalidation_rate,
        row.avg_win_r,
        row.avg_loss_r,
        row.expectancy_r,
        row.profit_factor,
        row.max_drawdown_r,
        row.median_bars_to_entry,
        row.median_bars_to_outcome,
        row.avg_mfe_r,
        row.avg_mae_r,
        row.fees_bps,
        row.slippage_bps,
        row.updated_at or datetime.now(timezone.utc),
    ]


def _profile_where(query: StrategyPerformanceProfileQuery) -> tuple[str, dict[str, Any]]:
    clauses = ["strategy_code = {strategy:String}"]
    parameters: dict[str, Any] = {"strategy": query.strategy}
    if query.exchange is not None:
        clauses.append("exchange = {exchange:String}")
        parameters["exchange"] = query.exchange
    if query.symbol is not None:
        clauses.append("symbol = {symbol:String}")
        parameters["symbol"] = query.symbol
    if query.timeframe is not None:
        clauses.append("timeframe = {timeframe:String}")
        parameters["timeframe"] = query.timeframe
    if query.market_regime is not None:
        clauses.append("market_regime = {market_regime:String}")
        parameters["market_regime"] = query.market_regime
    if query.score_bucket is not None:
        clauses.append("score_bucket = {score_bucket:String}")
        parameters["score_bucket"] = query.score_bucket
    if query.direction is not None:
        clauses.append("direction = {direction:String}")
        parameters["direction"] = query.direction
    return " AND ".join(clauses), parameters


def _summary_from_row(row: dict[str, Any]) -> StrategyPerformanceSummary | None:
    if int(row.get("signals_count") or 0) == 0:
        return None
    return StrategyPerformanceSummary(
        sample_size=int(row.get("sample_size") or 0),
        trades_count=int(row.get("trades_count") or 0),
        signals_count=int(row.get("signals_count") or 0),
        wins_count=int(row.get("wins_count") or 0),
        losses_count=int(row.get("losses_count") or 0),
        pending_armed_count=int(row.get("pending_armed_count") or 0),
        filled_count=int(row.get("filled_count") or 0),
        no_entry_count=int(row.get("no_entry_count") or 0),
        execution_rejected_count=int(row.get("execution_rejected_count") or 0),
        entry_touch_rate=_float(row.get("entry_touch_rate")),
        fill_rate=_float(row.get("fill_rate")),
        no_entry_rate=_float(row.get("no_entry_rate")),
        execution_rejected_rate=_float(row.get("execution_rejected_rate")),
        winrate=_float(row.get("winrate")),
        tp1_rate=_float(row.get("tp1_rate")),
        tp2_rate=_float(row.get("tp2_rate")),
        stop_rate=_float(row.get("stop_rate")),
        invalidation_rate=_float(row.get("invalidation_rate")),
        avg_win_r=_float(row.get("avg_win_r")),
        avg_loss_r=_float(row.get("avg_loss_r")),
        expectancy_r=_float(row.get("expectancy_r")),
        profit_factor=_optional_float(row.get("profit_factor")),
        max_drawdown_r=_float(row.get("max_drawdown_r")),
        median_bars_to_entry=_optional_float(row.get("median_bars_to_entry")),
        median_bars_to_outcome=_optional_float(row.get("median_bars_to_outcome")),
        avg_mfe_r=_float(row.get("avg_mfe_r")),
        avg_mae_r=_float(row.get("avg_mae_r")),
        fees_bps=_float(row.get("fees_bps")),
        slippage_bps=_float(row.get("slippage_bps")),
    )


def _edge_profile(
    summary: StrategyPerformanceSummary,
    *,
    source: EdgeProfileSource,
    confidence: EdgeProfileConfidence,
    strategy: str,
    exchange: str,
    symbol: str,
    timeframe: str,
    market_regime: str | None,
    score_bucket: ScoreBucket | None,
) -> StrategyEdgeProfile:
    return StrategyEdgeProfile(
        strategy=strategy,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        market_regime=market_regime,
        score_bucket=score_bucket,
        source=source,
        confidence=confidence,
        sample_size=summary.sample_size,
        trades_count=summary.trades_count,
        signals_count=summary.signals_count,
        wins_count=summary.wins_count,
        losses_count=summary.losses_count,
        pending_armed_count=summary.pending_armed_count,
        filled_count=summary.filled_count,
        no_entry_count=summary.no_entry_count,
        execution_rejected_count=summary.execution_rejected_count,
        entry_touch_rate=summary.entry_touch_rate,
        fill_rate=summary.fill_rate,
        no_entry_rate=summary.no_entry_rate,
        execution_rejected_rate=summary.execution_rejected_rate,
        winrate=summary.winrate,
        tp1_rate=summary.tp1_rate,
        tp2_rate=summary.tp2_rate,
        stop_rate=summary.stop_rate,
        invalidation_rate=summary.invalidation_rate,
        avg_win_r=summary.avg_win_r,
        avg_loss_r=summary.avg_loss_r,
        expectancy_r=summary.expectancy_r,
        profit_factor=summary.profit_factor,
        max_drawdown_r=summary.max_drawdown_r,
        median_bars_to_entry=summary.median_bars_to_entry,
        median_bars_to_outcome=summary.median_bars_to_outcome,
        avg_mfe_r=summary.avg_mfe_r,
        avg_mae_r=summary.avg_mae_r,
        fees_bps=summary.fees_bps,
        slippage_bps=summary.slippage_bps,
    )


def _edge_profile_from_eligibility(
    profile: StrategyExecutionEligibilityProfileRecord,
    *,
    strategy: str,
    exchange: str,
    symbol: str,
    timeframe: str,
    market_regime: str | None,
    score_bucket: ScoreBucket | None,
    min_sample_size: int,
) -> StrategyEdgeProfile:
    metrics = dict(profile.metrics)
    winrate = _float(metrics.get("winrate"))
    sample_size = int(profile.sample_size or 0)
    wins_count = int(sample_size * winrate) if sample_size else 0
    losses_count = max(sample_size - wins_count, 0)
    return StrategyEdgeProfile(
        strategy=strategy,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        market_regime=market_regime,
        score_bucket=score_bucket,
        source="strategy_test",
        confidence=_eligibility_confidence(sample_size, min_sample_size),
        sample_size=sample_size,
        trades_count=int(metrics.get("trades_count") or sample_size),
        signals_count=int(metrics.get("signals_count") or 0),
        wins_count=wins_count,
        losses_count=losses_count,
        pending_armed_count=int(metrics.get("pending_armed_count") or 0),
        filled_count=int(metrics.get("filled_count") or metrics.get("trades_count") or sample_size),
        no_entry_count=int(metrics.get("no_entry_count") or 0),
        execution_rejected_count=int(metrics.get("execution_rejected_count") or 0),
        entry_touch_rate=_float(metrics.get("entry_touch_rate")),
        fill_rate=_float(metrics.get("fill_rate")),
        no_entry_rate=_float(metrics.get("no_entry_rate")),
        execution_rejected_rate=_float(metrics.get("execution_rejection_rate")),
        winrate=winrate,
        tp1_rate=_float(metrics.get("tp1_rate")),
        tp2_rate=_float(metrics.get("tp2_rate")),
        stop_rate=_float(metrics.get("stop_rate")),
        invalidation_rate=_float(metrics.get("invalidation_rate")),
        avg_win_r=_float(metrics.get("avg_win_r")),
        avg_loss_r=_float(metrics.get("avg_loss_r")),
        expectancy_r=_float(metrics.get("expectancy_r")),
        profit_factor=profile.profit_factor,
        max_drawdown_r=profile.max_drawdown_r or 0.0,
        median_bars_to_entry=_optional_float(metrics.get("median_bars_to_entry")),
        median_bars_to_outcome=_optional_float(metrics.get("median_bars_to_outcome")),
        avg_mfe_r=_float(metrics.get("avg_mfe_r")),
        avg_mae_r=_float(metrics.get("avg_mae_r")),
        fees_bps=_float(metrics.get("fees_bps")),
        slippage_bps=_float(metrics.get("slippage_bps")),
        metadata={
            "profile_source": profile.source,
            "run_ids": list(profile.run_ids),
            "eligible": profile.eligible,
            "reason_code": profile.reason_code,
            "reason": profile.reason,
            "source": "strategy_test",
            **metrics,
        },
    )


def _eligibility_confidence(sample_size: int, min_sample_size: int) -> EdgeProfileConfidence:
    if sample_size <= 0:
        return "insufficient_sample"
    if sample_size >= min_sample_size:
        return "high"
    return "low"


def _outcome_to_input(outcome: SignalOutcome) -> StrategyPerformanceOutcome:
    metadata = outcome.metadata_ or {}
    signal = outcome.signal
    closed_at = outcome.closed_at or outcome.updated_at or outcome.created_at
    return StrategyPerformanceOutcome(
        date=_as_utc(closed_at).date(),
        exchange=outcome.exchange,
        symbol=outcome.symbol,
        timeframe=outcome.timeframe,
        strategy=outcome.strategy,
        strategy_version=_strategy_version(signal, metadata),
        market_regime=_market_regime(signal, metadata),
        score_bucket=score_bucket_for(outcome.signal_score),
        direction=_direction(outcome.direction),
        status=outcome.status,
        outcome=outcome.outcome,
        realized_r=_float(outcome.realized_r),
        mfe_r=_float(outcome.mfe_r),
        mae_r=_float(outcome.mae_r),
        bars_to_entry=outcome.bars_to_entry,
        bars_to_outcome=outcome.bars_to_outcome,
        fees_bps=_metadata_float(metadata, "fees_bps", "fee_bps", "fee_rate_bps"),
        slippage_bps=_metadata_float(metadata, "slippage_bps", "entry_slippage_bps"),
        closed_at=_as_utc(closed_at),
        pending_entry_reason_code=_pending_entry_reason_code_from_metadata(metadata),
    )


def _is_execution_rejected_outcome(outcome: StrategyPerformanceOutcome) -> bool:
    return (
        outcome.status == "execution_rejected"
        or outcome.outcome == "execution_rejected"
        or outcome.pending_entry_reason_code == VIRTUAL_EXECUTION_REJECTED
    )


def _pending_entry_reason_code_from_metadata(metadata: dict[str, Any]) -> str | None:
    pending_entry = metadata.get("pending_entry_outcome")
    if not isinstance(pending_entry, dict):
        return None
    reason_code = pending_entry.get("reason_code")
    return reason_code if isinstance(reason_code, str) and reason_code else None


def _strategy_version(signal: TradingSignal | None, metadata: dict[str, Any]) -> str:
    if signal is not None and signal.strategy_version is not None:
        version = signal.strategy_version.version
        if version:
            return version
    return _normalize_dimension(metadata.get("strategy_version") or "unknown")


def _market_regime(signal: TradingSignal | None, metadata: dict[str, Any]) -> str:
    direct = metadata.get("market_regime") or metadata.get("regime_key")
    if direct:
        return _normalize_dimension(direct)
    regime = None
    if signal is not None and isinstance(signal.features_snapshot, dict):
        regime = signal.features_snapshot.get("regime")
    if isinstance(regime, str) and regime:
        return _normalize_dimension(regime)
    if isinstance(regime, dict):
        direction = _normalize_dimension(regime.get("direction") or "unknown")
        strength = _normalize_dimension(regime.get("strength") or "unknown")
        alignment = _normalize_dimension(regime.get("alignment") or "unknown")
        return f"{direction}:{strength}:{alignment}"
    return "unknown"


def _metadata_float(metadata: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = metadata.get(key)
        parsed = _optional_float(value)
        if parsed is not None:
            return parsed
    return 0.0


def _direction(value: Any) -> str:
    return "short" if str(value).lower() == "short" else "long"


def _normalize_dimension(value: Any) -> str:
    text = str(value or "unknown").strip()
    return text or "unknown"


def _normalize_symbol_scope(value: Any) -> str:
    return _normalize_dimension(value).replace("/", "").replace(":PERP", "").upper()


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: Sequence[int | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return float(median(present)) if present else None


def _max_drawdown_r(values: Sequence[float]) -> float:
    peak = 0.0
    equity = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown


def _float(value: Any) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None else 0.0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


strategy_performance_service = StrategyPerformanceService(
    eligibility_store=PostgresStrategyExecutionEligibilityProfileStore(),
)
