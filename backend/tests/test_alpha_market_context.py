import unittest
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.schemas.candle import OHLCVCandle
from app.schemas.market import (
    AlphaMarketContext,
    Features,
    MarketData,
    OrderBookLevel,
    OrderBookSnapshot,
    RecentTrade,
    TradeSide,
)
from app.schemas.signal import StrategySignal
from app.services.alpha_market_context import AlphaMarketContextService
from app.services.candle_service import CandleService
from app.services.derivative_market import DerivativeMarketSnapshot
from app.services.market_scanner import MarketScanner
from app.strategies.engine import StrategyEngine


class AlphaMarketContextSchemaTest(unittest.TestCase):
    def test_alpha_context_schema_optional_fields(self) -> None:
        context = AlphaMarketContext(
            symbol="BTCUSDT",
            timeframe="1m",
            timestamp=1_779_796_800_000,
        )

        self.assertIsNone(context.buy_volume)
        self.assertIsNone(context.orderbook_imbalance)
        self.assertEqual(context.session_liquidity_pools, [])
        self.assertEqual(context.data_quality, {})


class AlphaMarketContextServiceTest(unittest.TestCase):
    def test_recent_trades_aggregation_with_side(self) -> None:
        aggregate = AlphaMarketContextService().aggregate_recent_trades(
            [
                _trade(quantity=2.5, side="buy"),
                _trade(quantity=1.0, side="sell"),
                _trade(quantity=0.5, side="buy"),
            ]
        )

        self.assertTrue(aggregate.side_available)
        self.assertEqual(aggregate.buy_volume, 3.0)
        self.assertEqual(aggregate.sell_volume, 1.0)
        self.assertEqual(aggregate.aggressive_delta, 2.0)
        self.assertEqual(aggregate.cvd, 2.0)
        self.assertIn("recent_trades", aggregate.metadata["available_sources"])

    def test_recent_trades_aggregation_without_side_marks_missing(self) -> None:
        aggregate = AlphaMarketContextService().aggregate_recent_trades(
            [
                _trade(quantity=2.5, side=None),
                _trade(quantity=1.0, side=None),
            ]
        )

        self.assertFalse(aggregate.side_available)
        self.assertIsNone(aggregate.buy_volume)
        self.assertIsNone(aggregate.sell_volume)
        self.assertIsNone(aggregate.aggressive_delta)
        self.assertIn("recent_trade_side", aggregate.metadata["missing_sources"])

    def test_orderbook_imbalance_calculation(self) -> None:
        service = AlphaMarketContextService()
        context = service.build_context(
            features=_features(),
            recent_trades=[],
            orderbook=_orderbook(
                bid_depth=100.0,
                ask_depth=300.0,
                bids=[(100.0, 1.0)],
                asks=[(101.0, 3.0)],
            ),
        )

        self.assertAlmostEqual(context.orderbook_imbalance or 0.0, -0.5)
        self.assertEqual(context.bid_depth_usd, 100.0)
        self.assertEqual(context.ask_depth_usd, 300.0)
        self.assertIn("orderbook_l2", context.data_quality["available_sources"])

    def test_depth_wall_detection(self) -> None:
        features = AlphaMarketContextService().orderbook_alpha_features(
            _orderbook(
                bid_depth=2_000.0,
                ask_depth=250.0,
                bids=[(100.0, 20.0), (99.5, 1.0)],
                asks=[(101.0, 1.0), (101.5, 1.0)],
            )
        )

        self.assertEqual(features.depth_wall_side, "bid")
        self.assertEqual(features.depth_wall_price, 100.0)

    def test_oi_funding_windows_missing_history_graceful(self) -> None:
        derivative = DerivativeMarketSnapshot(
            exchange="bybit",
            symbol="BTCUSDT",
            funding_rate=0.00075,
            open_interest=1_000.0,
            open_interest_value=50_000_000.0,
            oi_change=0.02,
            source="test",
            fetched_at=datetime.now(timezone.utc),
        )

        features = AlphaMarketContextService().derivative_alpha_features(
            derivative_snapshot=derivative,
            derivative_history=[],
        )

        self.assertEqual(features.oi_delta_5m, 0.02)
        self.assertIsNone(features.oi_delta_15m)
        self.assertAlmostEqual(features.funding_pressure or 0.0, 0.5)
        self.assertIn("derivative_history", features.metadata["missing_sources"])


class StrategyEngineAlphaContextTest(unittest.IsolatedAsyncioTestCase):
    async def test_strategy_engine_passes_alpha_context_to_strategy_params(self) -> None:
        engine = StrategyEngine()
        strategy = _AlphaRecordingStrategy()
        engine._strategies = [strategy]  # noqa: SLF001
        alpha_context = AlphaMarketContext(
            symbol="BTCUSDT",
            timeframe="1m",
            timestamp=1_779_796_800_000,
        )

        await engine.generate_signals(_features(), alpha_context=alpha_context)

        self.assertIs(strategy.seen_alpha_context, alpha_context)


class MarketScannerAlphaContextTest(unittest.IsolatedAsyncioTestCase):
    async def test_market_scanner_passes_alpha_context_to_engine(self) -> None:
        candle_store = CandleService(timeframes=["1m"])
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candle_store.seed_history(
            [
                _candle(start + index * 60_000)
                for index in range(70)
            ]
        )
        alpha_service = _FakeAlphaMarketContextService()
        strategy_engine = _RecordingStrategyEngine()
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
            derivative_market=None,
            alpha_market_context=alpha_service,
        )
        scanner._strategy_engine = strategy_engine  # noqa: SLF001

        await scanner.process_tick(
            MarketData(
                exchange="bybit",
                symbol="BTCUSDT",
                timestamp=start + 70 * 60_000,
                price=100.5,
                volume=5.0,
                side="buy",
            )
        )

        self.assertEqual(alpha_service.recent_trade_counts[-1], 1)
        self.assertIsNotNone(strategy_engine.alpha_contexts[-1])
        self.assertEqual(strategy_engine.alpha_contexts[-1].data_quality["source"], "test")


def _features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1m",
        timestamp=1_779_796_800_000,
        price=100.0,
        open=99.5,
        high=101.0,
        low=98.0,
        close=100.0,
        price_change_1m=0.01,
        previous_high=100.5,
        previous_low=98.5,
        volume=10.0,
        volume_spike=1.0,
        volume_ma_20=10.0,
        volatility=1.0,
        history_length=70,
        vwap=99.0,
        session_high=102.0,
        session_low=97.0,
        previous_day_high=101.0,
        previous_day_low=96.0,
        swing_high=103.0,
        swing_low=95.0,
    )


def _trade(*, quantity: float, side: TradeSide | None) -> RecentTrade:
    return RecentTrade(
        exchange="bybit",
        symbol="BTCUSDT",
        price=100.0,
        quantity=quantity,
        timestamp=1_779_796_800_000,
        side=side,
    )


def _orderbook(
    *,
    bid_depth: float,
    ask_depth: float,
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        exchange="bybit",
        symbol="BTCUSDT",
        category="linear",
        bids=[OrderBookLevel(price=price, quantity=quantity) for price, quantity in bids],
        asks=[OrderBookLevel(price=price, quantity=quantity) for price, quantity in asks],
        timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
        source="bybit_v5_orderbook",
        bid_depth_usd_0_5_pct=bid_depth,
        ask_depth_usd_0_5_pct=ask_depth,
    )


def _candle(open_time: int) -> OHLCVCandle:
    return OHLCVCandle(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1m",
        open_time=open_time,
        close_time=open_time + 59_999,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=100.0,
        trades=10,
        is_closed=True,
    )


class _AlphaRecordingStrategy:
    name = "volatility_squeeze_breakout"
    version = "test"
    required_data: list[str] = []

    def __init__(self) -> None:
        self.seen_alpha_context: AlphaMarketContext | None = None

    async def evaluate(
        self,
        features: Features,
        params: Mapping[str, Any] | None = None,
    ) -> list[StrategySignal]:
        self.seen_alpha_context = params.get("alpha_context") if params is not None else None
        return []


class _FakeAlphaMarketContextService(AlphaMarketContextService):
    def __init__(self) -> None:
        self.recent_trade_counts: list[int] = []

    def build_context(
        self,
        *,
        features: Features,
        recent_trades: Sequence[RecentTrade],
        **_kwargs: object,
    ) -> AlphaMarketContext:
        self.recent_trade_counts.append(len(recent_trades))
        return AlphaMarketContext(
            symbol=features.symbol,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            data_quality={"source": "test"},
        )


class _RecordingStrategyEngine:
    strategy_count = 1
    strategy_names = ["volatility_squeeze_breakout"]

    def __init__(self) -> None:
        self.alpha_contexts: list[AlphaMarketContext | None] = []

    async def generate_signals(self, features: Features, **kwargs: object) -> list[StrategySignal]:
        alpha_context = kwargs.get("alpha_context")
        self.alpha_contexts.append(alpha_context if isinstance(alpha_context, AlphaMarketContext) else None)
        return []


if __name__ == "__main__":
    unittest.main()
