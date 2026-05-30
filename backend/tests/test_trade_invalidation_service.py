import unittest
from datetime import datetime, timezone

from app.schemas.candle import OHLCVCandle
from app.schemas.signal import RadarSignal, SignalInvalidationSnapshot
from app.schemas.trade import VirtualTrade
from app.services.feature_engine import FeatureEngine
from app.services.trade_invalidation import TradeInvalidationService


class StaticSignals:
    def __init__(self, signal: RadarSignal | None) -> None:
        self._signal = signal

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        if self._signal is not None and self._signal.id == signal_id:
            return self._signal
        return None


class StaticCandles:
    def __init__(self, candles: list[OHLCVCandle]) -> None:
        self._candles = candles

    def list_candles(self, **_kwargs) -> list[OHLCVCandle]:
        return self._candles


class TradeInvalidationServiceTest(unittest.TestCase):
    def test_trend_pullback_long_returns_market_close_prompt_when_logic_breaks(self) -> None:
        trade = _trade(strategy="trend_pullback_continuation", side="long")
        signal = _signal(
            strategy=trade.strategy,
            direction="long",
            invalidation=SignalInvalidationSnapshot(
                price=94.0,
                hard_stop=90.0,
                conditions=[
                    "Close below EMA50",
                    "Break below last swing low",
                    "RSI loses the 45 zone",
                ],
                metadata={
                    "ema_50": 99.0,
                    "swing_low": 96.0,
                    "trend_invalidation_level": 96.0,
                    "rsi_long_min": 45.0,
                },
            ),
        )
        service = TradeInvalidationService(
            signals=StaticSignals(signal),
            candles=StaticCandles(_flat_then_drop_candles()),
            feature_engine=FeatureEngine(),
        )

        alert = service.evaluate_trade(trade)

        self.assertTrue(alert.invalidated)
        self.assertEqual(alert.status, "invalidated")
        self.assertEqual(alert.suggested_action, "close_market_or_wait_stop")
        self.assertIn("Close below EMA50", alert.triggered_conditions)
        self.assertIn("Break below last swing low", alert.triggered_conditions)
        self.assertIn("RSI loses the 45 zone", alert.triggered_conditions)

    def test_returns_unavailable_when_signal_has_no_invalidation_plan(self) -> None:
        trade = _trade(strategy="external", side="long")
        signal = _signal(strategy=trade.strategy, direction="long", invalidation=None)
        service = TradeInvalidationService(
            signals=StaticSignals(signal),
            candles=StaticCandles(_flat_then_drop_candles()),
            feature_engine=FeatureEngine(),
        )

        alert = service.evaluate_trade(trade)

        self.assertFalse(alert.invalidated)
        self.assertEqual(alert.status, "unavailable")
        self.assertIn("unavailable", alert.reason or "")


def _trade(strategy: str, side: str) -> VirtualTrade:
    now = datetime.now(timezone.utc)
    return VirtualTrade(
        id="vtr_test",
        user_id="demo_user",
        signal_id="sig_test",
        exchange="bybit",
        symbol="BTCUSDT",
        strategy=strategy,
        timeframe="15m",
        side=side,
        entry_price=100.0,
        current_price=100.0,
        size_usd=100.0,
        quantity=1.0,
        leverage=1,
        risk_percent=1.0,
        stop_loss=90.0,
        opened_at=now,
        updated_at=now,
    )


def _signal(
    *,
    strategy: str,
    direction: str,
    invalidation: SignalInvalidationSnapshot | None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="sig_test",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy=strategy,
        direction=direction,
        confidence=0.8,
        score=80,
        timeframe="15m",
        entry_min=99.5,
        entry_max=100.5,
        stop_loss=90.0,
        take_profit_1=110.0,
        take_profit_2=120.0,
        explanation=[],
        risks=[],
        invalidation=invalidation,
        created_at=now,
        updated_at=now,
    )


def _flat_then_drop_candles() -> list[OHLCVCandle]:
    candles: list[OHLCVCandle] = []
    timeframe_ms = 15 * 60_000
    for index in range(60):
        close = 100.0
        open_price = 100.0
        high = 100.2
        low = 99.8
        if index == 59:
            open_price = 100.0
            close = 95.0
            high = 100.1
            low = 94.8
        candles.append(
            OHLCVCandle(
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="15m",
                open_time=index * timeframe_ms,
                close_time=(index + 1) * timeframe_ms - 1,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=100.0,
                trades=20,
                is_closed=True,
            )
        )
    return candles


if __name__ == "__main__":
    unittest.main()
