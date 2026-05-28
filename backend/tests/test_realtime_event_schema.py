import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.notification import NotificationResponse
from app.schemas.signal import RadarSignal
from app.services.realtime_events import notification_created_event, signal_created_event


class RealtimeEventSchemaTest(unittest.TestCase):
    def test_signal_created_event_has_replayable_envelope(self) -> None:
        signal = RadarSignal(
            id="sig_123",
            symbol="BTCUSDT",
            exchange="binance",
            strategy="EMA_PULLBACK",
            direction="long",
            confidence=0.84,
            score=84,
            urgency="medium",
            entry_min=67850,
            entry_max=68100,
            stop_loss=67420,
            take_profit_1=68900,
            take_profit_2=69450,
            timeframe="15m",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        event = signal_created_event(signal)

        self.assertTrue(event["id"].startswith("evt_"))
        self.assertEqual(event["type"], "signal.created")
        self.assertEqual(event["version"], 1)
        self.assertTrue(event["timestamp"].endswith("Z"))
        self.assertEqual(event["payload"]["signalId"], "sig_123")
        self.assertEqual(event["payload"]["pair"], "BTCUSDT")
        self.assertEqual(event["payload"]["side"], "LONG")
        self.assertEqual(event["payload"]["confidence"], 84)
        self.assertEqual(event["payload"]["entryZone"]["from"], 67850)
        self.assertEqual(event["payload"]["takeProfit"], [68900, 69450])

    def test_notification_created_event_has_persisted_payload(self) -> None:
        notification = NotificationResponse(
            id=uuid4(),
            user_id=uuid4(),
            type="alert.rule_test",
            title="Alert test",
            body="BTCUSDT price_above",
            payload={"alert_rule_id": "rule_1"},
            is_read=False,
            created_at=datetime.now(timezone.utc),
            deliveries=[],
        )

        event = notification_created_event(notification)

        self.assertEqual(event["type"], "notification.created")
        self.assertEqual(event["payload"]["notificationId"], str(notification.id))
        self.assertEqual(event["payload"]["kind"], "alert")
        self.assertEqual(event["payload"]["title"], "Alert test")
        self.assertEqual(event["payload"]["notification"]["type"], "alert.rule_test")


if __name__ == "__main__":
    unittest.main()
