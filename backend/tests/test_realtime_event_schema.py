import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.schemas.notification import NotificationResponse
from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    TradeInvalidationAlert,
    VirtualTrade,
    VirtualTradeLifecycleEvent,
    VirtualTradeTargetState,
)
from app.services.realtime_events import (
    notification_created_event,
    pending_entry_updated_event,
    price_touched_entry_event,
    signal_created_event,
    signal_expired_event,
    signal_invalidated_event,
    signal_updated_event,
    stop_loss_hit_event,
    take_profit_hit_event,
    trade_activated_event,
    trade_closed_event,
    trade_invalidation_event,
    trade_updated_event,
)


class RealtimeEventSchemaTest(unittest.TestCase):
    def test_signal_created_event_has_replayable_envelope(self) -> None:
        signal = _signal()

        event = signal_created_event(signal)

        json.dumps(event, ensure_ascii=False)
        self.assertTrue(event["id"].startswith("evt_"))
        self.assertEqual(event["type"], "signal.created")
        self.assertEqual(event["version"], 1)
        self.assertTrue(event["timestamp"].endswith("Z"))
        self.assertIsInstance(event["payload"]["signal"], dict)
        self.assertEqual(event["payload"]["signal"]["id"], "sig_123")
        self.assertIsNotNone(event["payload"]["signal"]["card_view"])
        self.assertIsNotNone(event["payload"]["signal"]["details_view"])
        self.assertEqual(event["payload"]["signalId"], "sig_123")
        self.assertEqual(event["payload"]["pair"], "BTCUSDT")
        self.assertEqual(event["payload"]["side"], "LONG")
        self.assertEqual(event["payload"]["confidence"], 84)
        self.assertEqual(event["payload"]["entryZone"]["from"], 67850)
        self.assertEqual(event["payload"]["takeProfit"], [68900, 69450])

    def test_signal_lifecycle_events_are_json_safe(self) -> None:
        signal = _signal()

        for event in [
            signal_updated_event(signal),
            signal_invalidated_event(signal, "risk_gate_failed"),
            signal_expired_event(signal),
            price_touched_entry_event(signal, 67900),
        ]:
            json.dumps(event, ensure_ascii=False)
            self.assertIsInstance(event["payload"]["signal"], dict)
            self.assertEqual(event["payload"]["signal"]["id"], "sig_123")
            self.assertIsNotNone(event["payload"]["signal"]["card_view"])
            self.assertIsNotNone(event["payload"]["signal"]["details_view"])

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

        json.dumps(event, ensure_ascii=False)
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

        json.dumps(event, ensure_ascii=False)
        self.assertEqual(event["type"], "pending_entry.updated")
        self.assertEqual(event["payload"]["user_id"], str(intent.user_id))
        self.assertEqual(event["payload"]["signal_id"], str(intent.signal_id))
        self.assertEqual(event["payload"]["pending_entry_id"], str(intent.id))
        self.assertEqual(event["payload"]["pending_entry"]["id"], str(intent.id))
        self.assertEqual(event["payload"]["pending_entry"]["status"], "filling")
        self.assertEqual(event["payload"]["pending_entry"]["failure_reason"], "Order is being filled.")
        self.assertEqual(event["payload"]["status"], "filling")
        self.assertEqual(event["payload"]["mode"], "virtual")
        self.assertEqual(event["payload"]["reason"], "Order is being filled.")
        self.assertEqual(event["payload"]["message"], "Order is being filled.")
        self.assertEqual(event["payload"]["updated_at"], now.isoformat())

    def test_trade_events_are_json_safe_and_keep_trade_payload_as_dict(self) -> None:
        trade = _trade()

        for event in [
            trade_activated_event(trade),
            trade_updated_event(trade),
            trade_closed_event(trade),
            take_profit_hit_event(trade),
            stop_loss_hit_event(trade),
        ]:
            json.dumps(event, ensure_ascii=False)
            self.assertIsInstance(event["payload"]["trade"], dict)
            self.assertEqual(event["payload"]["trade"]["id"], "trade_123")

    def test_trade_invalidation_event_is_json_safe(self) -> None:
        alert = TradeInvalidationAlert(
            trade_id="trade_123",
            signal_id="sig_123",
            exchange="bybit",
            symbol="BTCUSDT",
            strategy="EMA_PULLBACK",
            timeframe="15m",
            side="long",
            invalidated=True,
            reason="trend_invalidated",
            triggered_conditions=["close_below_support"],
            current_price=67400,
            stop_loss=67420,
            detected_at=datetime.now(timezone.utc),
            fingerprint="fp_123",
        )

        event = trade_invalidation_event(alert)

        json.dumps(event, ensure_ascii=False)
        self.assertEqual(event["type"], "trade.invalidation")
        self.assertIsInstance(event["payload"]["alert"], dict)
        self.assertEqual(event["payload"]["alert"]["trade_id"], "trade_123")


def _signal() -> RadarSignal:
    return RadarSignal(
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


def _trade() -> VirtualTrade:
    now = datetime.now(timezone.utc)
    return VirtualTrade(
        id="trade_123",
        user_id="usr_demo",
        signal_id="sig_123",
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="EMA_PULLBACK",
        timeframe="15m",
        side="long",
        entry_price=67850,
        current_price=68900,
        exit_price=68900,
        size_usd=1000,
        quantity=0.0147,
        initial_quantity=0.0147,
        remaining_quantity=0,
        closed_quantity=0.0147,
        initial_size_usd=1000,
        remaining_size_usd=0,
        leverage=1,
        risk_percent=1,
        risk_amount=100,
        risk_reward=2.5,
        stop_loss=67420,
        current_stop_loss=67850,
        take_profit=[68900, 69450],
        realized_pnl=25,
        unrealized_pnl=0,
        status="closed",
        result="win",
        close_reason="take_profit",
        pnl=25,
        pnl_percent=2.5,
        opened_at=now,
        updated_at=now,
        closed_at=now,
        target_states=[
            VirtualTradeTargetState(
                label="TP1",
                price=68900,
                close_percent=100,
                hit=True,
                hit_at=now,
                closed_quantity=0.0147,
                closed_size_usd=1000,
                realized_pnl=25,
            )
        ],
        lifecycle_events=[
            VirtualTradeLifecycleEvent(
                signal_id="sig_123",
                virtual_trade_id="trade_123",
                event_type="take_profit",
                target_label="TP1",
                price=68900,
                quantity=0.0147,
                size_usd=1000,
                realized_pnl=25,
                created_at=now,
                metadata={"trigger_price": Decimal("68900")},
            )
        ],
    )


if __name__ == "__main__":
    unittest.main()
