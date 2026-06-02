import unittest
from datetime import datetime, timezone

from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features, MarketData
from app.schemas.signal import StrategySignal
from app.services.derivative_market import DerivativeMarketSnapshot
from app.services.feature_engine import FeatureEngine
from app.services.candle_service import CandleService
from app.services.market_scanner import MarketScanner
from app.strategies.common import build_signal
from app.strategies.pipeline import StrategyEvaluationContext, StrategySignalPipeline


class FeatureEngineTest(unittest.TestCase):
    def test_intraday_candle_features_include_session_vwap(self) -> None:
        engine = FeatureEngine()
        day = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        previous_day = day - 24 * 60 * 60 * 1000
        candles = [
            _candle(previous_day, high=120, low=90, close=100, volume=100),
            _candle(day, high=102, low=98, close=100, volume=10),
            _candle(day + 60_000, high=112, low=108, close=110, volume=30),
        ]

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertAlmostEqual(features.vwap or 0.0, 107.5)
        self.assertAlmostEqual(features.session_high or 0.0, 112.0)
        self.assertAlmostEqual(features.session_low or 0.0, 98.0)
        self.assertAlmostEqual(features.previous_day_high or 0.0, 120.0)
        self.assertAlmostEqual(features.previous_day_low or 0.0, 90.0)

    def test_daily_candle_features_skip_intraday_vwap(self) -> None:
        engine = FeatureEngine()
        day = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        features = engine.process_candles([
            _candle(day, timeframe="1d", high=102, low=98, close=100, volume=10),
        ])

        self.assertIsNotNone(features)
        self.assertIsNone(features.vwap)

    def test_feature_engine_sets_open_candle_state(self) -> None:
        engine = FeatureEngine()
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candles = [
            _candle(start, high=102, low=98, close=100, volume=10),
            _candle(start + 60_000, high=103, low=99, close=102, volume=12).model_copy(
                update={"is_closed": False}
            ),
        ]

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertEqual(features.candle_state if features else None, "open")

    def test_feature_engine_sets_closed_candle_state(self) -> None:
        engine = FeatureEngine()
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)

        features = engine.process_candles([
            _candle(start, high=102, low=98, close=100, volume=10),
            _candle(start + 60_000, high=103, low=99, close=102, volume=12),
        ])

        self.assertIsNotNone(features)
        self.assertEqual(features.candle_state if features else None, "closed")

    def test_candle_features_use_wilder_adx_stats(self) -> None:
        engine = FeatureEngine()
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candles = []
        price = 100.0
        for index in range(80):
            if index < 40:
                price += 0.3 if index % 2 == 0 else -0.25
            else:
                price += 0.45 + index * 0.01
            candles.append(_candle(start + index * 60_000, high=price + 0.8, low=price - 0.6, close=price, volume=10))

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertIsNotNone(features.adx)
        self.assertGreaterEqual(features.adx_rising_bars, 0)
        self.assertIsNotNone(features.adx_slope_5)

    def test_candle_features_include_ema200_chop_metrics(self) -> None:
        engine = FeatureEngine()
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candles = [
            _candle(
                start + index * 60_000,
                high=101.5 if index % 6 < 3 else 100.5,
                low=99.5 if index % 6 < 3 else 98.5,
                close=101.0 if index % 6 < 3 else 99.0,
                volume=10,
            )
            for index in range(260)
        ]

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertGreaterEqual(features.ema_200_cross_count_50, 3)
        self.assertIsNotNone(features.ema_200_near_ratio_50)
        self.assertIsNotNone(features.ema_200_chop_score)

    def test_candle_features_include_squeeze_compression_metrics(self) -> None:
        engine = FeatureEngine()
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candles = []
        price = 100.0
        for index in range(90):
            width = 3.0 if index < 45 else 1.0
            price += 0.05
            candles.append(
                _candle(
                    start + index * 60_000,
                    high=price + width,
                    low=price - width,
                    close=price,
                    volume=10,
                )
            )

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertIsNotNone(features.atr_sma_50)
        self.assertIsNotNone(features.range_20)
        self.assertIsNotNone(features.range_50_average)
        self.assertIsNotNone(features.range_20_atr)
        self.assertLess(features.range_20 or 0, features.range_50_average or 0)

    def test_candle_features_use_fractal_swing_levels_with_touch_counts(self) -> None:
        engine = FeatureEngine()
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candles = []
        for index in range(60):
            high = 102.0
            low = 98.0
            close = 100.0
            volume = 100.0
            if index in {24, 38}:
                high = 110.0
                close = 104.0
                volume = 220.0
            if index in {28, 42}:
                low = 90.0
                close = 96.0
                volume = 210.0
            candles.append(
                _candle(
                    start + index * 60_000,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
            )

        features = engine.process_candles(candles)

        self.assertIsNotNone(features)
        self.assertAlmostEqual(features.swing_high or 0.0, 110.0)
        self.assertAlmostEqual(features.swing_low or 0.0, 90.0)
        self.assertGreaterEqual(features.swing_high_touch_count, 2)
        self.assertGreaterEqual(features.swing_low_touch_count, 2)
        self.assertIsNotNone(features.swing_high_volume_score)
        self.assertIsNotNone(features.swing_low_volume_score)


class FeatureDerivativeEnrichmentTest(unittest.IsolatedAsyncioTestCase):
    async def test_derivative_enrichment_sets_funding_and_oi_change(self) -> None:
        scanner = MarketScanner(
            symbols=["BTCUSDT"],
            exchanges=["bybit"],
            market_persistence=None,
            market_quality=None,
            virtual_trading=None,
            derivative_market=_FakeDerivativeMarket(),  # type: ignore[arg-type]
        )
        features = Features(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1m",
            timestamp=1_779_796_859_999,
            price=100,
            open=99,
            high=101,
            low=98,
            close=100,
            price_change_1m=0.01,
            volume=10,
            volume_spike=1.0,
            volume_ma_20=10,
            volatility=1,
            history_length=20,
        )

        enriched = await scanner._enrich_derivative_context(features)  # noqa: SLF001

        self.assertEqual(enriched.funding_rate, 0.0003)
        self.assertEqual(enriched.oi_change, -0.04)

    async def test_market_scanner_open_candle_signal_is_preview(self) -> None:
        candle_store = CandleService(timeframes=["1m"])
        start = int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp() * 1000)
        candle_store.seed_history(
            [
                _candle(
                    start + index * 60_000,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                    volume=100.0,
                )
                for index in range(70)
            ]
        )
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
        )
        scanner._strategy_engine = _PreviewStrategyEngine()  # noqa: SLF001

        signals = await scanner.process_tick(
            MarketData(
                exchange="bybit",
                symbol="BTCUSDT",
                timestamp=start + 70 * 60_000,
                price=100.5,
                volume=5.0,
            )
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].candle_state, "open")
        self.assertEqual(signals[0].status, "watchlist")
        self.assertIn("forming_candle", signals[0].status_reason or "")
        self.assertFalse(signals[0].auto_entry.enabled if signals[0].auto_entry else True)


class _FakeDerivativeMarket:
    def hot_snapshot(self, *, exchange: str, symbol: str) -> DerivativeMarketSnapshot:
        return DerivativeMarketSnapshot(
            exchange=exchange,
            symbol=symbol,
            funding_rate=0.0003,
            oi_change=-0.04,
            fetched_at=datetime.now(timezone.utc),
        )


class _PreviewStrategyEngine:
    strategy_count = 1
    strategy_names = ["volatility_squeeze_breakout"]

    async def generate_signals(self, features: Features, **_: object) -> list[StrategySignal]:
        candidate = build_signal(
            features=features,
            strategy="volatility_squeeze_breakout",
            direction="LONG",
            reasons=["synthetic scanner setup"],
            score=90,
            entry=features.close,
            stop_loss=features.close - 1.0,
            take_profit_1=features.close + 2.0,
            take_profit_2=features.close + 3.0,
        ).model_copy(update={"status": "actionable"})
        signal = StrategySignalPipeline().finalize(
            candidate,
            StrategyEvaluationContext(
                signal_features=features,
                pair_scope_configured=True,
                strategy_params={"min_rr_ratio": 1.5, "rr_target": "final"},
            ),
        )
        return [signal] if signal is not None else []


def _candle(
    open_time: int,
    *,
    timeframe: str = "1m",
    high: float,
    low: float,
    close: float,
    volume: float,
) -> OHLCVCandle:
    return OHLCVCandle(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + 59_999,
        open=(high + low) / 2,
        high=high,
        low=low,
        close=close,
        volume=volume,
        trades=10,
        is_closed=True,
    )


if __name__ == "__main__":
    unittest.main()
