import unittest

from app.schemas.market import AlphaMarketContext, Features
from app.services.market_regime import (
    MarketQualityInput,
    MarketRegimeContextStore,
    MarketRegimeService,
    MarketWideRegimeContext,
)


class MarketRegimeServiceTest(unittest.TestCase):
    def test_trend_up_detected_from_ema_stack_and_adx(self) -> None:
        snapshot = MarketRegimeService().classify(features=_features())

        self.assertEqual(snapshot.primary_label, "trend_up")
        self.assertEqual(snapshot.base_label, "trend_up")
        self.assertIn("trend_up", snapshot.labels)
        self.assertEqual(snapshot.direction, "bullish")
        self.assertGreaterEqual(snapshot.confidence, 0.6)
        self.assertEqual(len(snapshot.candidates), 11)
        self.assertEqual(snapshot.regime_key, "trend_up:strong:unknown")

    def test_trend_down_detected_from_ema_stack_and_adx(self) -> None:
        snapshot = MarketRegimeService().classify(features=_features(direction="down"))

        self.assertEqual(snapshot.primary_label, "trend_down")
        self.assertEqual(snapshot.base_label, "trend_down")
        self.assertIn("trend_down", snapshot.labels)
        self.assertEqual(snapshot.direction, "bearish")

    def test_range_detected_when_adx_low_and_price_inside_donchian(self) -> None:
        snapshot = MarketRegimeService().classify(
            features=_features(
                close=100.0,
                ema_20=100.2,
                ema_50=100.1,
                ema_200=99.8,
                adx=13.0,
                adx_rising=False,
                bb_width_percentile=42.0,
                donchian_high_20=104.0,
                donchian_low_20=96.0,
                range_20_atr=3.0,
            )
        )

        self.assertEqual(snapshot.primary_label, "range")
        self.assertEqual(snapshot.base_label, "range")
        self.assertEqual(snapshot.direction, "range")

    def test_chop_detected_from_ema200_chop_score(self) -> None:
        snapshot = MarketRegimeService().classify(
            features=_features(
                close=100.1,
                ema_20=99.9,
                ema_50=100.2,
                ema_200=100.0,
                adx=14.0,
                adx_rising=False,
                ema_200_chop_score=74.0,
                ema_200_cross_count_50=4,
                ema_200_near_ratio_50=0.72,
            )
        )

        self.assertEqual(snapshot.primary_label, "chop")
        self.assertEqual(snapshot.base_label, "chop")
        self.assertIn("chop", snapshot.labels)
        self.assertTrue(any(check.name == "ema200_chop" and check.status == "failed" for check in snapshot.checks))

    def test_volatility_compression_detected_from_bb_width_and_atr_ratio(self) -> None:
        snapshot = MarketRegimeService().classify(
            features=_features(
                close=100.0,
                adx=16.0,
                bb_width_percentile=8.0,
                atr_14=0.55,
                atr_sma_50=1.0,
                range_20=3.0,
                range_50_average=6.0,
                volume_spike=0.9,
                donchian_high_20=104.0,
                donchian_low_20=96.0,
            )
        )

        self.assertEqual(snapshot.primary_label, "volatility_compression")
        self.assertEqual(snapshot.volatility_label, "volatility_compression")
        self.assertIn("volatility_compression", snapshot.labels)

    def test_volatility_expansion_detected_from_atr_volume_breakout(self) -> None:
        snapshot = MarketRegimeService().classify(
            features=_features(
                open=100.0,
                high=106.0,
                low=99.0,
                close=105.5,
                atr_14=1.0,
                atr_sma_50=0.55,
                atr_increasing=True,
                volume_spike=2.8,
                donchian_high_20=104.0,
                donchian_low_20=96.0,
            )
        )

        self.assertEqual(snapshot.primary_label, "volatility_expansion")
        self.assertEqual(snapshot.volatility_label, "volatility_expansion")
        self.assertIn("volatility_expansion", snapshot.labels)

    def test_post_impulse_detected_after_large_previous_candle(self) -> None:
        snapshot = MarketRegimeService().classify(
            features=_features(
                open=104.8,
                high=105.1,
                low=103.9,
                close=104.3,
                previous_open=100.0,
                previous_high=105.0,
                previous_low=99.7,
                previous_close=104.7,
                previous_volume=300.0,
                atr_14=1.0,
                volume_spike=1.2,
            )
        )

        self.assertEqual(snapshot.primary_label, "post_impulse")
        self.assertEqual(snapshot.volatility_label, "post_impulse")
        self.assertEqual(snapshot.metadata.get("impulse_direction"), "up")

    def test_news_pump_detected_from_extreme_volume_body_oi(self) -> None:
        snapshot = MarketRegimeService().classify(
            features=_features(
                open=100.0,
                high=108.5,
                low=99.6,
                close=108.0,
                atr_14=1.0,
                volume_spike=6.5,
                oi_change=0.22,
            ),
            alpha_context=AlphaMarketContext(
                symbol="BTCUSDT",
                timeframe="15m",
                timestamp=1_779_796_800_000,
                aggressive_delta=0.78,
                cvd_change=450_000.0,
                oi_delta_5m=0.18,
                funding_pressure=0.08,
            ),
            market_quality=MarketQualityInput(spread_bps=42.0, volume_24h_quote=200_000_000.0),
        )

        self.assertEqual(snapshot.primary_label, "news_pump")
        self.assertIn("news_pump", snapshot.event_labels)
        self.assertLessEqual(snapshot.score_adjustment, -25)

    def test_liquidity_vacuum_detected_from_spread_depth_imbalance(self) -> None:
        snapshot = MarketRegimeService().classify(
            features=_features(volume_spike=0.8),
            alpha_context=AlphaMarketContext(
                symbol="MEMEUSDT",
                timeframe="15m",
                timestamp=1_779_796_800_000,
                orderbook_imbalance=0.92,
                bid_depth_usd=12_000.0,
                ask_depth_usd=9_000.0,
                sweep_through_book=True,
            ),
            market_quality=MarketQualityInput(spread_bps=88.0, volume_24h_quote=450_000.0),
        )

        self.assertEqual(snapshot.primary_label, "liquidity_vacuum")
        self.assertIn("liquidity_vacuum", snapshot.event_labels)
        self.assertTrue(any(check.name == "liquidity_vacuum" and check.status == "failed" for check in snapshot.checks))

    def test_market_wide_risk_off_detected_from_major_context(self) -> None:
        market_wide_context = MarketWideRegimeContext(
            exchange="bybit",
            timeframe="15m",
            majors={
                "BTCUSDT": _features(symbol="BTCUSDT", direction="down"),
                "ETHUSDT": _features(symbol="ETHUSDT", direction="down"),
                "SOLUSDT": _features(symbol="SOLUSDT", direction="down"),
            },
        )

        snapshot = MarketRegimeService().classify(
            features=_features(symbol="ADAUSDT"),
            market_wide_context=market_wide_context,
        )

        self.assertEqual(snapshot.primary_label, "market_wide_risk_off")
        self.assertIn("market_wide_risk_off", snapshot.event_labels)

    def test_insufficient_history_returns_unknown_or_low_confidence(self) -> None:
        snapshot = MarketRegimeService().classify(features=_features(history_length=12, ema_20=None, ema_50=None, ema_200=None))

        self.assertEqual(snapshot.primary_label, "unknown")
        self.assertLessEqual(snapshot.confidence, 0.25)
        self.assertTrue(any(check.name == "market_regime_history" and check.status == "warning" for check in snapshot.checks))

    def test_unavailable_alpha_context_does_not_crash(self) -> None:
        snapshot = MarketRegimeService().classify(features=_features(), alpha_context=None)

        self.assertIsNotNone(snapshot)
        self.assertTrue(any(candidate.label == "news_pump" for candidate in snapshot.candidates))

    def test_unavailable_market_quality_does_not_crash(self) -> None:
        snapshot = MarketRegimeService().classify(features=_features(), market_quality=None)

        self.assertIsNotNone(snapshot)
        self.assertTrue(any(candidate.label == "liquidity_vacuum" for candidate in snapshot.candidates))

    def test_context_store_builds_market_wide_context_for_default_majors(self) -> None:
        store = MarketRegimeContextStore()
        store.update_features(_features(symbol="BTCUSDT", direction="down"))
        store.update_features(_features(symbol="ETHUSDT", direction="down"))

        context = store.market_wide_context("bybit", "15m")

        self.assertEqual(context.exchange, "bybit")
        self.assertEqual(context.timeframe, "15m")
        self.assertEqual(sorted(context.majors), ["BTCUSDT", "ETHUSDT"])
        self.assertTrue(context.sufficient_data)


def _features(
    *,
    exchange: str = "bybit",
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    direction: str = "up",
    history_length: int = 240,
    price: float | None = None,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    ema_20: float | None = None,
    ema_50: float | None = None,
    ema_200: float | None = None,
    adx: float | None = 31.0,
    adx_rising: bool = True,
    adx_slope_5: float | None = 2.0,
    atr_14: float | None = 1.0,
    atr_sma_50: float | None = 0.9,
    atr_increasing: bool = False,
    bb_width_percentile: float | None = 44.0,
    donchian_high_20: float | None = None,
    donchian_low_20: float | None = None,
    range_20: float | None = 5.0,
    range_50_average: float | None = 5.4,
    range_20_atr: float | None = 2.5,
    volume_spike: float = 1.2,
    previous_open: float | None = None,
    previous_high: float | None = None,
    previous_low: float | None = None,
    previous_close: float | None = None,
    previous_volume: float | None = None,
    ema_200_chop_score: float | None = None,
    ema_200_cross_count_50: int = 0,
    ema_200_near_ratio_50: float | None = 0.1,
    oi_change: float | None = None,
) -> Features:
    if direction == "down":
        close = 94.0 if close is None else close
        open = 95.0 if open is None else open
        high = 95.4 if high is None else high
        low = 93.6 if low is None else low
        ema_20 = 96.0 if ema_20 is None else ema_20
        ema_50 = 98.0 if ema_50 is None else ema_50
        ema_200 = 102.0 if ema_200 is None else ema_200
        donchian_high_20 = 101.0 if donchian_high_20 is None else donchian_high_20
        donchian_low_20 = 94.5 if donchian_low_20 is None else donchian_low_20
    else:
        close = 106.0 if close is None else close
        open = 105.1 if open is None else open
        high = 106.4 if high is None else high
        low = 104.7 if low is None else low
        ema_20 = 104.0 if ema_20 is None else ema_20
        ema_50 = 101.5 if ema_50 is None else ema_50
        ema_200 = 97.0 if ema_200 is None else ema_200
        donchian_high_20 = 106.8 if donchian_high_20 is None else donchian_high_20
        donchian_low_20 = 98.5 if donchian_low_20 is None else donchian_low_20
    return Features(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        timestamp=1_779_796_800_000,
        price=price if price is not None else close,
        open=open,
        high=high,
        low=low,
        close=close,
        price_change_1m=(close - open) / open,
        previous_open=previous_open,
        previous_high=previous_high,
        previous_low=previous_low,
        previous_close=previous_close,
        previous_volume=previous_volume,
        volume=120.0 * max(volume_spike, 0.1),
        volume_spike=volume_spike,
        volume_ma_20=120.0,
        volatility=1.2,
        history_length=history_length,
        ema_20=ema_20,
        ema_50=ema_50,
        ema_200=ema_200,
        vwap=102.5 if direction == "up" else 98.5,
        atr_14=atr_14,
        atr_sma_50=atr_sma_50,
        adx=adx,
        adx_rising=adx_rising,
        adx_slope_5=adx_slope_5,
        ema_200_chop_score=ema_200_chop_score,
        ema_200_cross_count_50=ema_200_cross_count_50,
        ema_200_near_ratio_50=ema_200_near_ratio_50,
        ema_200_slope_atr_20=0.2,
        bb_width_percentile=bb_width_percentile,
        donchian_high_20=donchian_high_20,
        donchian_low_20=donchian_low_20,
        range_20=range_20,
        range_50_average=range_50_average,
        range_20_atr=range_20_atr,
        candle_bullish=close >= open,
        candle_bearish=close < open,
        upper_wick_ratio=0.12,
        lower_wick_ratio=0.1,
        atr_increasing=atr_increasing,
        oi_change=oi_change,
    )


if __name__ == "__main__":
    unittest.main()
