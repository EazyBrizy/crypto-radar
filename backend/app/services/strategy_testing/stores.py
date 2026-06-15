from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol, Sequence, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clickhouse_client import create_clickhouse_client
from app.core.database import SessionLocal
from app.models.strategy_testing import StrategyTestRun, StrategyTestScenario
from app.services.strategy_testing.schemas import (
    StrategyTestFunnelResponse,
    StrategyTestMetricRow,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestScenarioCheckpoint,
    StrategyTestSignalEvent,
    StrategyTestType,
    StrategyTestTrade,
)
from app.services.user_identity import resolve_app_user


REQUEST_PARAMS_KEY = "request_params"
INITIAL_CAPITAL_KEY = "initial_capital"
FEE_RATE_KEY = "fee_rate"
SLIPPAGE_BPS_KEY = "slippage_bps"
SAME_CANDLE_POLICY_KEY = "same_candle_policy"

STRATEGY_TEST_TRADES_DDL = """
CREATE TABLE IF NOT EXISTS analytics.strategy_test_trades
(
    run_id UUID,
    trade_id String,
    scenario_key String,
    event_key String,
    run_attempt UInt32,
    user_id UUID,
    mode LowCardinality(String),
    strategy_code LowCardinality(String),
    strategy_version String,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    direction LowCardinality(String),
    signal_score Nullable(Float64),
    market_regime LowCardinality(String),
    score_bucket LowCardinality(String),
    entry_time DateTime64(3, 'UTC'),
    exit_time Nullable(DateTime64(3, 'UTC')),
    entry_price Decimal(38, 18),
    exit_price Nullable(Decimal(38, 18)),
    stop_loss Nullable(Decimal(38, 18)),
    targets_json String,
    selected_rr Nullable(Float64),
    realized_r Nullable(Float64),
    pnl Decimal(38, 18),
    pnl_pct Float64,
    fees Decimal(38, 18),
    slippage Decimal(38, 18),
    mfe_r Nullable(Float64),
    mae_r Nullable(Float64),
    bars_to_entry Nullable(UInt64),
    bars_in_trade Nullable(UInt64),
    close_reason LowCardinality(String),
    outcome LowCardinality(String),
    risk_rejected UInt8,
    execution_rejected UInt8,
    warnings_json String,
    features_snapshot_json String,
    trade_plan_json String,
    tags Array(String),
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(entry_time)
ORDER BY (run_id, scenario_key, event_key, entry_time, trade_id)
"""

STRATEGY_TEST_METRICS_DDL = """
CREATE TABLE IF NOT EXISTS analytics.strategy_test_metrics
(
    run_id UUID,
    scenario_key String,
    run_attempt UInt32,
    user_id UUID,
    mode LowCardinality(String),
    strategy_code LowCardinality(String),
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    market_regime LowCardinality(String),
    score_bucket LowCardinality(String),
    direction LowCardinality(String),
    metric_code LowCardinality(String),
    metric_value Nullable(Float64),
    sample_size UInt64,
    metadata_json String,
    created_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (
    run_id,
    scenario_key,
    strategy_code,
    exchange,
    symbol,
    timeframe,
    market_regime,
    score_bucket,
    direction,
    metric_code
)
"""

STRATEGY_TEST_SIGNALS_DDL = """
CREATE TABLE IF NOT EXISTS analytics.strategy_test_signals
(
    run_id UUID,
    scenario_key String,
    event_key String,
    run_attempt UInt32,
    user_id UUID,
    mode LowCardinality(String),
    test_type LowCardinality(String),
    strategy_code LowCardinality(String),
    strategy_version String,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    direction LowCardinality(String),
    signal_id Nullable(String),
    synthetic_signal_id String,
    signal_key String,
    event_time DateTime64(3, 'UTC'),
    candle_time DateTime64(3, 'UTC'),
    signal_score Nullable(Float64),
    market_regime LowCardinality(String),
    score_bucket LowCardinality(String),
    status LowCardinality(String),
    gate_status LowCardinality(String),
    feed_kind LowCardinality(String),
    trigger_passed UInt8,
    trigger_reason_code Nullable(String),
    execution_candidate UInt8,
    entry_touched UInt8,
    filled UInt8,
    closed UInt8,
    outcome Nullable(String),
    funnel_stage LowCardinality(String),
    risk_rejected UInt8,
    execution_rejected UInt8,
    no_entry UInt8,
    rejection_reason_code Nullable(String),
    blocked_reason_code Nullable(String),
    selected_rr Nullable(Float64),
    entry_min Nullable(Decimal(38, 18)),
    entry_max Nullable(Decimal(38, 18)),
    stop_loss Nullable(Decimal(38, 18)),
    features_snapshot_json String,
    trade_plan_json String,
    metadata_json String,
    tags Array(String),
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(candle_time)
ORDER BY (run_id, scenario_key, event_key, candle_time, signal_key)
"""

STRATEGY_TEST_ANALYTICS_ALTER_DDLS = [
    "ALTER TABLE analytics.strategy_test_trades ADD COLUMN IF NOT EXISTS scenario_key String DEFAULT concat(strategy_code, '::', exchange, '::', symbol, '::', timeframe)",
    "ALTER TABLE analytics.strategy_test_trades ADD COLUMN IF NOT EXISTS event_key String DEFAULT trade_id",
    "ALTER TABLE analytics.strategy_test_trades ADD COLUMN IF NOT EXISTS run_attempt UInt32 DEFAULT 0",
    "ALTER TABLE analytics.strategy_test_signals ADD COLUMN IF NOT EXISTS scenario_key String DEFAULT concat(strategy_code, '::', exchange, '::', symbol, '::', timeframe)",
    "ALTER TABLE analytics.strategy_test_signals ADD COLUMN IF NOT EXISTS event_key String DEFAULT coalesce(nullIf(signal_id, ''), nullIf(synthetic_signal_id, ''), signal_key)",
    "ALTER TABLE analytics.strategy_test_signals ADD COLUMN IF NOT EXISTS run_attempt UInt32 DEFAULT 0",
    "ALTER TABLE analytics.strategy_test_metrics ADD COLUMN IF NOT EXISTS scenario_key String DEFAULT concat(strategy_code, '::', exchange, '::', symbol, '::', timeframe)",
    "ALTER TABLE analytics.strategy_test_metrics ADD COLUMN IF NOT EXISTS run_attempt UInt32 DEFAULT 0",
]


class StrategyTestRunStore(Protocol):
    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunDetailResponse:
        ...

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        ...

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        ...

    def claim_next_run(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> StrategyTestRunDetailResponse | None:
        ...

    def renew_lease(
        self,
        run_id: UUID,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> StrategyTestRunDetailResponse:
        ...

    def recover_expired_leases(self, *, worker_id: str) -> dict[str, int]:
        ...

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        ...

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        ...

    def mark_failed(
        self,
        run_id: UUID,
        error: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        ...

    def mark_stopping(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        ...

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        ...

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        ...

    def list_scenarios(self, run_id: UUID) -> list[StrategyTestScenarioCheckpoint]:
        ...

    def completed_scenario_keys(self, run_id: UUID) -> set[str]:
        ...

    def mark_scenario_running(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        scenario_index: int,
        strategy_code: str,
        exchange: str,
        symbol: str,
        timeframe: str,
        bars_total: int | None = None,
    ) -> StrategyTestScenarioCheckpoint:
        ...

    def mark_scenario_completed(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        summary: dict[str, Any],
        bars_processed: int | None = None,
        result_written_at: datetime | None = None,
    ) -> StrategyTestScenarioCheckpoint:
        ...

    def mark_scenario_failed(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        error: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestScenarioCheckpoint:
        ...

    def mark_scenario_cancelled(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestScenarioCheckpoint:
        ...


class ClickHouseStrategyTestClient(Protocol):
    def command(self, command: str) -> Any:
        ...

    def insert(self, table: str, data: list[list[Any]], column_names: list[str]) -> None:
        ...

    def query(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
        ...


class ClickHouseStrategyTestStore:
    _trade_columns = [
        "run_id",
        "trade_id",
        "scenario_key",
        "event_key",
        "run_attempt",
        "user_id",
        "mode",
        "strategy_code",
        "strategy_version",
        "exchange",
        "symbol",
        "timeframe",
        "direction",
        "signal_score",
        "market_regime",
        "score_bucket",
        "entry_time",
        "exit_time",
        "entry_price",
        "exit_price",
        "stop_loss",
        "targets_json",
        "selected_rr",
        "realized_r",
        "pnl",
        "pnl_pct",
        "fees",
        "slippage",
        "mfe_r",
        "mae_r",
        "bars_to_entry",
        "bars_in_trade",
        "close_reason",
        "outcome",
        "risk_rejected",
        "execution_rejected",
        "warnings_json",
        "features_snapshot_json",
        "trade_plan_json",
        "tags",
        "created_at",
    ]
    _metric_columns = [
        "run_id",
        "scenario_key",
        "run_attempt",
        "user_id",
        "mode",
        "strategy_code",
        "exchange",
        "symbol",
        "timeframe",
        "market_regime",
        "score_bucket",
        "direction",
        "metric_code",
        "metric_value",
        "sample_size",
        "metadata_json",
        "created_at",
    ]
    _signal_event_columns = [
        "run_id",
        "scenario_key",
        "event_key",
        "run_attempt",
        "user_id",
        "mode",
        "test_type",
        "strategy_code",
        "strategy_version",
        "exchange",
        "symbol",
        "timeframe",
        "direction",
        "signal_id",
        "synthetic_signal_id",
        "signal_key",
        "event_time",
        "candle_time",
        "signal_score",
        "market_regime",
        "score_bucket",
        "status",
        "gate_status",
        "feed_kind",
        "trigger_passed",
        "trigger_reason_code",
        "execution_candidate",
        "entry_touched",
        "filled",
        "closed",
        "outcome",
        "funnel_stage",
        "risk_rejected",
        "execution_rejected",
        "no_entry",
        "rejection_reason_code",
        "blocked_reason_code",
        "selected_rr",
        "entry_min",
        "entry_max",
        "stop_loss",
        "features_snapshot_json",
        "trade_plan_json",
        "metadata_json",
        "tags",
        "created_at",
    ]

    def __init__(self, clickhouse_client_factory: Any = create_clickhouse_client) -> None:
        self._clickhouse_client_factory = clickhouse_client_factory

    def ensure_schema(self) -> None:
        client = self._client()
        try:
            client.command(STRATEGY_TEST_TRADES_DDL)
            client.command(STRATEGY_TEST_METRICS_DDL)
            client.command(STRATEGY_TEST_SIGNALS_DDL)
            for alter_ddl in STRATEGY_TEST_ANALYTICS_ALTER_DDLS:
                client.command(alter_ddl)
        finally:
            self._close_client(client)

    def write_trades(self, trades: Sequence[StrategyTestTrade]) -> None:
        if not trades:
            return
        client = self._client()
        try:
            client.insert(
                "analytics.strategy_test_trades",
                [_trade_to_clickhouse(trade) for trade in trades],
                column_names=self._trade_columns,
            )
        finally:
            self._close_client(client)

    def list_trades(
        self,
        run_id: UUID,
        limit: int = 500,
        offset: int = 0,
    ) -> list[StrategyTestTrade]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        query = f"""
            SELECT
                {_dedup_select_columns_sql(self._trade_columns, _trade_dedup_group_columns())}
            FROM analytics.strategy_test_trades
            WHERE run_id = {{run_id:UUID}}
            GROUP BY run_id, scenario_key, event_key
            ORDER BY entry_time ASC, trade_id ASC
            LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
        """
        client = self._client()
        try:
            result = client.query(
                query,
                parameters={"run_id": run_id, "limit": limit, "offset": offset},
            )
            rows = result.named_results() if hasattr(result, "named_results") else []
            return [_row_to_trade(row) for row in rows]
        finally:
            self._close_client(client)

    def write_signal_events(self, signal_events: Sequence[StrategyTestSignalEvent]) -> None:
        if not signal_events:
            return
        client = self._client()
        try:
            client.insert(
                "analytics.strategy_test_signals",
                [_signal_event_to_clickhouse(event) for event in signal_events],
                column_names=self._signal_event_columns,
            )
        finally:
            self._close_client(client)

    def list_signal_events(
        self,
        run_id: UUID,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StrategyTestSignalEvent]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        query = f"""
            SELECT
                {_dedup_select_columns_sql(self._signal_event_columns, _signal_event_dedup_group_columns())}
            FROM analytics.strategy_test_signals
            WHERE run_id = {{run_id:UUID}}
            GROUP BY run_id, scenario_key, event_key
            ORDER BY candle_time ASC, signal_key ASC
            LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
        """
        client = self._client()
        try:
            result = client.query(
                query,
                parameters={"run_id": run_id, "limit": limit, "offset": offset},
            )
            rows = result.named_results() if hasattr(result, "named_results") else []
            return [_row_to_signal_event(row) for row in rows]
        finally:
            self._close_client(client)

    def aggregate_signal_funnel(self, run_id: UUID) -> StrategyTestFunnelResponse:
        query = f"""
            SELECT
                count() AS signals_count,
                sum(toUInt64(execution_candidate)) AS execution_candidates,
                sum(toUInt64(entry_touched)) AS entry_touched,
                sum(toUInt64(filled)) AS filled,
                sum(toUInt64(closed)) AS closed,
                sum(if(lowerUTF8(ifNull(outcome, '')) = 'win', 1, 0)) AS wins,
                sum(if(lowerUTF8(ifNull(outcome, '')) = 'loss', 1, 0)) AS losses,
                sum(toUInt64(no_entry)) AS no_entry,
                sum(toUInt64(risk_rejected)) AS risk_rejected,
                sum(toUInt64(execution_rejected)) AS execution_rejected
            FROM (
                SELECT
                    {_dedup_select_columns_sql(self._signal_event_columns, _signal_event_dedup_group_columns())}
                FROM analytics.strategy_test_signals
                WHERE run_id = {{run_id:UUID}}
                GROUP BY run_id, scenario_key, event_key
            )
        """
        client = self._client()
        try:
            result = client.query(query, parameters={"run_id": run_id})
            rows = result.named_results() if hasattr(result, "named_results") else []
            row = rows[0] if rows else {}
            signals_count = _int_from_row(row, "signals_count")
            execution_candidates = _int_from_row(row, "execution_candidates")
            entry_touched = _int_from_row(row, "entry_touched")
            no_entry = _int_from_row(row, "no_entry")
            risk_rejected = _int_from_row(row, "risk_rejected")
            execution_rejected = _int_from_row(row, "execution_rejected")
            return StrategyTestFunnelResponse(
                run_id=run_id,
                signals_count=signals_count,
                execution_candidates=execution_candidates,
                entry_touched=entry_touched,
                filled=_int_from_row(row, "filled"),
                closed=_int_from_row(row, "closed"),
                wins=_int_from_row(row, "wins"),
                losses=_int_from_row(row, "losses"),
                no_entry=no_entry,
                risk_rejected=risk_rejected,
                execution_rejected=execution_rejected,
                entry_touch_rate=_safe_rate(entry_touched, signals_count),
                no_entry_rate=_safe_rate(no_entry, signals_count),
                risk_rejection_rate=_safe_rate(risk_rejected, signals_count),
                execution_rejection_rate=_safe_rate(execution_rejected, execution_candidates),
                false_signal_rate=_safe_rate(no_entry, signals_count),
                stages=[],
            )
        finally:
            self._close_client(client)

    def list_journal_trades(
        self,
        *,
        run_id: UUID | None = None,
        tag: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[StrategyTestTrade]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if status is not None and status not in {"open", "closed"}:
            return []

        conditions: list[str] = []
        parameters: dict[str, Any] = {"limit": limit}
        if run_id is not None:
            conditions.append("run_id = {run_id:UUID}")
            parameters["run_id"] = run_id
        if tag is not None:
            conditions.append("has(tags, {tag:String})")
            parameters["tag"] = tag
        if status == "open":
            conditions.append("exit_time IS NULL")
        elif status == "closed":
            conditions.append("exit_time IS NOT NULL")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT
                {_trade_select_columns_sql()}
            FROM analytics.strategy_test_trades
            {where_clause}
            ORDER BY entry_time DESC, created_at DESC, trade_id ASC
            LIMIT {{limit:UInt32}}
        """
        client = self._client()
        try:
            result = client.query(query, parameters=parameters)
            rows = result.named_results() if hasattr(result, "named_results") else []
            return [_row_to_trade(row) for row in rows]
        finally:
            self._close_client(client)

    def get_trade(self, trade_id: str) -> StrategyTestTrade | None:
        query = f"""
            SELECT
                {_trade_select_columns_sql()}
            FROM analytics.strategy_test_trades
            WHERE trade_id = {{trade_id:String}}
            ORDER BY created_at DESC
            LIMIT 1
        """
        client = self._client()
        try:
            result = client.query(query, parameters={"trade_id": trade_id})
            rows = result.named_results() if hasattr(result, "named_results") else []
            return _row_to_trade(rows[0]) if rows else None
        finally:
            self._close_client(client)

    def write_metrics(self, rows: Sequence[StrategyTestMetricRow]) -> None:
        if not rows:
            return
        client = self._client()
        try:
            client.insert(
                "analytics.strategy_test_metrics",
                [_metric_to_clickhouse(row) for row in rows],
                column_names=self._metric_columns,
            )
        finally:
            self._close_client(client)

    def list_metrics(self, run_id: UUID) -> list[StrategyTestMetricRow]:
        query = f"""
            SELECT
                {_dedup_select_columns_sql(self._metric_columns, _metric_dedup_group_columns())}
            FROM analytics.strategy_test_metrics
            WHERE run_id = {{run_id:UUID}}
            GROUP BY
                run_id,
                scenario_key,
                strategy_code,
                exchange,
                symbol,
                timeframe,
                market_regime,
                score_bucket,
                direction,
                metric_code
            ORDER BY
                strategy_code ASC,
                exchange ASC,
                symbol ASC,
                timeframe ASC,
                market_regime ASC,
                score_bucket ASC,
                direction ASC,
                metric_code ASC
        """
        client = self._client()
        try:
            result = client.query(query, parameters={"run_id": run_id})
            rows = result.named_results() if hasattr(result, "named_results") else []
            return [_row_to_metric(row) for row in rows]
        finally:
            self._close_client(client)

    def _client(self) -> ClickHouseStrategyTestClient:
        return self._clickhouse_client_factory()

    @staticmethod
    def _close_client(client: ClickHouseStrategyTestClient) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()


class PostgresStrategyTestRunStore:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def create_run(self, request: StrategyTestRunRequest) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, request.user_id)
            now = datetime.now(timezone.utc)
            run = StrategyTestRun(
                id=uuid4(),
                user_id=user.id,
                requested_user_id=request.user_id,
                status="queued",
                test_type=request.test_type,
                mode=request.mode,
                requested_strategies=list(request.strategies),
                requested_pairs=[pair.model_dump(mode="json") for pair in request.pairs],
                requested_timeframes=list(request.timeframes),
                start_at=request.start_at,
                end_at=request.end_at,
                params=_stored_params(request),
                summary={},
                runtime_state={},
                metric_set=list(request.metric_set),
                tags=list(request.tags),
                created_at=now,
            )
            session.add(run)
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def list_runs(
        self,
        user_id: str | None,
        limit: int,
        status: StrategyTestRunStatus | None = None,
    ) -> list[StrategyTestRunDetailResponse]:
        if limit < 1:
            raise ValueError("limit must be positive")

        with self._session_factory() as session:
            statement = select(StrategyTestRun)
            if user_id is not None:
                user = resolve_app_user(session, user_id)
                statement = statement.where(StrategyTestRun.user_id == user.id)
            if status is not None:
                statement = statement.where(StrategyTestRun.status == status)
            statement = statement.order_by(StrategyTestRun.created_at.desc()).limit(limit)
            return [_run_to_detail(run) for run in session.scalars(statement).all()]

    def get_run(self, run_id: UUID) -> StrategyTestRunDetailResponse | None:
        with self._session_factory() as session:
            run = session.get(StrategyTestRun, run_id)
            if run is None:
                return None
            return _run_to_detail(run)

    def claim_next_run(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> StrategyTestRunDetailResponse | None:
        now = _utc_now()
        with self._session_factory() as session:
            run = session.scalars(_claim_next_run_statement().limit(1)).first()
            if run is None:
                return None
            run.worker_id = worker_id
            run.worker_attempt = int(run.worker_attempt or 0) + 1
            run.claimed_at = now
            run.lease_expires_at = _lease_expires_at(now, lease_seconds)
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def renew_lease(
        self,
        run_id: UUID,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> StrategyTestRunDetailResponse:
        now = _utc_now()
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            run.worker_id = run.worker_id or worker_id
            run.claimed_at = run.claimed_at or now
            run.last_heartbeat_at = now
            run.lease_expires_at = _lease_expires_at(now, lease_seconds)
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def recover_expired_leases(self, *, worker_id: str) -> dict[str, int]:
        now = _utc_now()
        recovered = {"failed": 0, "cancelled": 0, "requeued": 0}
        with self._session_factory() as session:
            statement = (
                select(StrategyTestRun)
                .where(StrategyTestRun.status.in_(("queued", "running", "stopping")))
                .where(StrategyTestRun.lease_expires_at.is_not(None))
                .where(StrategyTestRun.lease_expires_at <= now)
                .order_by(StrategyTestRun.lease_expires_at.asc(), StrategyTestRun.created_at.asc())
                .with_for_update(skip_locked=True)
            )
            runs = list(session.scalars(statement).all())
            for run in runs:
                if run.status == "queued":
                    run.worker_id = None
                    run.lease_expires_at = None
                    run.claimed_at = None
                    recovered["requeued"] += 1
                    continue
                if run.status == "stopping":
                    run.status = "cancelled"
                    run.finished_at = now
                    run.last_heartbeat_at = now
                    run.lease_expires_at = None
                    run.runtime_state = {
                        **_json_object(run.runtime_state),
                        "phase": "cancelled",
                        "cancelled_reason": "strategy_test_worker_lease_expired",
                        "recovered_by_worker_id": worker_id,
                    }
                    recovered["cancelled"] += 1
                    continue
                run.status = "failed"
                run.finished_at = now
                run.last_heartbeat_at = now
                run.lease_expires_at = None
                run.error = "Strategy test worker lease expired before completion"
                run.runtime_state = {
                    **_json_object(run.runtime_state),
                    "phase": "failed",
                    "last_error": run.error,
                    "recovered_by_worker_id": worker_id,
                }
                recovered["failed"] += 1
            session.flush()
            session.commit()
        return recovered

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            run.status = "running"
            now = _utc_now()
            run.started_at = run.started_at or now
            run.last_heartbeat_at = now
            run.error = None
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            now = _utc_now()
            run.status = "completed"
            run.finished_at = now
            run.last_heartbeat_at = now
            run.lease_expires_at = None
            run.summary = dict(summary or {})
            run.error = None
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def mark_failed(
        self,
        run_id: UUID,
        error: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            now = _utc_now()
            run.status = "failed"
            run.finished_at = now
            run.last_heartbeat_at = now
            run.lease_expires_at = None
            run.error = error
            if summary is not None:
                run.summary = dict(summary)
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def mark_stopping(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            run.status = "stopping"
            run.last_heartbeat_at = _utc_now()
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def mark_cancelled(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            now = _utc_now()
            run.status = "cancelled"
            run.finished_at = now
            run.last_heartbeat_at = now
            run.lease_expires_at = None
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def update_runtime_state(
        self,
        run_id: UUID,
        runtime_state: dict[str, Any],
        *,
        heartbeat: bool = True,
    ) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            run.runtime_state = {
                **_json_object(run.runtime_state),
                **dict(runtime_state),
            }
            if heartbeat:
                run.last_heartbeat_at = _utc_now()
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail

    def list_scenarios(self, run_id: UUID) -> list[StrategyTestScenarioCheckpoint]:
        with self._session_factory() as session:
            statement = (
                select(StrategyTestScenario)
                .where(StrategyTestScenario.run_id == run_id)
                .order_by(StrategyTestScenario.scenario_index.asc())
            )
            return [_scenario_to_checkpoint(scenario) for scenario in session.scalars(statement).all()]

    def completed_scenario_keys(self, run_id: UUID) -> set[str]:
        with self._session_factory() as session:
            statement = (
                select(StrategyTestScenario.scenario_key)
                .where(StrategyTestScenario.run_id == run_id)
                .where(StrategyTestScenario.status == "completed")
            )
            return {str(key) for key in session.scalars(statement).all()}

    def mark_scenario_running(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        scenario_index: int,
        strategy_code: str,
        exchange: str,
        symbol: str,
        timeframe: str,
        bars_total: int | None = None,
    ) -> StrategyTestScenarioCheckpoint:
        now = _utc_now()
        with self._session_factory() as session:
            _get_run_or_raise(session, run_id)
            scenario = _get_scenario(session, run_id, scenario_key)
            if scenario is None:
                scenario = StrategyTestScenario(
                    id=uuid4(),
                    run_id=run_id,
                    scenario_key=scenario_key,
                    scenario_index=scenario_index,
                    strategy_code=strategy_code,
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    status="running",
                    bars_total=max(0, int(bars_total or 0)),
                    bars_processed=0,
                    summary={},
                    started_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(scenario)
            elif scenario.status != "completed":
                scenario.scenario_index = scenario_index
                scenario.strategy_code = strategy_code
                scenario.exchange = exchange
                scenario.symbol = symbol
                scenario.timeframe = timeframe
                scenario.status = "running"
                scenario.bars_total = max(0, int(bars_total if bars_total is not None else scenario.bars_total or 0))
                scenario.bars_processed = 0
                scenario.error = None
                scenario.started_at = scenario.started_at or now
                scenario.completed_at = None
                scenario.updated_at = now
            session.flush()
            checkpoint = _scenario_to_checkpoint(scenario)
            session.commit()
            return checkpoint

    def mark_scenario_completed(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        summary: dict[str, Any],
        bars_processed: int | None = None,
        result_written_at: datetime | None = None,
    ) -> StrategyTestScenarioCheckpoint:
        now = _utc_now()
        with self._session_factory() as session:
            scenario = _get_scenario_or_raise(session, run_id, scenario_key)
            scenario.status = "completed"
            scenario.summary = dict(summary)
            if bars_processed is not None:
                scenario.bars_processed = max(0, int(bars_processed))
            elif scenario.bars_total:
                scenario.bars_processed = max(scenario.bars_processed or 0, scenario.bars_total)
            scenario.result_written_at = result_written_at or now
            scenario.completed_at = now
            scenario.error = None
            scenario.updated_at = now
            session.flush()
            checkpoint = _scenario_to_checkpoint(scenario)
            session.commit()
            return checkpoint

    def mark_scenario_failed(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        error: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestScenarioCheckpoint:
        now = _utc_now()
        with self._session_factory() as session:
            scenario = _get_scenario_or_raise(session, run_id, scenario_key)
            scenario.status = "failed"
            scenario.error = error
            scenario.summary = dict(summary or {})
            scenario.completed_at = now
            scenario.updated_at = now
            session.flush()
            checkpoint = _scenario_to_checkpoint(scenario)
            session.commit()
            return checkpoint

    def mark_scenario_cancelled(
        self,
        run_id: UUID,
        *,
        scenario_key: str,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestScenarioCheckpoint:
        now = _utc_now()
        with self._session_factory() as session:
            scenario = _get_scenario_or_raise(session, run_id, scenario_key)
            scenario.status = "cancelled"
            scenario.summary = dict(summary or scenario.summary or {})
            scenario.completed_at = now
            scenario.updated_at = now
            session.flush()
            checkpoint = _scenario_to_checkpoint(scenario)
            session.commit()
            return checkpoint


def _claim_next_run_statement() -> Any:
    return (
        select(StrategyTestRun)
        .where(StrategyTestRun.status == "queued")
        .order_by(StrategyTestRun.created_at.asc())
        .with_for_update(skip_locked=True)
    )


def _get_scenario(
    session: Session,
    run_id: UUID,
    scenario_key: str,
) -> StrategyTestScenario | None:
    statement = (
        select(StrategyTestScenario)
        .where(StrategyTestScenario.run_id == run_id)
        .where(StrategyTestScenario.scenario_key == scenario_key)
    )
    return session.scalars(statement).first()


def _get_scenario_or_raise(
    session: Session,
    run_id: UUID,
    scenario_key: str,
) -> StrategyTestScenario:
    scenario = _get_scenario(session, run_id, scenario_key)
    if scenario is None:
        raise ValueError(f"Strategy test scenario is not found: {run_id} {scenario_key}")
    return scenario


def _get_run_or_raise(session: Session, run_id: UUID) -> StrategyTestRun:
    run = session.get(StrategyTestRun, run_id)
    if run is None:
        raise ValueError(f"Strategy test run is not found: {run_id}")
    return run


def _scenario_to_checkpoint(scenario: StrategyTestScenario) -> StrategyTestScenarioCheckpoint:
    return StrategyTestScenarioCheckpoint(
        id=scenario.id,
        run_id=scenario.run_id,
        scenario_key=scenario.scenario_key,
        scenario_index=scenario.scenario_index,
        strategy_code=scenario.strategy_code,
        exchange=scenario.exchange,
        symbol=scenario.symbol,
        timeframe=scenario.timeframe,
        status=cast(Any, scenario.status),
        bars_total=int(scenario.bars_total or 0),
        bars_processed=int(scenario.bars_processed or 0),
        summary=_json_object(scenario.summary),
        error=scenario.error,
        result_written_at=scenario.result_written_at,
        started_at=scenario.started_at,
        completed_at=scenario.completed_at,
        created_at=scenario.created_at,
        updated_at=scenario.updated_at,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _lease_expires_at(now: datetime, lease_seconds: int) -> datetime:
    return now + timedelta(seconds=max(1, int(lease_seconds)))


def _stored_params(request: StrategyTestRunRequest) -> dict[str, Any]:
    dumped = request.model_dump(mode="json")
    return {
        REQUEST_PARAMS_KEY: dumped["params"],
        INITIAL_CAPITAL_KEY: dumped["initial_capital"],
        FEE_RATE_KEY: dumped["fee_rate"],
        SLIPPAGE_BPS_KEY: dumped["slippage_bps"],
        SAME_CANDLE_POLICY_KEY: dumped["same_candle_policy"],
    }


def _run_to_detail(
    run: StrategyTestRun,
) -> StrategyTestRunDetailResponse:
    return StrategyTestRunDetailResponse(
        run=StrategyTestRunResponse(
            run_id=run.id,
            status=cast(StrategyTestRunStatus, run.status),
            test_type=cast(StrategyTestType, run.test_type),
            requested_matrix=_requested_matrix(run),
            summary=_json_object(run.summary),
            runtime_state=_json_object(run.runtime_state),
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            last_heartbeat_at=run.last_heartbeat_at,
            error=run.error,
        ),
    )


def _requested_matrix(run: StrategyTestRun) -> dict[str, Any]:
    params = run.params or {}
    request_params = params.get(REQUEST_PARAMS_KEY, params)
    return {
        "user_id": run.requested_user_id,
        "test_type": run.test_type,
        "mode": run.mode,
        "strategies": list(run.requested_strategies),
        "pairs": list(run.requested_pairs),
        "timeframes": list(run.requested_timeframes),
        "start_at": run.start_at,
        "end_at": run.end_at,
        "initial_capital": params.get(INITIAL_CAPITAL_KEY),
        "fee_rate": params.get(FEE_RATE_KEY),
        "slippage_bps": params.get(SLIPPAGE_BPS_KEY),
        "same_candle_policy": params.get(SAME_CANDLE_POLICY_KEY),
        "params": request_params,
        "metric_set": list(run.metric_set),
        "tags": list(run.tags),
        "scenario_count": len(run.requested_strategies) * len(run.requested_pairs) * len(run.requested_timeframes),
    }


def _json_object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}

def _trade_select_columns_sql() -> str:
    return ",\n                ".join(ClickHouseStrategyTestStore._trade_columns)


def _signal_event_select_columns_sql() -> str:
    return ",\n                ".join(ClickHouseStrategyTestStore._signal_event_columns)


def _dedup_select_columns_sql(columns: Sequence[str], group_columns: set[str]) -> str:
    expressions: list[str] = []
    for column in columns:
        if column in group_columns:
            expressions.append(column)
        elif column == "created_at":
            expressions.append("max(created_at) AS created_at")
        else:
            expressions.append(f"argMax({column}, created_at) AS {column}")
    return ",\n                ".join(expressions)


def _trade_dedup_group_columns() -> set[str]:
    return {"run_id", "scenario_key", "event_key"}


def _signal_event_dedup_group_columns() -> set[str]:
    return {"run_id", "scenario_key", "event_key"}


def _metric_dedup_group_columns() -> set[str]:
    return {
        "run_id",
        "scenario_key",
        "strategy_code",
        "exchange",
        "symbol",
        "timeframe",
        "market_regime",
        "score_bucket",
        "direction",
        "metric_code",
    }


def _trade_to_clickhouse(trade: StrategyTestTrade) -> list[Any]:
    return [
        trade.run_id,
        trade.trade_id,
        _analytics_scenario_key(trade.strategy_code, trade.exchange, trade.symbol, trade.timeframe),
        _trade_event_key(trade),
        _run_attempt(trade),
        trade.user_id,
        trade.mode,
        trade.strategy_code,
        trade.strategy_version,
        trade.exchange,
        trade.symbol,
        trade.timeframe,
        trade.direction,
        trade.signal_score,
        trade.market_regime,
        trade.score_bucket,
        trade.entry_time,
        trade.exit_time,
        trade.entry_price,
        trade.exit_price,
        trade.stop_loss,
        _json_dumps(trade.targets),
        trade.selected_rr,
        trade.realized_r,
        trade.pnl,
        trade.pnl_pct,
        trade.fees,
        trade.slippage,
        trade.mfe_r,
        trade.mae_r,
        trade.bars_to_entry,
        trade.bars_in_trade,
        trade.close_reason,
        trade.outcome,
        int(trade.risk_rejected),
        int(trade.execution_rejected),
        _json_dumps(trade.warnings),
        _json_dumps(trade.features_snapshot),
        _json_dumps(trade.trade_plan),
        list(trade.tags),
        trade.created_at,
    ]


def _signal_event_to_clickhouse(event: StrategyTestSignalEvent) -> list[Any]:
    return [
        event.run_id,
        _analytics_scenario_key(event.strategy_code, event.exchange, event.symbol, event.timeframe),
        _signal_event_key(event),
        _run_attempt(event),
        event.user_id,
        event.mode,
        event.test_type,
        event.strategy_code,
        event.strategy_version,
        event.exchange,
        event.symbol,
        event.timeframe,
        event.direction,
        event.signal_id,
        event.synthetic_signal_id,
        event.signal_key,
        event.event_time,
        event.candle_time,
        event.signal_score,
        event.market_regime,
        event.score_bucket,
        event.status,
        event.gate_status,
        event.feed_kind,
        int(event.trigger_passed),
        event.trigger_reason_code,
        int(event.execution_candidate),
        int(event.entry_touched),
        int(event.filled),
        int(event.closed),
        event.outcome,
        event.funnel_stage,
        int(event.risk_rejected),
        int(event.execution_rejected),
        int(event.no_entry),
        event.rejection_reason_code,
        event.blocked_reason_code,
        event.selected_rr,
        event.entry_min,
        event.entry_max,
        event.stop_loss,
        _json_dumps(event.features_snapshot),
        _json_dumps(event.trade_plan),
        _json_dumps(event.metadata),
        list(event.tags),
        event.created_at,
    ]


def _metric_to_clickhouse(row: StrategyTestMetricRow) -> list[Any]:
    return [
        row.run_id,
        _metric_scenario_key(row),
        _run_attempt(row),
        row.user_id,
        row.mode,
        row.strategy_code,
        row.exchange,
        row.symbol,
        row.timeframe,
        row.market_regime,
        row.score_bucket,
        row.direction,
        row.metric_code,
        row.metric_value,
        row.sample_size,
        _json_dumps(row.metadata),
        row.created_at,
    ]


def _row_to_trade(row: dict[str, Any]) -> StrategyTestTrade:
    return StrategyTestTrade(
        run_id=row["run_id"],
        trade_id=row["trade_id"],
        user_id=row["user_id"],
        mode=row["mode"],
        strategy_code=row["strategy_code"],
        strategy_version=row["strategy_version"],
        exchange=row["exchange"],
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        direction=row["direction"],
        signal_score=_optional_float(row.get("signal_score")),
        market_regime=row["market_regime"],
        score_bucket=row["score_bucket"],
        entry_time=_as_utc(row["entry_time"]),
        exit_time=_optional_datetime(row.get("exit_time")),
        entry_price=_decimal(row["entry_price"]),
        exit_price=_optional_decimal(row.get("exit_price")),
        stop_loss=_optional_decimal(row.get("stop_loss")),
        targets=_loads_json(row.get("targets_json"), []),
        selected_rr=_optional_float(row.get("selected_rr")),
        realized_r=_optional_float(row.get("realized_r")),
        pnl=_decimal(row["pnl"]),
        pnl_pct=_float(row.get("pnl_pct")),
        fees=_decimal(row["fees"]),
        slippage=_decimal(row["slippage"]),
        mfe_r=_optional_float(row.get("mfe_r")),
        mae_r=_optional_float(row.get("mae_r")),
        bars_to_entry=_optional_int(row.get("bars_to_entry")),
        bars_in_trade=_optional_int(row.get("bars_in_trade")),
        close_reason=row["close_reason"],
        outcome=row["outcome"],
        risk_rejected=_bool(row.get("risk_rejected")),
        execution_rejected=_bool(row.get("execution_rejected")),
        warnings=_loads_json(row.get("warnings_json"), []),
        features_snapshot=_loads_json(row.get("features_snapshot_json"), {}),
        trade_plan=_loads_json(row.get("trade_plan_json"), {}),
        tags=_string_list(row.get("tags")),
        created_at=_as_utc(row["created_at"]),
    )


def _row_to_signal_event(row: dict[str, Any]) -> StrategyTestSignalEvent:
    return StrategyTestSignalEvent(
        run_id=row["run_id"],
        user_id=row["user_id"],
        mode=row["mode"],
        test_type=row["test_type"],
        strategy_code=row["strategy_code"],
        strategy_version=row["strategy_version"],
        exchange=row["exchange"],
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        direction=row["direction"],
        signal_id=row.get("signal_id"),
        synthetic_signal_id=row["synthetic_signal_id"],
        signal_key=row["signal_key"],
        event_time=_as_utc(row["event_time"]),
        candle_time=_as_utc(row["candle_time"]),
        signal_score=_optional_float(row.get("signal_score")),
        market_regime=row["market_regime"],
        score_bucket=row["score_bucket"],
        status=row["status"],
        gate_status=row["gate_status"],
        feed_kind=row["feed_kind"],
        trigger_passed=_bool(row.get("trigger_passed")),
        trigger_reason_code=row.get("trigger_reason_code"),
        execution_candidate=_bool(row.get("execution_candidate")),
        entry_touched=_bool(row.get("entry_touched")),
        filled=_bool(row.get("filled")),
        closed=_bool(row.get("closed")),
        outcome=row.get("outcome"),
        funnel_stage=row["funnel_stage"],
        risk_rejected=_bool(row.get("risk_rejected")),
        execution_rejected=_bool(row.get("execution_rejected")),
        no_entry=_bool(row.get("no_entry")),
        rejection_reason_code=row.get("rejection_reason_code"),
        blocked_reason_code=row.get("blocked_reason_code"),
        selected_rr=_optional_float(row.get("selected_rr")),
        entry_min=_optional_decimal(row.get("entry_min")),
        entry_max=_optional_decimal(row.get("entry_max")),
        stop_loss=_optional_decimal(row.get("stop_loss")),
        features_snapshot=_loads_json(row.get("features_snapshot_json"), {}),
        trade_plan=_loads_json(row.get("trade_plan_json"), {}),
        metadata=_loads_json(row.get("metadata_json"), {}),
        tags=_string_list(row.get("tags")),
        created_at=_as_utc(row["created_at"]),
    )


def _row_to_metric(row: dict[str, Any]) -> StrategyTestMetricRow:
    return StrategyTestMetricRow(
        run_id=row["run_id"],
        user_id=row["user_id"],
        mode=row["mode"],
        strategy_code=row["strategy_code"],
        exchange=row["exchange"],
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        market_regime=row["market_regime"],
        score_bucket=row["score_bucket"],
        direction=row["direction"],
        metric_code=row["metric_code"],
        metric_value=_optional_float(row.get("metric_value")),
        sample_size=int(row.get("sample_size") or 0),
        metadata=_loads_json(row.get("metadata_json"), {}),
        created_at=_as_utc(row["created_at"]),
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _analytics_scenario_key(
    strategy: object,
    exchange: object,
    symbol: object,
    timeframe: object,
) -> str:
    return "::".join(_key_text(value) for value in (strategy, exchange, symbol, timeframe))


def _trade_event_key(trade: StrategyTestTrade) -> str:
    return str(trade.trade_id)


def _signal_event_key(event: StrategyTestSignalEvent) -> str:
    return str(event.signal_id or event.synthetic_signal_id or event.signal_key)


def _metric_scenario_key(row: StrategyTestMetricRow) -> str:
    scenario_key = row.metadata.get("scenario_key") if isinstance(row.metadata, dict) else None
    if scenario_key:
        return str(scenario_key)
    return _analytics_scenario_key(row.strategy_code, row.exchange, row.symbol, row.timeframe)


def _run_attempt(row: object) -> int:
    metadata = getattr(row, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("run_attempt", "worker_attempt"):
            value = metadata.get(key)
            if value is not None:
                return _non_negative_int(value)
    for key in ("run_attempt", "worker_attempt"):
        value = getattr(row, key, None)
        if value is not None:
            return _non_negative_int(value)
    return 0


def _non_negative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _key_text(value: object) -> str:
    return str(value or "unknown").strip() or "unknown"


def _loads_json(value: Any, fallback: list[Any] | dict[str, Any]) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if not isinstance(value, str) or not value:
        return _copy_json_fallback(fallback)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return _copy_json_fallback(fallback)


def _copy_json_fallback(fallback: list[Any] | dict[str, Any]) -> Any:
    if isinstance(fallback, list):
        return list(fallback)
    return dict(fallback)


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value)


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


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_from_row(row: dict[str, Any], key: str) -> int:
    return _non_negative_int(row.get(key))


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return _as_utc(value)


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise TypeError(f"Unsupported datetime value: {value!r}")
