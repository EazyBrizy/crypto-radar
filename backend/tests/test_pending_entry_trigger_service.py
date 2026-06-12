from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models.pending_entry import PendingEntryIntent
from app.models.user import AppUser
from app.repositories.pending_entry_repository import PendingEntryIntentRepository
from app.schemas.lifecycle import LifecycleTrace
from app.schemas.pending_entry import PendingEntryIntentCreate
from app.schemas.risk import ResolvedExecutionProfile
from app.schemas.signal import RadarSignal
from app.schemas.trade import ExecutionQualityGate, ManualConfirmRequest, VirtualExecutionReport, VirtualTrade
from app.schemas.user import RiskManagementSettings
from app.services.pending_entry import (
    TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
    PendingEntryService,
    accepted_trade_plan_hash,
)
from app.services.pending_entry_trigger import PendingEntryTriggerService, entry_zone_touch
from app.services.virtual_trading import VirtualExecutionRejected

USER_ID = UUID("7d7a4f33-a570-4334-b65f-3e5b4f0bb4a1")
SIGNAL_ID = UUID("eafefb92-8435-4d35-912f-6281ff0c1f19")
TRADE_ID = UUID("6a3aee25-8d76-4205-bab8-57e705de31b4")


class PendingEntryTriggerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._type_patches = _patch_sqlite_column_types()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.SessionFactory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        _create_sqlite_user_tables(self.engine)
        _create_sqlite_tables(self.engine)
        _seed_demo_user(self.SessionFactory)
        self.repository = PendingEntryIntentRepository(self.SessionFactory)
        self.signals = _FakeSignalProvider(_signal())
        self.virtual = _FakeVirtualTrading()
        self.events = _FakePendingEntryEventPublisher()
        self.service = PendingEntryTriggerService(
            pending_entries=self.repository,
            signals=self.signals,
            virtual_trading=self.virtual,
            session_factory=self.SessionFactory,
            event_publisher=self.events,
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        _restore_column_types(self._type_patches)

    def test_long_entry_touched_by_ask_fills_once(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5, "last": 99.0})

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "filled")
        self.assertEqual(results[0].price_source, "ask")
        self.assertEqual(results[0].virtual_trade_id, str(TRADE_ID))
        self.assertEqual(results[0].signal_id, str(SIGNAL_ID))
        self.assertEqual(results[0].lifecycle_trace.signal_id, str(SIGNAL_ID))
        self.assertEqual(results[0].lifecycle_trace.pending_entry_intent_id, str(created.id))
        self.assertEqual(results[0].lifecycle_trace.virtual_trade_id, str(TRADE_ID))
        self.assertEqual(len(self.virtual.calls), 1)
        self.assertEqual(self.virtual.calls[0][0].status, "entry_touched")
        self.assertEqual(self.virtual.calls[0][1].market_snapshot.best_ask, 100.5)
        self.assertEqual(
            self.virtual.calls[0][1].metadata["pending_entry_intent_id"],
            str(created.id),
        )
        self.assertEqual(
            self.virtual.calls[0][1].metadata["accepted_trade_plan_hash"],
            created.accepted_trade_plan_hash,
        )
        self.assertEqual(self.virtual.calls[0][1].metadata["trigger_source"], "pending_entry")
        self.assertEqual(
            self.virtual.calls[0][1].metadata["origin"]["pending_entry_intent_id"],
            str(created.id),
        )
        self.assertEqual(
            self.virtual.calls[0][1].metadata["pending_entry_trigger"]["trigger_reason"],
            "entry_zone_touched",
        )
        self.assertEqual(
            self.virtual.calls[0][1].metadata["lifecycle_trace"]["signal_id"],
            str(SIGNAL_ID),
        )
        self.assertEqual(self.virtual.trades[0].pending_entry_intent_id, str(created.id))
        self.assertEqual(self.virtual.trades[0].accepted_trade_plan_hash, created.accepted_trade_plan_hash)
        self.assertEqual(self.virtual.trades[0].trigger_source, "pending_entry")
        self.assertEqual(self.events.statuses(), ["triggered", "filling", "filled"])

    def test_confirmed_trigger_allows_open_entry_candle_touch_to_fill_virtual_pending(self) -> None:
        self.signals.signal = _signal(candle_state="open", confirmed_trigger=True)
        created = self.repository.create_intent(_intent_create(side="long"))

        results = self.service.process_market_tick(
            "bybit",
            "BTCUSDT",
            {"ask": 100.5, "last": 100.4, "candle_state": "open"},
        )

        self.assertEqual(results[0].status, "filled")
        self.assertEqual(results[0].price_source, "ask")
        self.assertEqual(self.virtual.calls[0][0].candle_state, "open")
        self.assertEqual(
            self.virtual.calls[0][0].trigger.metadata["confirmed_on_closed_candle"],
            True,
        )
        self.assertEqual(
            self.virtual.calls[0][1].metadata["pending_entry_trigger"]["entry_candle_state"],
            "open",
        )
        self.assertEqual(self.virtual.trades[0].pending_entry_intent_id, str(created.id))

    def test_short_entry_touched_by_bid_fills_once(self) -> None:
        self.signals.signal = _signal(direction="short")
        self.repository.create_intent(_intent_create(side="short"))

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"bid": 100.5, "last": 102.0})

        self.assertEqual(results[0].status, "filled")
        self.assertEqual(results[0].price_source, "bid")
        self.assertEqual(len(self.virtual.calls), 1)
        self.assertEqual(self.virtual.calls[0][1].market_snapshot.best_bid, 100.5)

    def test_last_fallback_adds_warning(self) -> None:
        self.repository.create_intent(_intent_create(side="long"))

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"last": 100.5})

        self.assertEqual(results[0].status, "filled")
        self.assertEqual(results[0].price_source, "last")
        self.assertIn("ask is unavailable", results[0].warnings[0])

    def test_not_touched_remains_pending(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 102.0, "last": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "pending")
        self.assertFalse(results[0].touched)
        self.assertEqual(results[0].reason_code, "entry_zone_not_touched")
        self.assertEqual(results[0].current_price, Decimal("102.0"))
        self.assertGreater(results[0].entry_zone_distance_bps or Decimal("0"), Decimal("0"))
        self.assertEqual(current.status if current else None, "pending")
        self.assertEqual(self.virtual.calls, [])
        self.assertEqual(self.events.statuses(), [])

    def test_expired_before_touch_records_reason_code_in_result_and_view(self) -> None:
        created = self.repository.create_intent(
            _intent_create(
                side="long",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        )

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 102.0})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "expired")
        self.assertEqual(results[0].reason_code, "pending_entry_expired_before_touch")
        self.assertEqual(results[0].current_price, Decimal("102.0"))
        self.assertEqual(current.reason_code if current else None, "pending_entry_expired_before_touch")
        self.assertEqual(current.view.reason_code if current and current.view else None, "pending_entry_expired_before_touch")

    def test_signal_invalidated_cancels_intent(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.signals.signal = _signal(status="invalidated")

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "cancelled")
        self.assertEqual(results[0].reason_code, "signal_terminal")
        self.assertEqual(current.status if current else None, "cancelled")
        self.assertEqual(current.reason_code if current else None, "signal_terminal")
        self.assertEqual(self.virtual.calls, [])

    def test_trade_plan_hash_changed_requires_reconfirmation(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.signals.signal = _signal(entry_min=99.0, entry_max=100.0)

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.0})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "requires_reconfirmation")
        self.assertEqual(results[0].reason, TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON)
        self.assertEqual(current.status if current else None, "requires_reconfirmation")
        self.assertEqual(current.failure_reason if current else None, TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON)
        self.assertEqual(
            current.accepted_trade_plan_snapshot if current else None,
            created.accepted_trade_plan_snapshot,
        )
        self.assertEqual(
            current.request_snapshot["pending_entry_lifecycle_events"][-1]["event"] if current else None,
            "pending_entry.requires_reconfirmation",
        )
        change = current.request_snapshot["pending_entry_lifecycle_events"][-1]["change_summary"]["changes"][0]
        self.assertIn("field", change)
        self.assertIn("previous", change)
        self.assertIn("current", change)
        self.assertIn("tolerance", change)
        self.assertIn("severity", change)
        self.assertIn("reason_code", change)
        self.assertFalse(hasattr(self.signals, "update_auto_entry"))
        self.assertEqual(self.virtual.calls, [])
        self.assertEqual(self.events.statuses(), ["requires_reconfirmation"])

    def test_event_publish_failure_does_not_rollback_trigger_transition(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.signals.signal = _signal(status="invalidated")
        service = PendingEntryTriggerService(
            pending_entries=self.repository,
            signals=self.signals,
            virtual_trading=self.virtual,
            session_factory=self.SessionFactory,
            event_publisher=_FailingPendingEntryEventPublisher(),
        )

        with self.assertLogs("app.services.pending_entry_trigger", level="WARNING") as logs:
            results = service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "cancelled")
        self.assertEqual(current.status if current else None, "cancelled")
        self.assertIn("Pending entry realtime event publish failed", "\n".join(logs.output))

    def test_changed_plan_reconfirm_then_second_touch_fills_virtual_trade(self) -> None:
        pending_service = PendingEntryService(
            repository=self.repository,
            session_factory=self.SessionFactory,
            signal_loader=lambda _signal_id: self.signals.signal,
            risk_settings_provider=lambda _user_id: RiskManagementSettings(),
        )
        created = pending_service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        old_hash = created.accepted_trade_plan_hash
        self.signals.signal = _signal(entry_min=99.0, entry_max=100.0, stop_loss=94.0, take_profit_1=111.0)

        blocked = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.0})
        blocked_current = self.repository.get_by_id(created.id)

        self.assertEqual(blocked[0].status, "requires_reconfirmation")
        self.assertEqual(blocked_current.status if blocked_current else None, "requires_reconfirmation")
        self.assertEqual(self.virtual.calls, [])

        reconfirmed = pending_service.reconfirm_intent(
            created.id,
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
        )
        self.assertEqual(reconfirmed.id, created.id)
        self.assertEqual(reconfirmed.status, "pending")
        self.assertEqual(reconfirmed.entry_min, Decimal("99"))
        self.assertEqual(reconfirmed.entry_max, Decimal("100"))
        self.assertNotEqual(reconfirmed.accepted_trade_plan_hash, old_hash)
        self.assertEqual(reconfirmed.accepted_trade_plan_hash, accepted_trade_plan_hash(self.signals.signal))
        self.assertEqual(
            reconfirmed.request_snapshot["pending_entry_lifecycle_events"][-1]["event"],
            "pending_entry.reconfirmed",
        )

        filled = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.0})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(filled[0].status, "filled")
        self.assertEqual(current.status if current else None, "filled")
        self.assertEqual(filled[0].virtual_trade_id, str(TRADE_ID))
        self.assertEqual(len(self.virtual.calls), 1)

    def test_stop_hash_changed_requires_reconfirmation(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.signals.signal = _signal(stop_loss=94.0)

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "requires_reconfirmation")
        self.assertEqual(current.status if current else None, "requires_reconfirmation")
        self.assertEqual(self.virtual.calls, [])

    def test_target_hash_changed_requires_reconfirmation(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.signals.signal = _signal(take_profit_1=111.0)

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "requires_reconfirmation")
        self.assertEqual(current.status if current else None, "requires_reconfirmation")
        self.assertEqual(self.virtual.calls, [])

    def test_score_only_update_keeps_pending_when_entry_not_touched(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.signals.signal = _signal(score=95)

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 102.0})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "pending")
        self.assertEqual(current.status if current else None, "pending")
        self.assertEqual(self.virtual.calls, [])

    def test_entry_touch_after_non_material_drift_uses_accepted_snapshot(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.signals.signal = _signal(
            entry_min=100.05,
            entry_max=101.05,
            stop_loss=95.05,
            take_profit_1=110.05,
            score=95,
        )

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "filled")
        self.assertEqual(current.status if current else None, "filled")
        self.assertEqual(len(self.virtual.calls), 1)
        execution_signal = self.virtual.calls[0][0]
        self.assertEqual(execution_signal.entry_min, 100.0)
        self.assertEqual(execution_signal.entry_max, 101.0)
        self.assertEqual(execution_signal.stop_loss, 95.0)
        self.assertEqual(execution_signal.take_profit_1, 110.0)
        self.assertEqual(execution_signal.score, 82)
        self.assertIsNotNone(execution_signal.trade_plan)
        self.assertEqual(execution_signal.trade_plan.stop_loss if execution_signal.trade_plan else None, 95.0)
        self.assertEqual(execution_signal.trade_plan.targets[0].price if execution_signal.trade_plan else None, 110.0)

    def test_requires_reconfirmation_intent_cannot_fill(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long", status="requires_reconfirmation"))

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results, [])
        self.assertEqual(current.status if current else None, "requires_reconfirmation")
        self.assertEqual(self.virtual.calls, [])

    def test_riskgate_failure_creates_no_trade_and_keeps_pending_for_stale_market_data(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.virtual.failure = ValueError("Bybit market data is stale.")

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "pending")
        self.assertEqual(results[0].reason_code, "temporary_execution_failure")
        self.assertEqual(current.status if current else None, "pending")
        self.assertEqual(current.reason_code if current else None, "temporary_execution_failure")
        self.assertIn("market data is stale", current.failure_reason if current else "")
        self.assertEqual(len(self.virtual.calls), 1)

    def test_riskgate_spread_failure_fails_pending_intent(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.virtual.failure = ValueError("Spread too wide for entry right now.")

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "failed")
        self.assertEqual(results[0].reason_code, "riskgate_rejected")
        self.assertEqual(current.status if current else None, "failed")
        self.assertEqual(current.reason_code if current else None, "riskgate_rejected")
        self.assertIn("Spread too wide", current.failure_reason if current else "")
        self.assertEqual(len(self.virtual.calls), 1)

    def test_virtual_execution_rejected_fails_with_reason_code(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.virtual.failure = _virtual_rejection("Liquidity too thin for requested size.")

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "failed")
        self.assertEqual(results[0].reason_code, "virtual_execution_rejected")
        self.assertEqual(current.status if current else None, "failed")
        self.assertEqual(current.reason_code if current else None, "virtual_execution_rejected")
        self.assertEqual(current.view.reason_code if current and current.view else None, "virtual_execution_rejected")

    def test_temporary_virtual_execution_rejection_keeps_pending_with_reason_code(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.virtual.failure = _virtual_rejection("Bybit market data is stale.", reason_code="market_data_stale")

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "pending")
        self.assertEqual(results[0].reason_code, "temporary_execution_failure")
        self.assertEqual(current.status if current else None, "pending")
        self.assertEqual(current.reason_code if current else None, "temporary_execution_failure")

    def test_double_tick_can_fill_only_once(self) -> None:
        self.repository.create_intent(_intent_create(side="long"))

        first = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        second = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})

        self.assertEqual(first[0].status, "filled")
        self.assertEqual(second, [])
        self.assertEqual(len(self.virtual.calls), 1)


class EntryTouchHelperTest(unittest.TestCase):
    def test_close_fallback_is_supported(self) -> None:
        result = entry_zone_touch(
            side="short",
            entry_min=Decimal("100"),
            entry_max=Decimal("101"),
            market_tick={"close": 100.25},
        )

        self.assertTrue(result.touched)
        self.assertEqual(result.price_source, "close")
        self.assertIn("bid and last are unavailable", result.warnings[0])


class _FakeSignalProvider:
    def __init__(self, signal: RadarSignal | None) -> None:
        self.signal = signal

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        if self.signal is None or self.signal.id != signal_id:
            return None
        return self.signal


class _FakeVirtualTrading:
    def __init__(self) -> None:
        self.calls: list[tuple[RadarSignal, ManualConfirmRequest]] = []
        self.trades: list[VirtualTrade] = []
        self.failure: Exception | None = None

    def confirm_signal(self, signal: RadarSignal, request: ManualConfirmRequest) -> tuple[RadarSignal, VirtualTrade]:
        self.calls.append((signal, request))
        if self.failure is not None:
            raise self.failure
        trade = _virtual_trade(signal, request)
        self.trades.append(trade)
        return signal.model_copy(update={"status": "confirmed", "confirmed_trade_id": trade.id}), trade


class _FakePendingEntryEventPublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, str | None]] = []

    def publish_update(self, intent: Any, *, message: str | None = None) -> None:
        reason = message if message is not None else intent.failure_reason
        self.events.append(
            {
                "pending_entry_id": str(intent.id),
                "signal_id": str(intent.signal_id),
                "user_id": str(intent.user_id),
                "status": intent.status,
                "mode": intent.mode,
                "reason": reason,
                "message": reason,
            }
        )

    def statuses(self) -> list[str | None]:
        return [event["status"] for event in self.events]


class _FailingPendingEntryEventPublisher:
    def publish_update(self, intent: Any, *, message: str | None = None) -> None:
        raise RuntimeError("broker unavailable")


def _signal(
    *,
    status: str = "active",
    direction: str = "long",
    candle_state: str = "closed",
    confirmed_trigger: bool = False,
    entry_min: float = 100.0,
    entry_max: float = 101.0,
    stop_loss: float | None = None,
    take_profit_1: float | None = None,
    take_profit_2: float | None = None,
    score: int = 82,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=str(SIGNAL_ID),
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction=direction,
        confidence=0.82,
        risk_reward=2.0,
        status=status,
        score=score,
        timeframe="15m",
        candle_state=candle_state,
        entry_min=entry_min,
        entry_max=entry_max,
        stop_loss=stop_loss if stop_loss is not None else (95.0 if direction == "long" else 105.0),
        take_profit_1=take_profit_1 if take_profit_1 is not None else (110.0 if direction == "long" else 90.0),
        take_profit_2=take_profit_2 if take_profit_2 is not None else (115.0 if direction == "long" else 85.0),
        created_at=now,
        updated_at=now,
        trigger=(
            {
                "trigger_type": "closed_candle",
                "passed": True,
                "candle_state": "closed",
                "confirmed_at": now,
                "metadata": {
                    "confirmed_on_closed_candle": True,
                    "trigger_candle_state": "closed",
                    "trigger_confirmed_at": now.isoformat(),
                },
            }
            if confirmed_trigger
            else None
        ),
    )


def _intent_create(**overrides: Any) -> PendingEntryIntentCreate:
    signal = _signal(direction=overrides.get("side", "long"))
    targets_snapshot = [{"label": "TP1", "price": str(signal.take_profit_1)}]
    if signal.take_profit_2 is not None:
        targets_snapshot.append({"label": "TP2", "price": str(signal.take_profit_2)})
    values: dict[str, Any] = {
        "user_id": USER_ID,
        "signal_id": SIGNAL_ID,
        "mode": "virtual",
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "side": signal.direction,
        "entry_min": Decimal("100"),
        "entry_max": Decimal("101"),
        "entry_price_policy": "accepted_entry_zone",
        "stop_loss": Decimal("95") if signal.direction == "long" else Decimal("105"),
        "targets_snapshot": targets_snapshot,
        "accepted_trade_plan_snapshot": {
            "entry": {"min_price": "100", "max_price": "101"},
            "accepted_signal": {
                "score": signal.score,
                "confidence": signal.confidence,
                "risk_reward": signal.risk_reward,
                "first_target_rr": signal.first_target_rr,
                "final_target_rr": signal.final_target_rr,
                "selected_rr": signal.selected_rr,
                "selected_rr_target": signal.selected_rr_target,
                "min_rr_ratio": signal.min_rr_ratio,
            },
        },
        "accepted_trade_plan_hash": accepted_trade_plan_hash(signal),
        "accepted_signal_status": "active",
        "accepted_signal_version": "v1",
        "accepted_signal_fingerprint": "signal-fingerprint",
        "execution_profile_snapshot": _execution_profile().model_dump(mode="json"),
        "request_snapshot": {
            "mode": "virtual",
            "user_id": str(USER_ID),
            "auto_enter_on_confirmation": True,
        },
        "idempotency_key": f"pending-entry:test:{signal.direction}",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    values.update(overrides)
    return PendingEntryIntentCreate(**values)


def _execution_profile() -> ResolvedExecutionProfile:
    return ResolvedExecutionProfile(
        execution_mode="virtual",
        instrument_type="spot",
        risk_mode="percent",
        risk_percent=Decimal("1.0"),
        fixed_risk_currency="USDT",
        leverage=Decimal("1"),
        rr_guard_mode="soft",
        min_rr_ratio=Decimal("2.0"),
        rr_target="final",
        radar_display_mode="all_market_opportunities",
    )


def _virtual_trade(signal: RadarSignal, request: ManualConfirmRequest) -> VirtualTrade:
    now = datetime.now(timezone.utc)
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    pending_entry_intent_id = metadata.get("pending_entry_intent_id")
    pending_entry_intent_id = str(pending_entry_intent_id) if pending_entry_intent_id is not None else None
    return VirtualTrade(
        id=str(TRADE_ID),
        user_id=request.user_id,
        signal_id=signal.id,
        pending_entry_intent_id=pending_entry_intent_id,
        accepted_trade_plan_hash=metadata.get("accepted_trade_plan_hash"),
        trigger_source=metadata.get("trigger_source"),
        origin=metadata.get("origin"),
        exchange=signal.exchange,
        symbol=signal.symbol,
        strategy=signal.strategy,
        timeframe=signal.timeframe,
        side=signal.direction,
        entry_price=100.5,
        current_price=100.5,
        size_usd=100.0,
        quantity=1.0,
        leverage=1,
        risk_percent=1.0,
        risk_amount=5.0,
        risk_reward=2.0,
        stop_loss=95.0 if signal.direction == "long" else 105.0,
        take_profit=[110.0],
        opened_at=now,
        updated_at=now,
        lifecycle_trace=LifecycleTrace(
            signal_id=signal.id,
            pending_entry_intent_id=pending_entry_intent_id,
            virtual_trade_id=str(TRADE_ID),
        ),
    )


def _virtual_rejection(reason: str, *, reason_code: str = "virtual_execution_rejected") -> VirtualExecutionRejected:
    return VirtualExecutionRejected(
        VirtualExecutionReport(
            status="rejected_virtual_execution",
            rejected_reason=reason,
            reason_code=reason_code,
            reason_codes=[reason_code],
            quality_gate=ExecutionQualityGate(
                status="blocked",
                message=reason,
                blockers=[reason_code],
            ),
        )
    )


def _patch_sqlite_column_types() -> list[tuple[Any, Any]]:
    patches: list[tuple[Any, Any]] = []
    for column_name in (
        "targets_snapshot",
        "accepted_trade_plan_snapshot",
        "execution_profile_snapshot",
        "request_snapshot",
    ):
        column = PendingEntryIntent.__table__.c[column_name]
        patches.append((column, column.type))
        column.type = JSON()
    return patches


def _restore_column_types(patches: list[tuple[Any, Any]]) -> None:
    for column, original_type in patches:
        column.type = original_type


def _create_sqlite_tables(engine: Any) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE pending_entry_intents (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    signal_id UUID NOT NULL,
                    strategy_id UUID,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_min NUMERIC NOT NULL,
                    entry_max NUMERIC NOT NULL,
                    entry_price_policy TEXT NOT NULL,
                    stop_loss NUMERIC NOT NULL,
                    targets_snapshot JSON NOT NULL,
                    accepted_trade_plan_snapshot JSON NOT NULL,
                    accepted_trade_plan_hash TEXT NOT NULL,
                    accepted_signal_status TEXT NOT NULL,
                    accepted_signal_version TEXT,
                    accepted_signal_fingerprint TEXT,
                    execution_profile_snapshot JSON NOT NULL,
                    request_snapshot JSON NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    expires_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    triggered_at DATETIME,
                    filled_at DATETIME,
                    filled_trade_id UUID,
                    failure_reason TEXT
                )
                """
            )
        )


def _create_sqlite_user_tables(engine: Any) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE app_users (
                    id UUID PRIMARY KEY,
                    email TEXT NOT NULL,
                    username TEXT,
                    status TEXT,
                    locale TEXT,
                    timezone TEXT,
                    risk_profile TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )


def _seed_demo_user(session_factory: Any) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            AppUser(
                id=USER_ID,
                email="demo@crypto-radar.local",
                username="demo",
                status="active",
                locale="ru",
                timezone="Europe/Warsaw",
                risk_profile="balanced",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


if __name__ == "__main__":
    unittest.main()
