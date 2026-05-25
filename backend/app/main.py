import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.services.market_scanner import DEFAULT_SYMBOLS, MarketScanner
from app.workers.signal_worker import ScannerRunner

load_dotenv()

logging.basicConfig(level=logging.INFO)

TICK_LIMIT = 5000


def _scanner_enabled() -> bool:
    raw_value = os.getenv("CRYPTO_RADAR_SCANNER_ENABLED", "true")
    return raw_value.strip().lower() not in {"0", "false", "no", "off"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    runner = ScannerRunner()
    app.state.scanner_runner = runner

    if _scanner_enabled():
        runner.start()
    else:
        logging.info("Scanner runner disabled by CRYPTO_RADAR_SCANNER_ENABLED")

    try:
        yield
    finally:
        await runner.stop()


app = FastAPI(title="Crypto Radar API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
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
    return {
        "status": "ok",
        "scanner_enabled": _scanner_enabled(),
        "scanner_running": bool(runner and runner.is_running),
        "processed_signals": runner.processed_signals if runner else 0,
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
