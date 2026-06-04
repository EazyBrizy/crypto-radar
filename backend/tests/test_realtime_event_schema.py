import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.schemas.notification import NotificationResponse
from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.signal import RadarSignal
from app.services.realtime_events import (
    notification_created_event,
    pending_entry_updated_event,
    signal_created_event,
)


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

    def test_pending_entry_updated_event_has_lifecycle_payload(self) -> None:
        now = datetime.now(timezone.utc)
        intent = PendingEntryIntentRead(
            id=uuid4(),
            user_id=uuid4(),
            signal_id=uuid4(),
            mode="virtual",
            status="filling",
            exchange="bybit",
            symbol="BTCUSDT",
            side="long",
            entry_min=Decimal("100"),
            entry_max=Decimal("101"),
            entry_price_policy="accepted_entry_zone",
            stop_loss=Decimal("95"),
            targets_snapshot=[{"label": "TP1", "price": "110"}],
            accepted_trade_plan_snapshot={"entry": {"min_price": "100", "max_price": "101"}},
            accepted_trade_plan_hash="sha256:test",
            accepted_signal_status="ready",
            execution_profile_snapshot={"risk_mode": "percent"},
            request_snapshot={"auto_enter_on_confirmation": True},
            idempotency_key="pending-entry:test",
            created_at=now,
            updated_at=now,
            failure_reason="Order is being filled.",
        )

        event = pending_entry_updated_event(intent)

        self.assertEqual(event["type"], "pending_entry.updated")
        self.assertEqual(event["payload"]["user_id"], str(intent.user_id))
        self.assertEqual(event["payload"]["signal_id"], str(intent.signal_id))
        self.assertEqual(event["payload"]["pending_entry_id"], str(intent.id))
        self.assertEqual(event["payload"]["status"], "filling")
        self.assertEqual(event["payload"]["mode"], "virtual")
        self.assertEqual(event["payload"]["reason"], "Order is being filled.")
        self.assertEqual(event["payload"]["message"], "Order is being filled.")
        self.assertEqual(event["payload"]["updated_at"], now.isoformat())


if __name__ == "__main__":
    unittest.main()
