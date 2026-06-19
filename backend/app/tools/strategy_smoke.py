from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

from app.core.database import SessionLocal
from app.schemas.candle import OHLCVCandle
from app.schemas.market import MarketData
from app.schemas.signal import SignalExecutionGateSnapshot, StrategySignal
from app.services.bootstrap_service import bootstrap_postgres_seed
from app.services.market_persistence import MarketDataPersistenceService
from app.services.strategy_testing.forward_runtime import ForwardRuntimeResult, ForwardStrategyTestRuntime
from app.services.strategy_testing.stores import ClickHouseStrategyTestStore


SMOKE_EXCHANGE = "bybit"
SMOKE_SYMBOL = "BTCUSDT"
SMOKE_STRATEGY = "trend_pullback_continuation"
SMOKE_TIMEFRAMES = ("5m", "15m")
SMOKE_FORWARD_TIMEFRAME = "15m"
DEFAULT_CANDLES_PER_TIMEFRAME = 12
DEFAULT_WARMUP_CANDLES = 3
DEFAULT_START_AT = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
_TIMEFRAME_MS = {"5m": 300_000, "15m": 900_000}


@dataclass(frozen=True)
class CandleSeedPlan:
    candles: list[OHLCVCandle]
    deduped_candles_by_timeframe: dict[str, int]
    duplicate_rows_by_timeframe: dict[str, int]
    warmup_candles: int

    @property
    def rows_total(self) -> int:
        return len(self.candles)

    @property
    def deduped_candles_total(self) -> int:
        return sum(self.deduped_candles_by_timeframe.values())

    @property
    def duplicate_rows_total(self) -> int:
        return sum(self.duplicate_rows_by_timeframe.values())

    @property
    def expected_bars_total(self) -> int:
        return sum(max(0, count - self.warmup_candles) for count in self.deduped_candles_by_timeframe.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_total": self.rows_total,
            "deduped_candles_total": self.deduped_candles_total,
            "duplicate_rows_total": self.duplicate_rows_total,
            "expected_bars_total": self.expected_bars_total,
            "warmup_candles": self.warmup_candles,
            "timeframes": list(self.deduped_candles_by_timeframe),
            "deduped_candles_by_timeframe": dict(self.deduped_candles_by_timeframe),
            "duplicate_rows_by_timeframe": dict(self.duplicate_rows_by_timeframe),
            "start_at": _ms_to_datetime(min(candle.open_time for candle in self.candles)).isoformat()
            if self.candles
            else None,
            "end_at": _ms_to_datetime(max(candle.close_time for candle in self.candles)).isoformat()
            if self.candles
            else None,
        }


def build_historical_run_payload(
    *,
    start_at: datetime = DEFAULT_START_AT,
    end_at: datetime | None = None,
    warmup_candles: int = DEFAULT_WARMUP_CANDLES,
) -> dict[str, Any]:
    end_at = end_at or start_at + timedelta(hours=4)
    return {
        "test_type": "historical_backtest",
        "strategies": [SMOKE_STRATEGY],
        "pairs": [{"exchange": SMOKE_EXCHANGE, "symbol": SMOKE_SYMBOL}],
        "timeframes": list(SMOKE_TIMEFRAMES),
        "start_at": _as_utc(start_at).isoformat(),
        "end_at": _as_utc(end_at).isoformat(),
        "mode": "research_virtual",
        "initial_capital": "1000",
        "fee_rate": "0.001",
        "slippage_bps": "0",
        "same_candle_policy": "conservative_stop_first",
        "params": {
            "warmup_candles": warmup_candles,
            "rolling_window_candles": warmup_candles,
            "historical_pending_entries_enabled": True,
            "pending_entry_max_wait_bars": 4,
            "auto_publish_calibration": False,
        },
        "metric_set": ["trades_count", "signals_count", "expectancy_r"],
        "tags": ["docker_smoke", "backtest"],
    }


def build_forward_run_payload(
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    start_at = start_at or datetime.now(timezone.utc) - timedelta(minutes=15)
    end_at = end_at or datetime.now(timezone.utc) + timedelta(hours=1)
    return {
        "test_type": "forward_virtual",
        "strategies": [SMOKE_STRATEGY],
        "pairs": [{"exchange": SMOKE_EXCHANGE, "symbol": SMOKE_SYMBOL}],
        "timeframes": [SMOKE_FORWARD_TIMEFRAME],
        "start_at": _as_utc(start_at).isoformat(),
        "end_at": _as_utc(end_at).isoformat(),
        "mode": "research_virtual",
        "initial_capital": "1000",
        "fee_rate": "0.001",
        "slippage_bps": "0",
        "same_candle_policy": "conservative_stop_first",
        "params": {
            "execution_policy": {"mode": "pending_retest"},
            "max_concurrent_positions": 3,
            "risk_settings": {
                "max_price_deviation_bps": 10000,
                "max_open_risk_percent": 100,
                "max_daily_loss_percent": 100,
                "max_account_drawdown_percent": 100,
            },
        },
        "metric_set": ["trades_count", "signals_count", "expectancy_r"],
        "tags": ["docker_smoke", "forward"],
    }


def build_candle_seed_plan(
    *,
    start_at: datetime = DEFAULT_START_AT,
    candles_per_timeframe: int = DEFAULT_CANDLES_PER_TIMEFRAME,
    warmup_candles: int = DEFAULT_WARMUP_CANDLES,
) -> CandleSeedPlan:
    candles: list[OHLCVCandle] = []
    deduped: dict[str, int] = {}
    duplicate_rows: dict[str, int] = {}
    base_candles = max(0, int(candles_per_timeframe))
    max_timeframe_ms = max(_TIMEFRAME_MS[timeframe] for timeframe in SMOKE_TIMEFRAMES)
    for timeframe in SMOKE_TIMEFRAMES:
        timeframe_ms = _TIMEFRAME_MS[timeframe]
        timeframe_candles = (base_candles * max_timeframe_ms) // timeframe_ms
        deduped[timeframe] = timeframe_candles
        duplicate_rows[timeframe] = 1 if timeframe_candles > 2 else 0
        for index in range(timeframe_candles):
            candles.append(_candle(timeframe=timeframe, start_at=start_at, index=index, timeframe_ms=timeframe_ms))
        if timeframe_candles > 2:
            candles.append(
                _candle(
                    timeframe=timeframe,
                    start_at=start_at,
                    index=2,
                    timeframe_ms=timeframe_ms,
                    duplicate_revision=True,
                )
            )
    return CandleSeedPlan(
        candles=candles,
        deduped_candles_by_timeframe=deduped,
        duplicate_rows_by_timeframe=duplicate_rows,
        warmup_candles=warmup_candles,
    )


def seed_clickhouse_candles(
    *,
    candles_per_timeframe: int = DEFAULT_CANDLES_PER_TIMEFRAME,
    warmup_candles: int = DEFAULT_WARMUP_CANDLES,
    start_at: datetime = DEFAULT_START_AT,
) -> dict[str, Any]:
    plan = build_candle_seed_plan(
        start_at=start_at,
        candles_per_timeframe=candles_per_timeframe,
        warmup_candles=warmup_candles,
    )
    service = MarketDataPersistenceService()
    warnings = service.ensure_ohlcv_schema()
    rows_written = service.persist_candles(plan.candles)
    return {
        **plan.to_dict(),
        "rows_written": rows_written,
        "schema_warnings": warnings,
    }


def bootstrap_seed() -> dict[str, Any]:
    with SessionLocal() as session:
        summary = bootstrap_postgres_seed(session)
        session.commit()
    return summary.to_dict()


def ensure_strategy_analytics_schema() -> dict[str, Any]:
    ClickHouseStrategyTestStore().ensure_schema()
    return {"strategy_analytics_schema": "ok"}


def build_forward_pending_signal(*, timestamp: int = 1_781_000_030) -> StrategySignal:
    return StrategySignal(
        exchange=SMOKE_EXCHANGE,
        symbol=SMOKE_SYMBOL,
        strategy=SMOKE_STRATEGY,
        direction="LONG",
        confidence=0.82,
        timestamp=timestamp,
        score=82,
        timeframe=SMOKE_FORWARD_TIMEFRAME,
        status="actionable",
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=95.0,
        take_profit_1=110.0,
        take_profit_2=115.0,
        risk_reward=2.0,
        explanation=["docker smoke pending retest signal"],
        execution_gate=SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="watchlist",
            can_notify=False,
            can_enter_now=False,
            can_arm_pending=True,
            can_arm_virtual_pending=True,
            can_show_in_execution_feed=False,
            metadata={"source": "docker_smoke"},
        ),
    )


async def feed_forward_signal() -> dict[str, Any]:
    result = await ForwardStrategyTestRuntime().process_strategy_signal(build_forward_pending_signal())
    return _forward_result_to_dict(result)


async def feed_forward_tick(*, price: float, timestamp: int) -> dict[str, Any]:
    result = await ForwardStrategyTestRuntime().process_market_tick(
        MarketData(
            exchange=SMOKE_EXCHANGE,
            symbol=SMOKE_SYMBOL,
            price=price,
            volume=1.0,
            timestamp=timestamp,
            bid=price,
            ask=price,
            last=price,
        )
    )
    return _forward_result_to_dict(result)


async def heartbeat_forward_runs() -> dict[str, Any]:
    result = ForwardStrategyTestRuntime().heartbeat_active_runs()
    return _forward_result_to_dict(result)


def _candle(
    *,
    timeframe: str,
    start_at: datetime,
    index: int,
    timeframe_ms: int,
    duplicate_revision: bool = False,
) -> OHLCVCandle:
    base_price = 100.0 + index
    if duplicate_revision:
        base_price += 0.25
    open_time = _datetime_to_ms(_as_utc(start_at)) + index * timeframe_ms
    return OHLCVCandle(
        exchange=SMOKE_EXCHANGE,
        symbol=SMOKE_SYMBOL,
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timeframe_ms - 1,
        open=base_price,
        high=base_price + 4.0,
        low=base_price - 3.0,
        close=base_price + 1.0,
        volume=1000.0 + index,
        trades=10 + index + (100 if duplicate_revision else 0),
        is_closed=True,
    )


def _forward_result_to_dict(result: ForwardRuntimeResult) -> dict[str, Any]:
    return {
        "ticks_processed": result.ticks_processed,
        "signals_processed": result.signals_processed,
        "signals_skipped": result.signals_skipped,
        "opened_trades": result.opened_trades,
        "closed_trades": result.closed_trades,
        "pending_entries_armed": result.pending_entries_armed,
        "trades_written": result.trades_written,
        "signal_events_written": result.signal_events_written,
        "metrics_written": result.metrics_written,
        "runtime_state_updates": result.runtime_state_updates,
        "cancelled_runs": result.cancelled_runs,
        "errors": list(result.errors),
    }


def _datetime_to_ms(value: datetime) -> int:
    return int(_as_utc(value).timestamp() * 1000)


def _ms_to_datetime(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Docker strategy-test smoke helper")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("bootstrap-seed")
    subcommands.add_parser("ensure-analytics-schema")

    seed = subcommands.add_parser("seed-candles")
    seed.add_argument("--candles-per-timeframe", type=int, default=DEFAULT_CANDLES_PER_TIMEFRAME)
    seed.add_argument("--warmup-candles", type=int, default=DEFAULT_WARMUP_CANDLES)
    seed.add_argument("--start-at", default=DEFAULT_START_AT.isoformat())

    historical = subcommands.add_parser("historical-payload")
    historical.add_argument("--start-at", default=DEFAULT_START_AT.isoformat())
    historical.add_argument("--end-at", default=None)
    historical.add_argument("--warmup-candles", type=int, default=DEFAULT_WARMUP_CANDLES)

    forward = subcommands.add_parser("forward-payload")
    forward.add_argument("--start-at", default=None)
    forward.add_argument("--end-at", default=None)

    tick = subcommands.add_parser("forward-tick")
    tick.add_argument("--price", type=float, required=True)
    tick.add_argument("--timestamp", type=int, required=True)

    subcommands.add_parser("forward-signal")
    subcommands.add_parser("forward-heartbeat")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.command == "bootstrap-seed":
        _print_json(bootstrap_seed())
    elif args.command == "ensure-analytics-schema":
        _print_json(ensure_strategy_analytics_schema())
    elif args.command == "seed-candles":
        _print_json(
            seed_clickhouse_candles(
                candles_per_timeframe=args.candles_per_timeframe,
                warmup_candles=args.warmup_candles,
                start_at=_parse_datetime(args.start_at),
            )
        )
    elif args.command == "historical-payload":
        _print_json(
            build_historical_run_payload(
                start_at=_parse_datetime(args.start_at),
                end_at=_parse_datetime(args.end_at) if args.end_at else None,
                warmup_candles=args.warmup_candles,
            )
        )
    elif args.command == "forward-payload":
        _print_json(
            build_forward_run_payload(
                start_at=_parse_datetime(args.start_at) if args.start_at else None,
                end_at=_parse_datetime(args.end_at) if args.end_at else None,
            )
        )
    elif args.command == "forward-tick":
        _print_json(asyncio.run(feed_forward_tick(price=args.price, timestamp=args.timestamp)))
    elif args.command == "forward-signal":
        _print_json(asyncio.run(feed_forward_signal()))
    elif args.command == "forward-heartbeat":
        _print_json(asyncio.run(heartbeat_forward_runs()))


if __name__ == "__main__":
    main()
