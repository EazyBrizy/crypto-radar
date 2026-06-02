from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol, Sequence, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clickhouse_client import create_clickhouse_client
from app.core.database import SessionLocal
from app.models.strategy_testing import StrategyTestRun
from app.models.user import AppUser
from app.services.strategy_testing.schemas import (
    StrategyTestMetricRow,
    StrategyTestRunDetailResponse,
    StrategyTestRunRequest,
    StrategyTestRunResponse,
    StrategyTestRunStatus,
    StrategyTestTrade,
)


DEMO_PUBLIC_USER_ID = "demo_user"
DEMO_USERNAME = "demo"
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
ORDER BY (run_id, strategy_code, exchange, symbol, timeframe, entry_time, trade_id)
"""

STRATEGY_TEST_METRICS_DDL = """
CREATE TABLE IF NOT EXISTS analytics.strategy_test_metrics
(
    run_id UUID,
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

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        ...

    def mark_completed(
        self,
        run_id: UUID,
        summary: dict[str, Any] | None = None,
    ) -> StrategyTestRunDetailResponse:
        ...

    def mark_failed(self, run_id: UUID, error: str) -> StrategyTestRunDetailResponse:
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

    def __init__(self, clickhouse_client_factory: Any = create_clickhouse_client) -> None:
        self._clickhouse_client_factory = clickhouse_client_factory

    def ensure_schema(self) -> None:
        client = self._client()
        try:
            client.command(STRATEGY_TEST_TRADES_DDL)
            client.command(STRATEGY_TEST_METRICS_DDL)
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

        query = """
            SELECT
                run_id,
                trade_id,
                user_id,
                mode,
                strategy_code,
                strategy_version,
                exchange,
                symbol,
                timeframe,
                direction,
                signal_score,
                market_regime,
                score_bucket,
                entry_time,
                exit_time,
                entry_price,
                exit_price,
                stop_loss,
                targets_json,
                selected_rr,
                realized_r,
                pnl,
                pnl_pct,
                fees,
                slippage,
                mfe_r,
                mae_r,
                bars_to_entry,
                bars_in_trade,
                close_reason,
                outcome,
                risk_rejected,
                execution_rejected,
                warnings_json,
                features_snapshot_json,
                trade_plan_json,
                tags,
                created_at
            FROM analytics.strategy_test_trades
            WHERE run_id = {run_id:UUID}
            ORDER BY entry_time ASC, trade_id ASC
            LIMIT {limit:UInt32} OFFSET {offset:UInt32}
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
        query = """
            SELECT
                run_id,
                user_id,
                mode,
                strategy_code,
                exchange,
                symbol,
                timeframe,
                market_regime,
                score_bucket,
                direction,
                metric_code,
                metric_value,
                sample_size,
                metadata_json,
                created_at
            FROM analytics.strategy_test_metrics
            WHERE run_id = {run_id:UUID}
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
            user = _resolve_user(session, request.user_id)
            now = datetime.now(timezone.utc)
            run = StrategyTestRun(
                id=uuid4(),
                user_id=user.id,
                requested_user_id=request.user_id,
                status="queued",
                mode=request.mode,
                requested_strategies=list(request.strategies),
                requested_pairs=[pair.model_dump(mode="json") for pair in request.pairs],
                requested_timeframes=list(request.timeframes),
                start_at=request.start_at,
                end_at=request.end_at,
                params=_stored_params(request),
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
                user = _resolve_user(session, user_id)
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

    def mark_running(self, run_id: UUID) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
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
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
            run.error = None
            session.flush()
            detail = _run_to_detail(run, summary=summary)
            session.commit()
            return detail

    def mark_failed(self, run_id: UUID, error: str) -> StrategyTestRunDetailResponse:
        with self._session_factory() as session:
            run = _get_run_or_raise(session, run_id)
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error = error
            session.flush()
            detail = _run_to_detail(run)
            session.commit()
            return detail


def _resolve_user(session: Session, user_id: str) -> AppUser:
    value = user_id.strip()
    if not value:
        raise ValueError(f"User is not seeded: {user_id}")

    if value == DEMO_PUBLIC_USER_ID:
        user = session.scalars(select(AppUser).where(AppUser.username == DEMO_USERNAME)).one_or_none()
        if user is not None:
            return user
        raise ValueError(f"User is not seeded: {user_id}")

    user_uuid = _parse_uuid(value)
    if user_uuid is not None:
        user = session.get(AppUser, user_uuid)
        if user is not None:
            return user
        raise ValueError(f"User is not seeded: {user_id}")

    user = session.scalars(
        select(AppUser).where((AppUser.username == value) | (AppUser.email == value))
    ).one_or_none()
    if user is not None:
        return user

    raise ValueError(f"User is not seeded: {user_id}")


def _get_run_or_raise(session: Session, run_id: UUID) -> StrategyTestRun:
    run = session.get(StrategyTestRun, run_id)
    if run is None:
        raise ValueError(f"Strategy test run is not found: {run_id}")
    return run


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
    *,
    summary: dict[str, Any] | None = None,
) -> StrategyTestRunDetailResponse:
    return StrategyTestRunDetailResponse(
        run=StrategyTestRunResponse(
            run_id=run.id,
            status=cast(StrategyTestRunStatus, run.status),
            requested_matrix=_requested_matrix(run),
            summary=summary or {},
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error=run.error,
        ),
    )


def _requested_matrix(run: StrategyTestRun) -> dict[str, Any]:
    params = run.params or {}
    request_params = params.get(REQUEST_PARAMS_KEY, params)
    return {
        "user_id": run.requested_user_id,
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


def _parse_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError:
        return None


def _trade_select_columns_sql() -> str:
    return ",\n                ".join(ClickHouseStrategyTestStore._trade_columns)


def _trade_to_clickhouse(trade: StrategyTestTrade) -> list[Any]:
    return [
        trade.run_id,
        trade.trade_id,
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


def _metric_to_clickhouse(row: StrategyTestMetricRow) -> list[Any]:
    return [
        row.run_id,
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
