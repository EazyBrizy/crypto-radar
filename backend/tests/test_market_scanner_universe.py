import asyncio
import contextlib
import time
import unittest
from unittest.mock import patch

from app.schemas.candle import OHLCVCandle
from app.schemas.market import MarketData
from app.services.candle_service import CandleService
from app.services.market_scanner import MarketScanner


class MarketScannerUniverseTest(unittest.IsolatedAsyncioTestCase):
    async def test_process_tick_skips_pairs_outside_scan_universe(self) -> None:
        scanner = MarketScanner(
            symbols=["BTCUSDT"],
            exchanges=["bybit"],
            scan_pairs=(("bybit", "XRPUSDT"),),
            candle_store=CandleService(timeframes=["1m"]),
            market_persistence=None,
            market_quality=None,
            support_resistance=None,
            signal_lifecycle=None,
            signal_outcomes=None,
            trade_invalidation=None,
            strategy_configs=None,
            virtual_trading=None,
            pending_entry_trigger=None,
            derivative_market=None,
            alpha_market_context=None,
        )

        signals = await scanner.process_tick(
            MarketData(
                exchange="bybit",
                symbol="BTCUSDT",
                price=100.0,
                volume=1.0,
                timestamp=1_779_796_800_000,
            )
        )

        self.assertEqual(signals, [])
        self.assertEqual(scanner.symbols, ["XRPUSDT"])
        self.assertEqual(scanner.stats["scanner_pairs_count"], 1)
        self.assertEqual(scanner.stats["scan_pairs"], ["bybit:XRPUSDT"])
        self.assertEqual(scanner.stats["ticks_processed"], 0)

    async def test_empty_scan_pairs_keeps_scanner_blocked(self) -> None:
        scanner = MarketScanner(
            symbols=[],
            exchanges=[],
            scan_pairs=[],
            candle_store=CandleService(timeframes=["1m"]),
            market_persistence=None,
            market_quality=None,
            support_resistance=None,
            signal_lifecycle=None,
            signal_outcomes=None,
            trade_invalidation=None,
            strategy_configs=None,
            virtual_trading=None,
            pending_entry_trigger=None,
            derivative_market=None,
            alpha_market_context=None,
            universe_source="blocked",
            universe_warning="Scanner start is blocked.",
        )

        self.assertEqual(scanner.symbols, [])
        self.assertEqual(scanner.exchanges, [])
        self.assertEqual(scanner.stats["scanner_pairs_count"], 0)
        self.assertEqual(scanner.stats["scanner_universe_source"], "blocked")

    async def test_warmup_progress_counts_completed_and_failed_items(self) -> None:
        candle_store = CandleService(timeframes=["1m", "5m"])
        scanner = MarketScanner(
            symbols=["BTCUSDT"],
            exchanges=["bybit"],
            candle_store=candle_store,
            market_persistence=None,
            market_quality=None,
            support_resistance=None,
            signal_lifecycle=None,
            signal_outcomes=None,
            trade_invalidation=None,
            strategy_configs=None,
            virtual_trading=None,
            pending_entry_trigger=None,
            derivative_market=None,
            alpha_market_context=None,
            warmup_concurrency=2,
            warmup_timeout_seconds=1,
        )

        def fake_fetch(symbol: str, timeframe: str, limit: int) -> list[OHLCVCandle]:
            if timeframe == "5m":
                raise TimeoutError("boom")
            return [
                OHLCVCandle(
                    exchange="bybit",
                    symbol=symbol,
                    timeframe="1m",
                    open_time=1_779_796_800_000,
                    close_time=1_779_796_859_999,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=1,
                    trades=1,
                    is_closed=True,
                )
            ]

        with patch("app.services.market_scanner.fetch_bybit_klines", side_effect=fake_fetch):
            await scanner._warm_up_history()

        stats = scanner.stats
        self.assertEqual(stats["warmup_total"], 2)
        self.assertEqual(stats["warmup_completed"], 2)
        self.assertEqual(stats["warmup_failed"], 1)
        self.assertEqual(stats["candles_seeded"], 1)
        self.assertIsNotNone(stats["warmup_started_at"])
        self.assertIsNotNone(stats["warmup_finished_at"])

    async def test_start_processes_live_tick_before_full_warmup_finishes(self) -> None:
        scanner = NonBlockingWarmupScanner()
        task = asyncio.create_task(_consume_scanner(scanner))

        await asyncio.wait_for(scanner.warmup_started.wait(), timeout=0.5)
        for _ in range(50):
            if scanner.stats["ticks_processed"] == 1:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(scanner.stats["ticks_processed"], 1)
        self.assertEqual(scanner.stats["warmup_completed"], 0)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def test_process_tick_forwards_market_tick_after_virtual_lifecycle(self) -> None:
        tick = MarketData(
            exchange="bybit",
            symbol="BTCUSDT",
            price=100.5,
            volume=1.0,
            timestamp=1_779_796_800_000,
        )
        events: list[str] = []
        lifecycle = _RecordingVirtualLifecycle(events)
        pending = _RecordingPendingEntryTrigger(events)
        forward = _RecordingForwardStrategyTests(events)
        scanner = MarketScanner(
            symbols=["BTCUSDT"],
            exchanges=["bybit"],
            candle_store=CandleService(timeframes=["1m"]),
            market_persistence=None,
            market_quality=None,
            support_resistance=None,
            signal_lifecycle=None,
            signal_outcomes=None,
            trade_invalidation=None,
            strategy_configs=None,
            virtual_trading=lifecycle,  # type: ignore[arg-type]
            pending_entry_trigger=pending,  # type: ignore[arg-type]
            derivative_market=None,
            alpha_market_context=None,
            forward_strategy_tests=forward,  # type: ignore[arg-type]
        )

        signals = await scanner.process_tick(tick)

        self.assertEqual(signals, [])
        self.assertEqual(forward.ticks, [tick])
        self.assertEqual(events, ["virtual_positions", "pending_entries", "forward_tick"])

    async def test_forward_market_tick_error_is_logged_and_does_not_stop_scanner(self) -> None:
        scanner = MarketScanner(
            symbols=["BTCUSDT"],
            exchanges=["bybit"],
            candle_store=CandleService(timeframes=["1m"]),
            market_persistence=None,
            market_quality=None,
            support_resistance=None,
            signal_lifecycle=None,
            signal_outcomes=None,
            trade_invalidation=None,
            strategy_configs=None,
            virtual_trading=None,
            pending_entry_trigger=None,
            derivative_market=None,
            alpha_market_context=None,
            forward_strategy_tests=_FailingForwardStrategyTests(),  # type: ignore[arg-type]
        )

        with self.assertLogs("app.services.market_scanner", level="WARNING") as logs:
            signals = await scanner.process_tick(
                MarketData(
                    exchange="bybit",
                    symbol="BTCUSDT",
                    price=100.0,
                    volume=1.0,
                    timestamp=1_779_796_800_000,
                )
            )

        self.assertEqual(signals, [])
        self.assertIn("Forward strategy test market tick skipped: forward failed", "\n".join(logs.output))


class NonBlockingWarmupScanner(MarketScanner):
    def __init__(self) -> None:
        self.warmup_started = asyncio.Event()
        self.release_warmup = asyncio.Event()
        super().__init__(
            symbols=["BTCUSDT"],
            exchanges=["bybit"],
            candle_store=CandleService(timeframes=["1m"]),
            market_persistence=None,
            market_quality=None,
            support_resistance=None,
            signal_lifecycle=None,
            signal_outcomes=None,
            trade_invalidation=None,
            strategy_configs=None,
            virtual_trading=None,
            pending_entry_trigger=None,
            derivative_market=None,
            alpha_market_context=None,
        )

    async def _warm_up_history(self) -> None:
        self._history_warmup_in_progress = True
        self._stats.warmup_total = 1
        self._stats.warmup_started_at = int(time.time() * 1000)
        self.warmup_started.set()
        try:
            await self.release_warmup.wait()
            self._stats.warmup_completed = 1
            self._stats.warmup_finished_at = int(time.time() * 1000)
        finally:
            self._history_warmup_in_progress = False

    def listen(self):
        return self._listen()

    async def _listen(self):
        await self.warmup_started.wait()
        yield MarketData(
            exchange="bybit",
            symbol="BTCUSDT",
            price=100,
            volume=1,
            timestamp=1_779_796_800_000,
        )
        await asyncio.Event().wait()


async def _consume_scanner(scanner: MarketScanner) -> None:
    async for _ in scanner.start():
        pass


class _RecordingVirtualLifecycle:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def process_virtual_positions_tick(
        self,
        exchange: str,
        symbol: str,
        market_tick_or_candle: object,
    ) -> list[object]:
        _ = exchange, symbol, market_tick_or_candle
        self._events.append("virtual_positions")
        return []


class _RecordingPendingEntryTrigger:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def process_market_tick(self, exchange: str, symbol: str, market_tick: MarketData) -> list[object]:
        _ = exchange, symbol, market_tick
        self._events.append("pending_entries")
        return []


class _RecordingForwardStrategyTests:
    ticks: list[MarketData]

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.ticks = []

    async def process_market_tick(self, tick: MarketData) -> object:
        self._events.append("forward_tick")
        self.ticks.append(tick)
        return object()


class _FailingForwardStrategyTests:
    async def process_market_tick(self, tick: MarketData) -> object:
        _ = tick
        raise RuntimeError("forward failed")


if __name__ == "__main__":
    unittest.main()
