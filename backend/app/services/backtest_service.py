from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.core.clickhouse_client import create_clickhouse_client
from app.schemas.backtest import (
    BacktestNotReadyResponse,
    BacktestResultResponse,
    BacktestRunRequest,
    BacktestRunResult,
)


BACKTEST_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS analytics.backtest_results
(
    run_id UUID,
    user_id UUID,
    strategy_code LowCardinality(String),
    strategy_version String,
    exchange LowCardinality(String),
    symbol LowCardinality(String),
    timeframe LowCardinality(String),
    start_ts DateTime64(3, 'UTC'),
    end_ts DateTime64(3, 'UTC'),
    initial_capital Decimal(38, 18),
    final_equity Decimal(38, 18),
    pnl Decimal(38, 18),
    pnl_pct Float64,
    max_drawdown_pct Float64,
    trades_count UInt64,
    wins_count UInt64,
    losses_count UInt64,
    metrics_json String,
    equity_curve_json String,
    created_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (user_id, strategy_code, exchange, symbol, timeframe, created_at, run_id)
"""


class ClickHouseClient(Protocol):
    def command(self, command: str) -> Any:
        ...

    def insert(self, table: str, data: list[list[Any]], column_names: list[str]) -> None:
        ...

    def query(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
        ...


class BacktestRunner(Protocol):
    def run(self, request: BacktestRunRequest) -> BacktestRunResult:
        ...


class BacktestNotReadyError(NotImplementedError):
    def __init__(self, response: BacktestNotReadyResponse) -> None:
        super().__init__(response.message)
        self.response = response


class ClickHouseBacktestResultStore:
    _columns = [
        "run_id",
        "user_id",
        "strategy_code",
        "strategy_version",
        "exchange",
        "symbol",
        "timeframe",
        "start_ts",
        "end_ts",
        "initial_capital",
        "final_equity",
        "pnl",
        "pnl_pct",
        "max_drawdown_pct",
        "trades_count",
        "wins_count",
        "losses_count",
        "metrics_json",
        "equity_curve_json",
        "created_at",
    ]

    def __init__(self, clickhouse_client_factory: Any = create_clickhouse_client) -> None:
        self._clickhouse_client_factory = clickhouse_client_factory

    def ensure_schema(self) -> None:
        client = self._client()
        try:
            client.command(BACKTEST_RESULTS_DDL)
        finally:
            self._close_client(client)

    def write_result(self, result: BacktestResultResponse) -> None:
        client = self._client()
        try:
            client.insert(
                "analytics.backtest_results",
                [
                    [
                        result.run_id,
                        result.user_id,
                        result.strategy_code,
                        result.strategy_version,
                        result.exchange,
                        result.symbol,
                        result.timeframe,
                        result.start_at,
                        result.end_at,
                        result.initial_capital,
                        result.final_equity,
                        result.pnl,
                        result.pnl_pct,
                        result.max_drawdown_pct,
                        result.trades_count,
                        result.wins_count,
                        result.losses_count,
                        json.dumps(result.metrics, ensure_ascii=False, default=str, separators=(",", ":")),
                        json.dumps(result.equity_curve, ensure_ascii=False, default=str, separators=(",", ":")),
                        result.created_at,
                    ]
                ],
                column_names=self._columns,
            )
        finally:
            self._close_client(client)

    def list_results(
        self,
        *,
        user_id: UUID | None = None,
        limit: int = 50,
    ) -> list[BacktestResultResponse]:
        where_clause = ""
        parameters: dict[str, Any] = {"limit": limit}
        if user_id is not None:
            where_clause = "WHERE user_id = {user_id:UUID}"
            parameters["user_id"] = user_id
        query = f"""
            SELECT
                run_id,
                user_id,
                strategy_code,
                strategy_version,
                exchange,
                symbol,
                timeframe,
                start_ts,
                end_ts,
                initial_capital,
                final_equity,
                pnl,
                pnl_pct,
                max_drawdown_pct,
                trades_count,
                wins_count,
                losses_count,
                metrics_json,
                equity_curve_json,
                created_at
            FROM analytics.backtest_results
            {where_clause}
            ORDER BY created_at DESC
            LIMIT {{limit:UInt32}}
        """
        client = self._client()
        try:
            result = client.query(query, parameters=parameters)
            rows = result.named_results() if hasattr(result, "named_results") else []
            return [_row_to_result(row) for row in rows]
        finally:
            self._close_client(client)

    def _client(self) -> ClickHouseClient:
        return self._clickhouse_client_factory()

    @staticmethod
    def _close_client(client: ClickHouseClient) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()


class BacktestService:
    def __init__(
        self,
        result_store: ClickHouseBacktestResultStore | None = None,
        runner: BacktestRunner | None = None,
    ) -> None:
        self._result_store = result_store or ClickHouseBacktestResultStore()
        self._runner = runner

    def ensure_schema(self) -> None:
        self._result_store.ensure_schema()

    def run_backtest(self, request: BacktestRunRequest) -> BacktestRunResult:
        if request.end_at <= request.start_at:
            raise ValueError("Backtest end_at must be later than start_at")
        if self._runner is None:
            raise BacktestNotReadyError(
                BacktestNotReadyResponse(
                    message=(
                        "Backtest worker is not implemented yet. "
                        "Results are reserved for ClickHouse analytics.backtest_results."
                    ),
                    details={
                        "strategy_code": request.strategy_code,
                        "strategy_version": request.strategy_version,
                        "exchange": request.exchange,
                        "symbol": request.symbol,
                        "timeframe": request.timeframe,
                        "start_at": request.start_at.isoformat(),
                        "end_at": request.end_at.isoformat(),
                        "params_keys": sorted(request.params.keys()),
                    },
                )
            )
        result = self._runner.run(request)
        if result.result is not None:
            self._result_store.write_result(result.result)
        return result

    def list_results(self, *, user_id: UUID | None = None, limit: int = 50) -> list[BacktestResultResponse]:
        return self._result_store.list_results(user_id=user_id, limit=limit)


def _row_to_result(row: dict[str, Any]) -> BacktestResultResponse:
    return BacktestResultResponse(
        run_id=row["run_id"],
        user_id=row["user_id"],
        strategy_code=row["strategy_code"],
        strategy_version=row["strategy_version"],
        exchange=row["exchange"],
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        start_at=_as_utc(row["start_ts"]),
        end_at=_as_utc(row["end_ts"]),
        initial_capital=_decimal(row["initial_capital"]),
        final_equity=_decimal(row["final_equity"]),
        pnl=_decimal(row["pnl"]),
        pnl_pct=float(row["pnl_pct"]),
        max_drawdown_pct=float(row["max_drawdown_pct"]),
        trades_count=int(row["trades_count"]),
        wins_count=int(row["wins_count"]),
        losses_count=int(row["losses_count"]),
        metrics=_loads_json(row.get("metrics_json"), {}),
        equity_curve=_loads_json(row.get("equity_curve_json"), []),
        created_at=_as_utc(row["created_at"]),
    )


def _loads_json(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


backtest_service = BacktestService()
