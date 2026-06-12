from __future__ import annotations

import unittest

from app.schemas.market import AlphaMarketContext, Features
from app.services.market_context import MarketContextService
from app.services.market_regime import MarketQualityInput, MarketWideRegimeContext


class MarketContextServiceTest(unittest.TestCase):
    def test_alt_long_is_blocked_when_btc_and_eth_are_risk_off(self) -> None:
        features = _features(symbol="ADAUSDT")
        context = MarketContextService().build_snapshot(
            features=features,
            direction="long",
            alpha_context=AlphaMarketContext(
                symbol="ADAUSDT",
                timeframe="15m",
                timestamp=features.timestamp,
                funding_rate=0.0001,
                funding_pressure=0.1,
                bid_depth_usd=250_000.0,
                ask_depth_usd=240_000.0,
            ),
            market_quality=MarketQualityInput(volume_24h_quote=50_000_000.0, spread_bps=8.0),
            market_wide_context=MarketWideRegimeContext(
                exchange="bybit",
                timeframe="15m",
                majors={
                    "BTCUSDT": _features(symbol="BTCUSDT", direction="down"),
                    "ETHUSDT": _features(symbol="ETHUSDT", direction="down"),
                },
            ),
        )

        self.assertTrue(context.risk_off)
        self.assertIn("btc_risk_off", context.reason_codes)
        self.assertIn("eth_risk_off", context.reason_codes)
        self.assertTrue(any(blocker.code == "btc_risk_off" for blocker in context.blockers))

    def test_derivative_and_liquidity_context_emit_specific_blockers(self) -> None:
        features = _features(symbol="SOLUSDT")
        context = MarketContextService().build_snapshot(
            features=features,
            direction="long",
            alpha_context=AlphaMarketContext(
                symbol="SOLUSDT",
                timeframe="15m",
                timestamp=features.timestamp,
                funding_rate=0.0025,
                funding_pressure=2.0,
                oi_delta_5m=0.18,
                bid_depth_usd=15_000.0,
                ask_depth_usd=12_000.0,
            ),
            market_quality=MarketQualityInput(volume_24h_quote=5_000_000.0, spread_bps=95.0),
            settings={
                "market_context_max_spread_bps": 50,
                "market_context_min_depth_usd": 50_000,
            },
        )

        self.assertIn("funding_extreme", context.reason_codes)
        self.assertIn("oi_unstable", context.reason_codes)
        self.assertIn("spread_too_wide", context.reason_codes)
        self.assertIn("depth_insufficient", context.reason_codes)


def _features(
    *,
    symbol: str,
    direction: str = "up",
) -> Features:
    if direction == "down":
        close = 95.0
        ema_20 = 97.0
        ema_50 = 99.0
        ema_200 = 101.0
        adx_slope = -2.0
    else:
        close = 105.0
        ema_20 = 103.0
        ema_50 = 101.0
        ema_200 = 99.0
        adx_slope = 2.0
    return Features(
        exchange="bybit",
        symbol=symbol,
        timeframe="15m",
        timestamp=1_779_796_800_000,
        price=close,
        open=100.0,
        high=max(106.0, close),
        low=min(94.0, close),
        close=close,
        price_change_1m=0.0,
        volume=100.0,
        volume_spike=1.2,
        volume_ma_20=100.0,
        volatility=1.0,
        history_length=240,
        ema_20=ema_20,
        ema_50=ema_50,
        ema_200=ema_200,
        adx=32.0,
        adx_rising=True,
        adx_slope_5=adx_slope,
        atr_14=1.0,
        atr_sma_50=0.9,
    )


if __name__ == "__main__":
    unittest.main()
