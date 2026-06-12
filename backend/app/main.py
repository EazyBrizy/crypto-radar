import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1.router import api_router
from app.core.clickhouse_client import close_clickhouse_client
from app.core.database import dispose_database_engine
from app.core.health import get_storage_health
from app.core.migrations import warn_if_migrations_outdated
from app.core.redis_client import close_redis_client
from app.core.config import settings
from app.core.request_timing import add_request_timing_middleware
from app.services.market_scanner import DEFAULT_SYMBOLS, MarketScanner
from app.services.realtime_gateway import realtime_gateway
from app.services.trading_kill_switch import scanner_kill_switch_payload
from app.workers.derivative_snapshot_worker import DerivativeSnapshotSyncRunner
from app.workers.exchange_instrument_worker import ExchangeInstrumentRuleSyncRunner
from app.workers.forward_strategy_test_worker import ForwardStrategyTestWorker
from app.workers.orderbook_snapshot_worker import OrderbookSnapshotWorker
from app.workers.real_position_sync_worker import BybitRealPositionSyncClient, RealPositionSyncWorker
from app.workers.signal_worker import ScannerRunner, SignalExpiryWorker

load_dotenv()

logging.basicConfig(level=logging.INFO)

TICK_LIMIT = 5000


def _scanner_enabled() -> bool:
    raw_value = os.getenv("CRYPTO_RADAR_SCANNER_ENABLED")
    if raw_value is None:
        return settings.crypto_radar_scanner_enabled
    return raw_value.strip().lower() not in {"0", "false", "no", "off"}


def _instrument_rule_sync_enabled() -> bool:
    return settings.exchange_instrument_sync_enabled


def _derivative_snapshot_sync_enabled() -> bool:
    return settings.derivative_snapshot_sync_enabled


def _orderbook_snapshot_sync_enabled() -> bool:
    return settings.orderbook_snapshot_sync_enabled


def _real_position_sync_enabled() -> bool:
    return settings.real_position_sync_enabled


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    forward_strategy_test_worker = ForwardStrategyTestWorker()
    runner = ScannerRunner(forward_strategy_tests=forward_strategy_test_worker)
    instrument_rule_runner = ExchangeInstrumentRuleSyncRunner()
    derivative_snapshot_runner = DerivativeSnapshotSyncRunner()
    orderbook_snapshot_worker = OrderbookSnapshotWorker()
    signal_expiry_worker = SignalExpiryWorker()
    real_position_sync_worker = RealPositionSyncWorker(
        client=BybitRealPositionSyncClient(),
        interval_seconds=settings.real_position_sync_interval_seconds,
    )
    scanner_autostart_enabled = _scanner_enabled()
    instrument_rule_sync_enabled = _instrument_rule_sync_enabled()
    derivative_snapshot_sync_enabled = _derivative_snapshot_sync_enabled()
    orderbook_snapshot_sync_enabled = _orderbook_snapshot_sync_enabled()
    real_position_sync_enabled = _real_position_sync_enabled()
    app.state.scanner_runner = runner
    app.state.exchange_instrument_rule_sync_runner = instrument_rule_runner
    app.state.derivative_snapshot_sync_runner = derivative_snapshot_runner
    app.state.orderbook_snapshot_worker = orderbook_snapshot_worker
    app.state.signal_expiry_worker = signal_expiry_worker
    app.state.real_position_sync_worker = real_position_sync_worker
    app.state.forward_strategy_test_worker = forward_strategy_test_worker
    app.state.scanner_autostart_enabled = scanner_autostart_enabled
    app.state.exchange_instrument_rule_sync_enabled = instrument_rule_sync_enabled
    app.state.derivative_snapshot_sync_enabled = derivative_snapshot_sync_enabled
    app.state.orderbook_snapshot_sync_enabled = orderbook_snapshot_sync_enabled
    app.state.real_position_sync_enabled = real_position_sync_enabled

    await asyncio.to_thread(warn_if_migrations_outdated)

    realtime_gateway.start_broker_bridge()

    if instrument_rule_sync_enabled:
        instrument_rule_runner.start()
    else:
        logging.info("Exchange instrument rule sync disabled by settings")

    if derivative_snapshot_sync_enabled:
        derivative_snapshot_runner.start()
    else:
        logging.info("Derivative snapshot sync disabled by settings")

    if orderbook_snapshot_sync_enabled:
        orderbook_snapshot_worker.start()
    else:
        logging.info("Orderbook snapshot sync disabled by settings")

    signal_expiry_worker.start()

    if real_position_sync_enabled:
        real_position_sync_worker.start()
    else:
        logging.info("Real position sync disabled by settings")

    forward_strategy_test_worker.start()

    if scanner_autostart_enabled:
        runner.start()
    else:
        logging.info("Scanner runner disabled by CRYPTO_RADAR_SCANNER_ENABLED")

    try:
        yield
    finally:
        await runner.stop()
        await forward_strategy_test_worker.stop()
        await signal_expiry_worker.stop()
        await orderbook_snapshot_worker.stop()
        await real_position_sync_worker.stop()
        await derivative_snapshot_runner.stop()
        await instrument_rule_runner.stop()
        await realtime_gateway.stop_broker_bridge()
        close_clickhouse_client()
        close_redis_client()
        dispose_database_engine()


app = FastAPI(title="Crypto Radar API", lifespan=lifespan)
add_request_timing_middleware(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, object]:
    runner = getattr(app.state, "scanner_runner", None)
    instrument_rule_runner = getattr(app.state, "exchange_instrument_rule_sync_runner", None)
    derivative_snapshot_runner = getattr(app.state, "derivative_snapshot_sync_runner", None)
    orderbook_snapshot_worker = getattr(app.state, "orderbook_snapshot_worker", None)
    real_position_sync_worker = getattr(app.state, "real_position_sync_worker", None)
    forward_strategy_test_worker = getattr(app.state, "forward_strategy_test_worker", None)
    scanner_status = runner.scanner_status if runner else {}
    storage_health = await asyncio.to_thread(get_storage_health)
    scanner_running = bool(runner and runner.is_running)
    kill_switch = scanner_kill_switch_payload(
        scanner_status,
        scanner_running=scanner_running,
        max_stale_data_seconds=settings.scanner_market_data_stale_seconds,
    )
    return {
        "status": "ok" if storage_health["status"] == "ok" else "degraded",
        "scanner_enabled": runner is not None,
        "scanner_running": scanner_running,
        "scanner_stopping": bool(runner and runner.is_stopping),
        "instrument_rule_sync_enabled": bool(
            getattr(app.state, "exchange_instrument_rule_sync_enabled", False)
        ),
        "instrument_rule_sync_running": bool(
            instrument_rule_runner and instrument_rule_runner.is_running
        ),
        "instrument_rule_sync_last_result": (
            instrument_rule_runner.last_result
            if instrument_rule_runner is not None
            else {}
        ),
        "derivative_snapshot_sync_enabled": bool(
            getattr(app.state, "derivative_snapshot_sync_enabled", False)
        ),
        "derivative_snapshot_sync_running": bool(
            derivative_snapshot_runner and derivative_snapshot_runner.is_running
        ),
        "derivative_snapshot_sync_last_result": (
            derivative_snapshot_runner.last_result
            if derivative_snapshot_runner is not None
            else {}
        ),
        "orderbook_snapshot_sync_enabled": bool(
            getattr(app.state, "orderbook_snapshot_sync_enabled", False)
        ),
        "orderbook_snapshot_sync_running": bool(
            orderbook_snapshot_worker and orderbook_snapshot_worker.is_running
        ),
        "orderbook_snapshot_sync_last_result": (
            orderbook_snapshot_worker.last_result
            if orderbook_snapshot_worker is not None
            else {}
        ),
        "real_position_sync_enabled": bool(
            getattr(app.state, "real_position_sync_enabled", False)
        ),
        "real_position_sync_running": bool(
            real_position_sync_worker and real_position_sync_worker.is_running
        ),
        "real_position_sync_last_result": (
            real_position_sync_worker.last_result
            if real_position_sync_worker is not None
            else {}
        ),
        "forward_strategy_test_running": bool(
            forward_strategy_test_worker and forward_strategy_test_worker.is_running
        ),
        "forward_strategy_test_stopping": bool(
            forward_strategy_test_worker and forward_strategy_test_worker.is_stopping
        ),
        "forward_strategy_test_last_result": (
            asdict(forward_strategy_test_worker.last_result)
            if forward_strategy_test_worker is not None
            else {}
        ),
        "processed_signals": runner.processed_signals if runner else 0,
        "scanner_pairs_count": scanner_status.get("scanner_pairs_count", 0),
        "scanner_universe_source": scanner_status.get("scanner_universe_source", "default"),
        "scanner_universe_warning": scanner_status.get("scanner_universe_warning"),
        "estimated_strategy_checks": scanner_status.get("estimated_strategy_checks", 0),
        "max_scanner_pairs": scanner_status.get("max_scanner_pairs"),
        "stage": scanner_status.get("stage", "stopped"),
        "market_data_status": scanner_status.get("market_data_status", "offline"),
        "warmup_total": scanner_status.get("warmup_total", 0),
        "warmup_completed": scanner_status.get("warmup_completed", 0),
        "warmup_failed": scanner_status.get("warmup_failed", 0),
        "warmup_started_at": scanner_status.get("warmup_started_at"),
        "warmup_finished_at": scanner_status.get("warmup_finished_at"),
        "ticks_processed": scanner_status.get("ticks_processed", 0),
        "last_tick_age_seconds": scanner_status.get("last_tick_age_seconds"),
        "last_error": scanner_status.get("last_error"),
        "market_stream_connected": scanner_status.get("market_stream_connected", False),
        "ws_connected": scanner_status.get("ws_connected", False),
        "features_built": scanner_status.get("features_built", 0),
        "strategy_evaluations": scanner_status.get("strategy_evaluations", 0),
        "signals_found": scanner_status.get("signals_found", 0),
        "candles_seeded": scanner_status.get("candles_seeded", 0),
        "last_symbol": scanner_status.get("last_symbol"),
        "last_price": scanner_status.get("last_price"),
        "kill_switch": kill_switch,
        "storage": storage_health,
    }


@app.get("/metrics")
async def metrics() -> Response:
    if not settings.prometheus_metrics_enabled:
        return Response("", media_type=CONTENT_TYPE_LATEST)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def main() -> None:
    scanner = MarketScanner(DEFAULT_SYMBOLS)
    count = 0
    signal_count = 0

    async for tick in scanner.listen():
        signals = await scanner.process_tick(tick)
        signal_count += len(signals)
        count += 1

        if count >= TICK_LIMIT:
            print(
                f"Done: processed {count} ticks, signals={signal_count} "
                f"symbols={len(DEFAULT_SYMBOLS)}."
            )
            break


if __name__ == "__main__":
    asyncio.run(main())
