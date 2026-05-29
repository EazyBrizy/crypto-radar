import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.clickhouse_client import close_clickhouse_client
from app.core.database import dispose_database_engine
from app.core.health import get_storage_health
from app.core.redis_client import close_redis_client
from app.core.config import settings
from app.services.market_scanner import DEFAULT_SYMBOLS, MarketScanner
from app.services.realtime_gateway import realtime_gateway
from app.workers.exchange_instrument_worker import ExchangeInstrumentRuleSyncRunner
from app.workers.signal_worker import ScannerRunner

load_dotenv()

logging.basicConfig(level=logging.INFO)

TICK_LIMIT = 5000


def _scanner_enabled() -> bool:
    raw_value = os.getenv("CRYPTO_RADAR_SCANNER_ENABLED", "true")
    return raw_value.strip().lower() not in {"0", "false", "no", "off"}


def _instrument_rule_sync_enabled() -> bool:
    return settings.exchange_instrument_sync_enabled


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runner = ScannerRunner()
    instrument_rule_runner = ExchangeInstrumentRuleSyncRunner()
    scanner_autostart_enabled = _scanner_enabled()
    instrument_rule_sync_enabled = _instrument_rule_sync_enabled()
    app.state.scanner_runner = runner
    app.state.exchange_instrument_rule_sync_runner = instrument_rule_runner
    app.state.scanner_autostart_enabled = scanner_autostart_enabled
    app.state.exchange_instrument_rule_sync_enabled = instrument_rule_sync_enabled

    realtime_gateway.start_broker_bridge()

    if instrument_rule_sync_enabled:
        instrument_rule_runner.start()
    else:
        logging.info("Exchange instrument rule sync disabled by settings")

    if scanner_autostart_enabled:
        runner.start()
    else:
        logging.info("Scanner runner disabled by CRYPTO_RADAR_SCANNER_ENABLED")

    try:
        yield
    finally:
        await instrument_rule_runner.stop()
        await runner.stop()
        await realtime_gateway.stop_broker_bridge()
        close_clickhouse_client()
        close_redis_client()
        dispose_database_engine()


app = FastAPI(title="Crypto Radar API", lifespan=lifespan)
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
    scanner_status = runner.scanner_status if runner else {}
    storage_health = await asyncio.to_thread(get_storage_health)
    return {
        "status": "ok" if storage_health["status"] == "ok" else "degraded",
        "scanner_enabled": runner is not None,
        "scanner_running": bool(runner and runner.is_running),
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
        "processed_signals": runner.processed_signals if runner else 0,
        "ticks_processed": scanner_status.get("ticks_processed", 0),
        "features_built": scanner_status.get("features_built", 0),
        "strategy_evaluations": scanner_status.get("strategy_evaluations", 0),
        "signals_found": scanner_status.get("signals_found", 0),
        "candles_seeded": scanner_status.get("candles_seeded", 0),
        "last_symbol": scanner_status.get("last_symbol"),
        "last_price": scanner_status.get("last_price"),
        "storage": storage_health,
    }


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
