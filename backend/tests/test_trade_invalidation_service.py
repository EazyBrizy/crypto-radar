import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features
from app.schemas.signal import RadarSignal, SignalInvalidationSnapshot
from app.schemas.trade import TradeInvalidationAlert, TradeJournalEntry, VirtualTrade
from app.services.feature_engine import FeatureEngine
from app.services.trade_invalidation import TradeInvalidationActionRecord, TradeInvalidationMonitor, TradeInvalidationService


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


class MemoryActions:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], TradeInvalidationActionRecord] = {}

    def latest_for_alert(self, alert):
        return self.records.get((alert.trade_id, alert.fingerprint))

    def record(self, alert, action, *, user_id: str = "demo_user"):
        record = TradeInvalidationActionRecord(action=action, created_at=datetime.now(timezone.utc))
        self.records[(alert.trade_id, alert.fingerprint)] = record
        return record


class StaticOpenTrades:
    def __init__(self, trades: list[TradeJournalEntry]) -> None:
        self._trades = trades

    def list_trade_journal(self, **_kwargs) -> list[TradeJournalEntry]:
        return self._trades


class StaticInvalidations:
    def __init__(self, alert: TradeInvalidationAlert) -> None:
        self.alert = alert

    def evaluate_trade_with_features(self, _trade, _features):
        return self.alert


class CapturingBroker:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def publish(self, event: dict[str, object]) -> None:
        self.events.append(event)


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
            actions=MemoryActions(),
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
            actions=MemoryActions(),
        )

        alert = service.evaluate_trade(trade)

        self.assertFalse(alert.invalidated)
        self.assertEqual(alert.status, "unavailable")
        self.assertIn("unavailable", alert.reason or "")

    def test_keep_stop_loss_action_is_persisted_on_matching_alert(self) -> None:
        actions = MemoryActions()
        trade = _trade(strategy="trend_pullback_continuation", side="long")
        signal = _signal(
            strategy=trade.strategy,
            direction="long",
            invalidation=SignalInvalidationSnapshot(
                price=94.0,
                hard_stop=90.0,
                conditions=["Close below EMA50"],
                metadata={"ema_50": 99.0},
            ),
        )
        service = TradeInvalidationService(
            signals=StaticSignals(signal),
            candles=StaticCandles(_flat_then_drop_candles()),
            feature_engine=FeatureEngine(),
            actions=actions,
        )

        alert = service.evaluate_trade(trade)
        stored = service.record_user_action(trade, "keep_stop_loss", alert=alert)
        reloaded = service.evaluate_trade(trade)

        self.assertEqual(stored.user_action, "keep_stop_loss")
        self.assertTrue(stored.action_dismissed)
        self.assertEqual(reloaded.user_action, "keep_stop_loss")
        self.assertTrue(reloaded.action_dismissed)


class TradeInvalidationMonitorTest(unittest.IsolatedAsyncioTestCase):
    async def test_closed_candle_monitor_publishes_trade_invalidation_once(self) -> None:
        trade = TradeJournalEntry.model_validate(_trade("trend_pullback_continuation", "long").model_dump())
        alert = _alert_for_trade(trade)
        broker = CapturingBroker()
        monitor = TradeInvalidationMonitor(
            trades=StaticOpenTrades([trade]),
            invalidations=StaticInvalidations(alert),
        )

        with patch("app.services.trade_invalidation.realtime_event_broker", broker):
            first = await monitor.process_closed_candle(_features())
            second = await monitor.process_closed_candle(_features())

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)
        self.assertEqual(len(broker.events), 1)
        self.assertEqual(broker.events[0]["type"], "trade.invalidation")


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


def _features() -> Features:
    return Features(
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="15m",
        timestamp=1,
        price=95.0,
        open=100.0,
        high=100.0,
        low=94.0,
        close=95.0,
        price_change_1m=-0.05,
        volume=100.0,
        volume_spike=1.0,
        volume_ma_20=100.0,
        volatility=1.0,
        history_length=60,
    )


def _alert_for_trade(trade: TradeJournalEntry) -> TradeInvalidationAlert:
    now = datetime.now(timezone.utc)
    return TradeInvalidationAlert(
        trade_id=trade.id,
        signal_id=trade.signal_id,
        exchange=trade.exchange,
        symbol=trade.symbol,
        strategy=trade.strategy,
        timeframe=trade.timeframe,
        side=trade.side,
        status="invalidated",
        invalidated=True,
        reason="Close below EMA50",
        triggered_conditions=["Close below EMA50"],
        watched_conditions=["Close below EMA50"],
        suggested_action="close_market_or_wait_stop",
        current_price=95.0,
        stop_loss=trade.stop_loss,
        invalidation_price=96.0,
        detected_at=now,
        fingerprint="fp_test",
    )


if __name__ == "__main__":
    unittest.main()
