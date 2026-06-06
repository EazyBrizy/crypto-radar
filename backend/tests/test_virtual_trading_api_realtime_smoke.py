from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import radar as radar_api
from app.api.v1 import signals as signals_api
from app.api.v1 import trades as trades_api
from app.domain.signal_status import is_market_opportunity_status
from app.repositories.pending_entry_repository import PendingEntryIntentRepository
from app.schemas.market import MarketData
from app.schemas.signal import RadarSignal, StrategySignal
from app.services.market_scanner import MarketScanner
from app.services.pending_entry import PendingEntryService
from app.services.pending_entry_trigger import PendingEntryTriggerService
from app.services.radar_service import RadarService
from app.services.realtime_events import pending_entry_updated_event, signal_created_event
from app.services.signal_actions import SignalActionService
from app.services.signal_views import annotate_pending_entry_view
from app.services.trade_journal_service import TradeJournalService
from app.services.virtual_trading import VirtualTradingService
from backend.tests.test_trading_e2e_virtual_flow import (
    SIGNAL_ID,
    USER_ID,
    VIRTUAL_TRADE_ID,
    _CapturingRealtimeBroker,
    _DeterministicRiskGateService,
    _DeterministicVirtualTradeRepository,
    _NoopCandleStore,
    _NoopSignalAnalyticsWriter,
    _NoopSignalHotStore,
    _StableMarketDataService,
    _ZeroFeeRateService,
    _create_sqlite_pending_entry_tables,
    _create_sqlite_user_tables,
    _patch_sqlite_column_types,
    _restore_column_types,
    _risk_settings,
    _seed_demo_user,
)


AUTH_HEADERS = {"x-auth-user-id": str(USER_ID)}


class VirtualTradingApiRealtimeSmokeTest(unittest.TestCase):
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
        _create_sqlite_pending_entry_tables(self.engine)
        _seed_demo_user(self.SessionFactory)

        self.broker = _CapturingRealtimeBroker()
        self.signals = _InMemoryStrategySignalService()
        self.pending_events = _CapturingPendingEntryPublisher(self.broker)
        self.pending_repository = PendingEntryIntentRepository(self.SessionFactory)
        self.pending_service = PendingEntryService(
            repository=self.pending_repository,
            session_factory=self.SessionFactory,
            signal_loader=self.signals.get_signal,
            risk_settings_provider=_risk_settings,
            event_publisher=self.pending_events,
        )
        self.virtual_repository = _DeterministicVirtualTradeRepository(str(VIRTUAL_TRADE_ID))
        self.virtual_trading = VirtualTradingService(
            repository=self.virtual_repository,
            signal_analytics_writer=_NoopSignalAnalyticsWriter(),
            signal_hot_store=_NoopSignalHotStore(),
            risk_settings_provider=_risk_settings,
            market_data_service=_StableMarketDataService(),
            fee_rate_service=_ZeroFeeRateService(),
            risk_gate_service=_DeterministicRiskGateService(),
        )
        self.trigger_service = PendingEntryTriggerService(
            pending_entries=self.pending_repository,
            signals=self.signals,
            virtual_trading=self.virtual_trading,
            session_factory=self.SessionFactory,
            event_publisher=self.pending_events,
        )
        self.scanner = MarketScanner(
            symbols=["BTCUSDT"],
            exchanges=["bybit"],
            candle_store=_NoopCandleStore(),
            market_persistence=None,
            market_quality=None,
            support_resistance=None,
            signal_lifecycle=None,
            signal_outcomes=None,
            trade_invalidation=None,
            strategy_configs=None,
            virtual_trading=self.virtual_trading,
            pending_entry_trigger=self.trigger_service,
            derivative_market=None,
            alpha_market_context=None,
            scan_pairs=[("bybit", "BTCUSDT")],
        )
        self.action_service = SignalActionService(
            signals=self.signals,
            pending_entries=self.pending_service,
            virtual_trading=self.virtual_trading,
            risk_settings_provider=_risk_settings,
            market_data_service=_StableMarketDataService(),
            fee_rate_service=_ZeroFeeRateService(),
            realtime_broker=self.broker,
        )
        self.api_virtual_trading = _ApiVirtualTradingFacade(self.virtual_trading, default_user_id=str(USER_ID))
        self.trade_journal = TradeJournalService(
            execution_journal=self.api_virtual_trading,
            strategy_test_journal=_NoopBacktestJournal(),
        )
        self.radar_service = RadarService(
            signal_provider=self.signals,
            user_risk_settings_provider=_risk_settings,
            strategy_risk_settings_provider=lambda _signal, *, user_id: ({}, "test"),
            action_state_provider=lambda signal, user_id, mode: self.action_service.state_for_signal(
                signal,
                user_id=user_id,
                mode=mode,
            ),
        )

        self._patches = [
            patch("app.api.v1.radar.radar_service", self.radar_service),
            patch("app.api.v1.signals.signal_service", self.signals),
            patch("app.api.v1.signals._signal_action_service", return_value=self.action_service),
            patch("app.api.v1.trades.virtual_trading_service", self.api_virtual_trading),
            patch("app.api.v1.trades.trade_journal_service", self.trade_journal),
            patch("app.services.pending_entry.pending_entry_intent_service", self.pending_service),
            patch("app.services.market_scanner.realtime_event_broker", self.broker),
        ]
        for patcher in self._patches:
            patcher.start()

        app = FastAPI()
        api_router = APIRouter(prefix="/api/v1")
        api_router.include_router(radar_api.router)
        api_router.include_router(signals_api.router)
        api_router.include_router(trades_api.router)
        app.include_router(api_router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for patcher in reversed(self._patches):
            patcher.stop()
        self.engine.dispose()
        _restore_column_types(self._type_patches)

    def test_virtual_signal_action_pending_fill_close_journal_and_reconfirmation_smoke(self) -> None:
        signal = self._upsert_strategy_signal_and_publish_created()

        radar = self.client.get("/api/v1/radar", headers=AUTH_HEADERS)
        self.assertEqual(radar.status_code, 200)
        self.assertEqual([item["id"] for item in radar.json()["signals"]], [signal.id])
        created_event = _last_event(self.broker.events, "signal.created")
        self.assertIsNotNone(created_event)
        assert created_event is not None
        self.assertIsInstance(created_event["payload"]["signal"], dict)
        self.assertEqual(created_event["payload"]["signal"]["id"], signal.id)

        action_state = self.client.get(
            f"/api/v1/signals/{signal.id}/action-state",
            params={"mode": "virtual"},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(action_state.status_code, 200)
        self.assertTrue(action_state.json()["can_arm_pending"])
        self.assertEqual(action_state.json()["primary_action"], "arm_pending_entry")

        action = self.client.post(
            f"/api/v1/signals/{signal.id}/actions",
            json={"kind": "arm_pending_entry", "mode": "virtual"},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(action.status_code, 200)
        intent_payload = action.json()["pending_entry_intent"]
        self.assertEqual(intent_payload["status"], "pending")
        intent_id = intent_payload["id"]

        asyncio.run(self.scanner.process_tick(_market_tick(price=99.5, timestamp=1_780_000_000)))
        still_pending = self.pending_repository.get_by_id(intent_id)
        self.assertEqual(still_pending.status if still_pending else None, "pending")
        self.assertEqual(self.virtual_repository.list_virtual_trades(), [])

        asyncio.run(self.scanner.process_tick(_market_tick(price=100.5, timestamp=1_780_000_060)))
        filled = self.pending_repository.get_by_id(intent_id)
        self.assertEqual(filled.status if filled else None, "filled")
        self.assertEqual(str(filled.filled_trade_id), str(VIRTUAL_TRADE_ID))
        filled_event = _last_event(self.broker.events, "pending_entry.updated")
        self.assertEqual(filled_event["payload"]["status"], "filled")

        journal = self.client.get(
            "/api/v1/trades",
            params={"source": "virtual", "signal_id": signal.id},
        )
        self.assertEqual(journal.status_code, 200)
        open_journal = journal.json()
        self.assertEqual([trade["id"] for trade in open_journal["trades"]], [str(VIRTUAL_TRADE_ID)])
        self.assertEqual(open_journal["trades"][0]["status"], "open")
        self.assertEqual(open_journal["account"]["open_positions"], 1)

        asyncio.run(self.scanner.process_tick(_market_tick(price=110.0, timestamp=1_780_000_120)))
        closed_journal = self.client.get(
            "/api/v1/trades",
            params={"source": "virtual", "signal_id": signal.id},
        )
        self.assertEqual(closed_journal.status_code, 200)
        closed_payload = closed_journal.json()
        closed_trade = closed_payload["trades"][0]
        self.assertEqual(closed_trade["status"], "closed")
        self.assertEqual(closed_trade["close_reason"], "take_profit")
        self.assertGreater(closed_trade["realized_pnl"], 0)
        self.assertAlmostEqual(closed_payload["account"]["realized_pnl"], closed_trade["realized_pnl"])
        self.assertAlmostEqual(closed_payload["account"]["balance"], 100.0 + closed_trade["realized_pnl"])
        trade_closed = _last_event(self.broker.events, "trade.closed")
        self.assertIsNotNone(trade_closed)
        assert trade_closed is not None
        self.assertEqual(trade_closed["payload"]["trade"]["id"], str(VIRTUAL_TRADE_ID))

        second_action = self.client.post(
            f"/api/v1/signals/{signal.id}/actions",
            json={"kind": "arm_pending_entry", "mode": "virtual"},
            headers=AUTH_HEADERS,
        )
        self.assertEqual(second_action.status_code, 200)
        second_intent_id = second_action.json()["pending_entry_intent"]["id"]
        trade_count_before_reconfirmation = len(self.virtual_repository.list_virtual_trades())
        self.signals.replace_signal(
            _radar_signal(
                entry_min=98.0,
                entry_max=99.0,
                stop_loss=92.0,
                take_profit_1=112.0,
                updated_at=datetime.now(timezone.utc),
            )
        )

        asyncio.run(self.scanner.process_tick(_market_tick(price=99.0, timestamp=1_780_000_180)))
        reconfirmation_intent = self.pending_repository.get_by_id(second_intent_id)
        self.assertEqual(reconfirmation_intent.status if reconfirmation_intent else None, "requires_reconfirmation")
        self.assertIsNone(reconfirmation_intent.filled_trade_id if reconfirmation_intent else None)
        self.assertEqual(
            len(self.virtual_repository.list_virtual_trades()),
            trade_count_before_reconfirmation,
        )

        asyncio.run(self.scanner.process_tick(_market_tick(price=98.5, timestamp=1_780_000_240)))
        self.assertEqual(
            len(self.virtual_repository.list_virtual_trades()),
            trade_count_before_reconfirmation,
        )
        requires_event = _last_event(self.broker.events, "pending_entry.updated")
        self.assertEqual(requires_event["payload"]["status"], "requires_reconfirmation")

    def _upsert_strategy_signal_and_publish_created(self) -> RadarSignal:
        now = datetime.now(timezone.utc)
        radar_signal, created = self.signals.upsert_strategy_signal(
            StrategySignal(
                exchange="bybit",
                symbol="BTCUSDT",
                strategy="trend_pullback_continuation",
                direction="LONG",
                confidence=0.82,
                score=82,
                status="wait_for_pullback",
                timeframe="15m",
                entry_min=100.0,
                entry_max=101.0,
                stop_loss=95.0,
                take_profit_1=110.0,
                risk_reward=2.0,
                timestamp=int(now.timestamp()),
            )
        )
        if created:
            asyncio.run(self.broker.publish(signal_created_event(radar_signal)))
        return radar_signal


class _InMemoryStrategySignalService:
    def __init__(self) -> None:
        self.signal: RadarSignal | None = None

    def upsert_strategy_signal(
        self,
        signal: StrategySignal,
        exchange: str | None = None,
        explanation: list[str] | None = None,
    ) -> tuple[RadarSignal, bool]:
        created = self.signal is None
        self.signal = _radar_signal(
            exchange=exchange or signal.exchange,
            symbol=signal.symbol,
            strategy=signal.strategy,
            direction=signal.direction.lower(),
            confidence=signal.confidence,
            score=signal.score,
            status=signal.status,
            timeframe=signal.timeframe,
            entry_min=signal.entry_min,
            entry_max=signal.entry_max,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            risk_reward=signal.risk_reward,
            explanation=explanation or signal.explanation,
            execution_gate=signal.execution_gate,
        )
        return self.signal, created

    def replace_signal(self, signal: RadarSignal) -> None:
        self.signal = signal

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        if self.signal is None or self.signal.id != str(signal_id):
            return None
        return self.signal

    def list_signals(self) -> list[RadarSignal]:
        return [self.signal] if self.signal is not None else []

    def list_active_signals(self) -> list[RadarSignal]:
        return self.list_open_signals()

    def list_open_signals(self) -> list[RadarSignal]:
        if self.signal is None or not is_market_opportunity_status(self.signal.status):
            return []
        return [self.signal]


class _CapturingPendingEntryPublisher:
    def __init__(self, broker: _CapturingRealtimeBroker) -> None:
        self._broker = broker

    def publish_update(self, intent: Any, *, message: str | None = None) -> None:
        self._broker.events.append(
            pending_entry_updated_event(annotate_pending_entry_view(intent), message=message)
        )


class _ApiVirtualTradingFacade:
    def __init__(self, service: VirtualTradingService, *, default_user_id: str) -> None:
        self._service = service
        self._default_user_id = default_user_id

    def get_virtual_account(self, user_id: str = "demo_user"):
        resolved_user_id = self._default_user_id if user_id == "demo_user" else user_id
        return self._service.get_virtual_account(resolved_user_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)


class _NoopBacktestJournal:
    def list_journal(self, **_kwargs: Any) -> list[Any]:
        return []

    def get_entry(self, _trade_id: str) -> None:
        return None


def _radar_signal(
    *,
    exchange: str = "bybit",
    symbol: str = "BTCUSDT",
    strategy: str = "trend_pullback_continuation",
    direction: str = "long",
    confidence: float = 0.82,
    score: int = 82,
    status: str = "wait_for_pullback",
    timeframe: str = "15m",
    entry_min: float | None = 100.0,
    entry_max: float | None = 101.0,
    stop_loss: float | None = 95.0,
    take_profit_1: float | None = 110.0,
    risk_reward: float | None = 2.0,
    explanation: list[str] | None = None,
    updated_at: datetime | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=str(SIGNAL_ID),
        symbol=symbol,
        exchange=exchange,
        strategy=strategy,
        direction=direction,
        confidence=confidence,
        risk_reward=risk_reward,
        status=status,
        score=score,
        timeframe=timeframe,
        entry_min=entry_min,
        entry_max=entry_max,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        explanation=explanation or [],
        created_at=now,
        updated_at=updated_at or now,
        expires_at=now + timedelta(hours=1),
    )


def _market_tick(*, price: float, timestamp: int) -> MarketData:
    return MarketData(
        exchange="bybit",
        symbol="BTCUSDT",
        price=price,
        volume=1.0,
        timestamp=timestamp,
    )


def _last_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    return next((event for event in reversed(events) if event.get("type") == event_type), None)


if __name__ == "__main__":
    unittest.main()
