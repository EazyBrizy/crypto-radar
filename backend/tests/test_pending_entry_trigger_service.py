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
from app.schemas.pending_entry import PendingEntryIntentCreate
from app.schemas.risk import ResolvedExecutionProfile
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, VirtualTrade
from app.schemas.user import RiskManagementSettings
from app.services.pending_entry import (
    TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
    PendingEntryService,
    accepted_trade_plan_hash,
)
from app.services.pending_entry_trigger import PendingEntryTriggerService, entry_zone_touch

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
        self.service = PendingEntryTriggerService(
            pending_entries=self.repository,
            signals=self.signals,
            virtual_trading=self.virtual,
            session_factory=self.SessionFactory,
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
            self.virtual.calls[0][1].metadata["lifecycle_trace"]["signal_id"],
            str(SIGNAL_ID),
        )

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
        self.assertEqual(current.status if current else None, "pending")
        self.assertEqual(self.virtual.calls, [])

    def test_signal_invalidated_cancels_intent(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.signals.signal = _signal(status="invalidated")

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "cancelled")
        self.assertEqual(current.status if current else None, "cancelled")
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
        self.assertEqual(self.signals.auto_entry_updates[-1]["status"], "requires_reconfirmation")
        self.assertEqual(self.signals.auto_entry_updates[-1]["message"], TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON)
        self.assertEqual(self.virtual.calls, [])

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

    def test_requires_reconfirmation_intent_cannot_fill(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long", status="requires_reconfirmation"))

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results, [])
        self.assertEqual(current.status if current else None, "requires_reconfirmation")
        self.assertEqual(self.virtual.calls, [])

    def test_riskgate_failure_creates_no_trade_and_keeps_pending_for_temporary_reason(self) -> None:
        created = self.repository.create_intent(_intent_create(side="long"))
        self.virtual.failure = ValueError("Spread too wide for entry right now.")

        results = self.service.process_market_tick("bybit", "BTCUSDT", {"ask": 100.5})
        current = self.repository.get_by_id(created.id)

        self.assertEqual(results[0].status, "pending")
        self.assertEqual(current.status if current else None, "pending")
        self.assertIn("Spread too wide", current.failure_reason if current else "")
        self.assertEqual(len(self.virtual.calls), 1)

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
        self.auto_entry_updates: list[dict[str, Any]] = []

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        if self.signal is None or self.signal.id != signal_id:
            return None
        return self.signal

    def update_auto_entry(self, signal_id: str, **kwargs: Any) -> RadarSignal | None:
        self.auto_entry_updates.append({"signal_id": signal_id, **kwargs})
        return self.signal


class _FakeVirtualTrading:
    def __init__(self) -> None:
        self.calls: list[tuple[RadarSignal, ManualConfirmRequest]] = []
        self.failure: Exception | None = None

    def confirm_signal(self, signal: RadarSignal, request: ManualConfirmRequest) -> tuple[RadarSignal, VirtualTrade]:
        self.calls.append((signal, request))
        if self.failure is not None:
            raise self.failure
        trade = _virtual_trade(signal, request)
        return signal.model_copy(update={"status": "confirmed", "confirmed_trade_id": trade.id}), trade


def _signal(
    *,
    status: str = "active",
    direction: str = "long",
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
        entry_min=entry_min,
        entry_max=entry_max,
        stop_loss=stop_loss if stop_loss is not None else (95.0 if direction == "long" else 105.0),
        take_profit_1=take_profit_1 if take_profit_1 is not None else (110.0 if direction == "long" else 90.0),
        take_profit_2=take_profit_2 if take_profit_2 is not None else (115.0 if direction == "long" else 85.0),
        created_at=now,
        updated_at=now,
    )


def _intent_create(**overrides: Any) -> PendingEntryIntentCreate:
    signal = _signal(direction=overrides.get("side", "long"))
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
        "targets_snapshot": [{"label": "TP1", "price": "110"}],
        "accepted_trade_plan_snapshot": {"entry": {"min_price": "100", "max_price": "101"}},
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
    return VirtualTrade(
        id=str(TRADE_ID),
        user_id=request.user_id,
        signal_id=signal.id,
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
