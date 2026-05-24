import asyncio
import logging

from app.services.market_scanner import DEFAULT_SYMBOLS, MarketScanner

logging.basicConfig(level=logging.INFO)

TICK_LIMIT = 5000


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


asyncio.run(main())
