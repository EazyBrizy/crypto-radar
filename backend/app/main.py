import asyncio
import logging

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.services.market_scanner import DEFAULT_SYMBOLS, MarketScanner

logging.basicConfig(level=logging.INFO)

TICK_LIMIT = 5000

app = FastAPI(title="Crypto Radar API")
app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
