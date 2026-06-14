from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import JSON, create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models.pending_entry import PendingEntryIntent
from app.models.user import AppUser
from app.repositories.pending_entry_repository import PendingEntryIntentRepository
from app.schemas.lifecycle import LifecycleTrace
from app.schemas.market import MarketData
from app.schemas.risk import (
    BreakevenPlan,
    PositionSizingResult,
    RiskAdjustmentPlan,
    RiskCheckResult,
    RiskDecision,
    StopLossPlan,
    TakeProfitPlan,
    TakeProfitTarget,
    TrailingStopPlan,
)
from app.schemas.signal import (
    RadarSignal,
    SignalEdgeSnapshot,
    SignalExecutionGateSnapshot,
    SignalTriggerSnapshot,
)
from app.schemas.signal_action import SignalActionRequest
from app.schemas.trade import RealTrade, TradeJournalEntry, VirtualTrade
from app.schemas.trade_plan import (
    TradePlan,
    TradePlanEntry,
    TradePlanInvalidation,
    TradePlanRiskRules,
    TradePlanTarget,
)
from app.schemas.user import RiskManagementSettings
from app.services.market_scanner import MarketScanner
from app.services.pending_entry import PendingEntryService
from app.services.pending_entry_trigger import PendingEntryTriggerService
from app.services.risk_fee_rate import RiskFeeRateSnapshot
from app.services.risk_market_data import RiskMarketDataSnapshot
from app.services.signal_actions import SignalActionService
from app.services.virtual_trading import VirtualTradingService


USER_ID = UUID("7d7a4f33-a570-4334-b65f-3e5b4f0bb4a1")
SIGNAL_ID = UUID("eafefb92-8435-4d35-912f-6281ff0c1f19")
VIRTUAL_TRADE_ID = UUID("6a3aee25-8d76-4205-bab8-57e705de31b4")
TEST_NOW = datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc)


class TradingWorkflowE2ESmokeTest(unittest.IsolatedAsyncioTestCase):
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

        self.signals = _FakeSignalService(_hot_armable_signal())
        self.pending_events = _FakePendingEntryEventPublisher()
        self.pending_repository = PendingEntryIntentRepository(self.SessionFactory)
        self.pending_service = PendingEntryService(
            repository=self.pending_repository,
            session_factory=self.SessionFactory,
            signal_loader=self.signals.get_signal,
            risk_settings_provider=_risk_settings,
            event_publisher=self.pending_events,
            pending_entry_outcomes=_NoopPendingEntryOutcomes(),
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
            virtual_execution_profile_provider=_deterministic_virtual_profile,
        )
        self.action_service = SignalActionService(
            signals=self.signals,
            pending_entries=self.pending_service,
            virtual_trading=self.virtual_trading,
            risk_settings_provider=_risk_settings,
            market_data_service=_StableMarketDataService(),
            fee_rate_service=_ZeroFeeRateService(),
            realtime_broker=_CapturingRealtimeBroker(),
            virtual_execution_profile_provider=_deterministic_virtual_profile,
        )
        self.trigger_service = PendingEntryTriggerService(
            pending_entries=self.pending_service,
            signals=self.signals,
            virtual_trading=self.virtual_trading,
            session_factory=self.SessionFactory,
            event_publisher=self.pending_events,
        )
        self.realtime_broker = _CapturingRealtimeBroker()
        self._broker_patch = patch("app.services.market_scanner.realtime_event_broker", self.realtime_broker)
        self._broker_patch.start()
        self._trigger_now_patch = patch("app.services.pending_entry_trigger._utc_now", return_value=TEST_NOW)
        self._trigger_now_patch.start()
        self.scanner = MarketScanner(
            symbols=["SOLUSDT"],
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
            scan_pairs=[("bybit", "SOLUSDT")],
        )

    def tearDown(self) -> None:
        self._trigger_now_patch.stop()
        self._broker_patch.stop()
        self.engine.dispose()
        _restore_column_types(self._type_patches)

    async def test_signal_action_virtual_pending_runs_full_trade_to_journal(self) -> None:
        state = self.action_service.state_for_signal(
            self.signals.signal,
            mode="virtual",
            user_id=str(USER_ID),
        )
        self.assertTrue(state.can_arm_pending)
        self.assertEqual(state.primary_action, "arm_pending_entry")

        response = await self.action_service.execute_action(
            str(SIGNAL_ID),
            SignalActionRequest(kind="arm_pending_entry", mode="virtual"),
            user_id=str(USER_ID),
        )
        intent = response.pending_entry_intent

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(response.message, "Pending entry armed; waiting for accepted entry zone")
        self.assertEqual(intent.status, "pending")
        self.assertEqual(intent.exchange, "bybit")
        self.assertEqual(intent.symbol, "SOLUSDT")
        self.assertEqual(intent.accepted_signal_status, "wait_for_pullback")
        self.assertEqual(intent.accepted_trade_plan_snapshot["entry"]["min_price"], "20")
        self.assertEqual(len(intent.targets_snapshot), 2)
        self.assertEqual(self.pending_service.list_active_for_user(user_id=str(USER_ID))[0].id, intent.id)

        await self.scanner.process_tick(_market_tick(price=19.8, timestamp=1_780_000_000))
        still_pending = self.pending_repository.get_by_id(intent.id)
        self.assertEqual(still_pending.status if still_pending else None, "pending")
        self.assertEqual(self.virtual_repository.list_virtual_trades(), [])

        await self.scanner.process_tick(_market_tick(price=20.1, timestamp=1_780_000_060))
        filled_intent = self.pending_repository.get_by_id(intent.id)
        opened_trade = self.virtual_trading.get_virtual_trade(str(VIRTUAL_TRADE_ID))

        self.assertEqual(filled_intent.status if filled_intent else None, "filled")
        self.assertEqual(str(filled_intent.filled_trade_id), str(VIRTUAL_TRADE_ID))
        self.assertIsNotNone(opened_trade)
        assert opened_trade is not None
        self.assertEqual(opened_trade.status, "open")
        self.assertEqual(opened_trade.signal_id, str(SIGNAL_ID))
        self.assertEqual(opened_trade.pending_entry_intent_id, str(intent.id))
        self.assertEqual(opened_trade.origin.pending_entry_intent_id if opened_trade.origin else None, str(intent.id))
        self.assertEqual(opened_trade.trigger_source, "pending_entry")

        await self.scanner.process_tick(_market_tick(price=23.0, timestamp=1_780_000_120))
        closed_trade = self.virtual_trading.get_virtual_trade(str(VIRTUAL_TRADE_ID))
        journal = self.virtual_trading.list_trade_journal(mode="virtual", signal_id=str(SIGNAL_ID))
        active_trades = self.virtual_trading.list_virtual_trades(status="open", signal_id=str(SIGNAL_ID))
        closed_trades = self.virtual_trading.list_virtual_trades(status="closed", signal_id=str(SIGNAL_ID))
        account = self.virtual_trading.get_virtual_account(str(USER_ID))

        self.assertIsNotNone(closed_trade)
        assert closed_trade is not None
        self.assertEqual(closed_trade.status, "closed")
        self.assertEqual(closed_trade.close_reason, "take_profit")
        self.assertGreater(closed_trade.realized_pnl, 0.0)
        self.assertAlmostEqual(closed_trade.pnl or 0.0, closed_trade.realized_pnl)
        self.assertEqual(active_trades, [])
        self.assertEqual([trade.id for trade in closed_trades], [str(VIRTUAL_TRADE_ID)])
        self.assertEqual([entry.id for entry in journal], [str(VIRTUAL_TRADE_ID)])
        self.assertEqual(journal[0].signal_id, str(SIGNAL_ID))
        self.assertEqual(journal[0].pending_entry_intent_id, str(intent.id))
        self.assertEqual(journal[0].close_reason, "take_profit")
        self.assertGreater(journal[0].pnl or 0.0, 0.0)
        self.assertEqual(account.open_positions, 0)
        self.assertEqual(account.closed_trades, 1)
        self.assertEqual(account.wins, 1)

        funnel_events = _workflow_funnel_events(
            pending_events=self.pending_events.events,
            trade=closed_trade,
            realtime_events=self.realtime_broker.events,
        )
        self.assertEqual(funnel_events, ["armed", "touched", "filled", "closed"])


class _FakeSignalService:
    def __init__(self, signal: RadarSignal) -> None:
        self.signal = signal

    def get_signal(self, signal_id: str) -> RadarSignal | None:
        if self.signal.id != str(signal_id):
            return None
        return self.signal


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


class _DeterministicVirtualTradeRepository:
    def __init__(self, trade_id: str) -> None:
        self.trade_id = trade_id
        self._virtual_trades: dict[str, VirtualTrade] = {}
        self._assigned = False

    def save_virtual_trade(self, trade: VirtualTrade) -> VirtualTrade:
        persisted = trade
        if not self._assigned and trade.id != self.trade_id:
            persisted = _with_persisted_virtual_trade_id(trade, self.trade_id)
            self._assigned = True
        self._virtual_trades[persisted.id] = persisted
        return persisted

    def get_virtual_trade(self, trade_id: str) -> VirtualTrade | None:
        return self._virtual_trades.get(trade_id)

    def list_virtual_trades(
        self,
        status: str | None = None,
        signal_id: str | None = None,
    ) -> list[VirtualTrade]:
        trades = list(self._virtual_trades.values())
        if status is not None:
            trades = [trade for trade in trades if trade.status == status]
        if signal_id is not None:
            trades = [trade for trade in trades if trade.signal_id == signal_id]
        return sorted(trades, key=lambda trade: trade.opened_at, reverse=True)

    def delete_virtual_trade(self, trade_id: str) -> None:
        self._virtual_trades.pop(trade_id, None)

    def save_real_trade(self, trade: RealTrade) -> RealTrade:
        raise NotImplementedError

    def get_real_trade(self, trade_id: str) -> RealTrade | None:
        return None

    def list_real_trades(
        self,
        status: str | None = None,
        signal_id: str | None = None,
    ) -> list[RealTrade]:
        return []

    def list_journal(
        self,
        mode: str | None = None,
        status: str | None = None,
        signal_id: str | None = None,
    ) -> list[TradeJournalEntry]:
        if mode == "real":
            return []
        return [
            TradeJournalEntry.model_validate(trade.model_dump())
            for trade in self.list_virtual_trades(status=status, signal_id=signal_id)
        ]


class _StableMarketDataService:
    def build_snapshot(
        self,
        *,
        exchange: str,
        symbol: str,
        fallback_entry_price: float,
        manual_entry_price: float | None = None,
        manual_slippage_bps: float = 0.0,
        **_kwargs: Any,
    ) -> RiskMarketDataSnapshot:
        entry_price = manual_entry_price or fallback_entry_price
        return RiskMarketDataSnapshot(
            exchange=exchange,
            symbol=symbol,
            category=None,
            entry_price=entry_price,
            slippage_bps=manual_slippage_bps,
            best_bid=entry_price,
            best_ask=entry_price,
            spread_percent=0.0,
            spread_bps=0.0,
            orderbook_depth_usd=1_000_000.0,
            market_data_status="fresh",
            market_data_source="test",
        )


class _ZeroFeeRateService:
    def resolve(self, **_kwargs: Any) -> RiskFeeRateSnapshot:
        return RiskFeeRateSnapshot(
            fee_rate=0.0,
            maker_fee_rate=0.0,
            taker_fee_rate=0.0,
            source="test",
        )


class _DeterministicRiskGateService:
    def evaluate(self, **kwargs: Any) -> RiskDecision:
        return _risk_decision(kwargs["context"])


class _NoopSignalAnalyticsWriter:
    def write_event(self, event: dict[str, Any]) -> None:
        return None


class _NoopSignalHotStore:
    def write_signal(self, result: Any) -> None:
        return None


class _NoopPendingEntryOutcomes:
    def record_pending_entry_terminal(self, intent: Any) -> None:
        return None


class _NoopCandleStore:
    timeframes = ["15m"]

    def update_from_tick(self, data: MarketData) -> list[Any]:
        return []

    def list_candles(self, **_kwargs: Any) -> list[Any]:
        return []


class _CapturingRealtimeBroker:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _hot_armable_signal() -> RadarSignal:
    return RadarSignal(
        id=str(SIGNAL_ID),
        symbol="SOLUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.9,
        risk_reward=3.0,
        first_target_rr=1.0,
        final_target_rr=3.0,
        selected_rr=3.0,
        selected_rr_target="final",
        min_rr_ratio=2.0,
        status="wait_for_pullback",
        score=90,
        timeframe="15m",
        candle_state="closed",
        entry_min=20.0,
        entry_max=20.2,
        stop_loss=19.0,
        take_profit_1=21.0,
        take_profit_2=23.0,
        trade_plan=_trade_plan(),
        trigger=SignalTriggerSnapshot(
            passed=True,
            trigger_type="pullback_touch",
            price=20.1,
            candle_state="closed",
            confirmed_at=TEST_NOW,
            metadata={
                "confirmed_on_closed_candle": True,
                "trigger_candle_state": "closed",
                "source": "e2e_smoke",
            },
        ),
        edge=SignalEdgeSnapshot(
            status="positive",
            sample_size=120,
            min_sample_size=50,
            expectancy_after_costs_r=0.2,
            profit_factor=1.5,
            confidence_score=0.85,
            source="outcome",
        ),
        execution_gate=SignalExecutionGateSnapshot(
            status="passed",
            feed_kind="watchlist",
            can_notify=True,
            can_enter_now=False,
            can_arm_pending=True,
            can_arm_virtual_pending=True,
            can_arm_real_pending=False,
            can_show_in_execution_feed=True,
            metadata={
                "can_arm_pending": True,
                "confirmed_on_closed_candle": True,
            },
        ),
        created_at=TEST_NOW,
        updated_at=TEST_NOW,
        expires_at=TEST_NOW + timedelta(hours=1),
        lifecycle_trace=LifecycleTrace(signal_id=str(SIGNAL_ID)),
    )


def _trade_plan() -> TradePlan:
    return TradePlan(
        entry=TradePlanEntry(
            price=20.1,
            min_price=20.0,
            max_price=20.2,
            source="e2e_smoke",
        ),
        stop_loss=19.0,
        targets=[
            TradePlanTarget(
                label="TP1",
                price=21.0,
                r_multiple=1.0,
                action="partial_close",
                close_percent=50.0,
                source="e2e_smoke",
            ),
            TradePlanTarget(
                label="TP2",
                price=23.0,
                r_multiple=3.0,
                action="full_close",
                close_percent=100.0,
                source="e2e_smoke",
            ),
        ],
        invalidation=TradePlanInvalidation(
            price=19.0,
            hard_stop=19.0,
            conditions=["Long setup invalid below pullback structure."],
            metadata={"source": "e2e_smoke"},
        ),
        risk_rules=TradePlanRiskRules(
            risk_reward=3.0,
            first_target_rr=1.0,
            final_target_rr=3.0,
            selected_rr=3.0,
            selected_rr_target="final",
            min_rr_ratio=2.0,
        ),
        metadata={"signal_version": "patch-7.3-smoke"},
    )


def _market_tick(*, price: float, timestamp: int) -> MarketData:
    return MarketData(
        exchange="bybit",
        symbol="SOLUSDT",
        price=price,
        volume=1.0,
        timestamp=timestamp,
    )


def _risk_decision(context: Any) -> RiskDecision:
    entry = float(context.entry_price)
    stop = 19.0
    targets = [
        TakeProfitTarget(
            label="TP1",
            r_multiple=(21.0 - entry) / max(entry - stop, 0.000001),
            price=21.0,
            close_percent=50.0,
            action="observe",
        ),
        TakeProfitTarget(
            label="TP2",
            r_multiple=(23.0 - entry) / max(entry - stop, 0.000001),
            price=23.0,
            close_percent=100.0,
            action="full_close",
        ),
    ]
    notional = float(context.requested_notional or 100.0)
    quantity = notional / entry
    risk_per_unit = max(entry - stop, 0.000001)
    risk_amount = risk_per_unit * quantity
    final_rr = targets[-1].r_multiple
    sizing = PositionSizingResult(
        side=context.side,
        account_equity=context.account_equity,
        risk_per_trade_percent=1.0,
        risk_amount=risk_amount,
        entry_price=entry,
        stop_loss_price=stop,
        stop_distance_per_unit=risk_per_unit,
        effective_risk_per_unit=risk_per_unit,
        position_size_base=quantity,
        notional=notional,
        leverage=1,
        required_margin=notional,
        fee_rate=0.0,
        slippage_bps=0.0,
    )
    risk_adjustment = RiskAdjustmentPlan(
        instrument_type=context.instrument_type,
        strategy=context.strategy,
        signal_score=context.signal_score,
        account_equity=context.account_equity,
        base_risk_percent=1.0,
        base_risk_amount=context.account_equity * 0.01,
        strategy_risk_multiplier=1.0,
        signal_score_multiplier=1.0,
        adjusted_risk_percent=1.0,
        adjusted_risk_amount=context.account_equity * 0.01,
        signal_trade_allowed=True,
    )
    risk_check = RiskCheckResult(
        status="passed",
        blockers=[],
        warnings=[],
        rr=final_rr,
        min_rr_ratio=2.0,
        account_equity=context.account_equity,
        adjusted_risk_amount=context.account_equity * 0.01,
        adjusted_risk_percent=1.0,
        effective_risk_amount=risk_amount,
        position_notional=notional,
        position_size_base=quantity,
        required_margin=notional,
        available_balance=context.available_balance,
        max_daily_loss_percent=50.0,
        max_account_drawdown_percent=90.0,
        max_open_risk_percent=100.0,
        max_correlated_risk_percent=100.0,
        exchange_rule_status="fresh",
        market_data_status="fresh",
        best_bid=context.best_bid,
        best_ask=context.best_ask,
        spread_percent=0.0,
        spread_bps=0.0,
        orderbook_depth_usd=context.orderbook_depth_usd,
    )
    return RiskDecision(
        mode=context.mode,
        stage=context.stage,
        status="passed",
        can_enter=True,
        lifecycle_trace=context.lifecycle_trace,
        risk_profile_source=context.risk_profile_source,
        execution_profile_sources=context.execution_profile_sources,
        exchange=context.exchange,
        symbol=context.symbol,
        instrument_type=context.instrument_type,
        requested_notional=context.requested_notional,
        risk_adjustment_plan=risk_adjustment,
        position_sizing=sizing,
        checked_position_sizing=sizing,
        risk_check=risk_check,
        stop_loss_plan=StopLossPlan(
            side=context.side,
            mode="structure",
            entry_price=entry,
            stop_loss_price=stop,
            risk_per_unit=risk_per_unit,
            source="test",
            default_stop_loss_percent=1.5,
            atr_period=14,
            atr_multiplier=2.0,
        ),
        take_profit_plan=TakeProfitPlan(
            mode="risk_multiple",
            side=context.side,
            entry_price=entry,
            stop_loss_price=stop,
            risk_per_unit=risk_per_unit,
            partial_take_profit_enabled=True,
            targets=targets,
            selected_rr=final_rr,
        ),
        breakeven_plan=BreakevenPlan(
            side=context.side,
            entry_price=entry,
            stop_loss_price=stop,
            risk_per_unit=risk_per_unit,
            move_after_r=1.0,
            trigger_price=21.0,
            breakeven_stop_price=entry,
        ),
        trailing_stop_plan=TrailingStopPlan(
            side=context.side,
            enabled=False,
            mode="percent",
            entry_price=entry,
            current_price=entry,
            trailing_percent=0.0,
            atr_multiplier=2.0,
            source="disabled",
        ),
    )


def _risk_settings(_user_id: str) -> RiskManagementSettings:
    return RiskManagementSettings(
        risk_profile="balanced",
        risk_per_trade_percent=1.0,
        min_rr_ratio=2.0,
        max_daily_loss_percent=50.0,
        max_account_drawdown_percent=90.0,
        max_open_risk_percent=100.0,
        max_correlated_risk_percent=100.0,
        stop_loss_mode="structure",
        virtual_starting_balance=100.0,
        virtual_trading_uses_realistic_execution=True,
        virtual_execution_profile="deterministic_test",
        max_spread_bps_for_entry=50.0,
    )


def _deterministic_virtual_profile(
    _user_id: str,
    _risk_settings: RiskManagementSettings | None = None,
) -> str:
    return "deterministic_test"


def _with_persisted_virtual_trade_id(trade: VirtualTrade, trade_id: str) -> VirtualTrade:
    pending_entry_intent_id = trade.pending_entry_intent_id or trade.lifecycle_trace.pending_entry_intent_id
    trace = trade.lifecycle_trace.model_copy(
        update={
            "signal_id": trade.signal_id,
            "pending_entry_intent_id": pending_entry_intent_id,
            "virtual_trade_id": trade_id,
        }
    )
    origin = None
    if trade.origin is not None:
        origin = trade.origin.model_copy(
            update={
                "signal_id": trade.signal_id,
                "pending_entry_intent_id": pending_entry_intent_id,
                "virtual_trade_id": trade_id,
                "position_id": trade_id,
            }
        )
    lifecycle_events = []
    for event in trade.lifecycle_events:
        event_trace = event.lifecycle_trace.model_copy(
            update={
                "signal_id": trade.signal_id,
                "pending_entry_intent_id": pending_entry_intent_id,
                "virtual_trade_id": trade_id,
            }
        )
        lifecycle_events.append(
            event.model_copy(
                update={
                    "signal_id": trade.signal_id,
                    "pending_entry_intent_id": pending_entry_intent_id,
                    "virtual_trade_id": trade_id,
                    "lifecycle_trace": event_trace,
                }
            )
        )
    execution = trade.execution
    if execution is not None:
        risk_decision = execution.risk_decision
        if risk_decision is not None:
            risk_decision = risk_decision.model_copy(
                update={
                    "lifecycle_trace": risk_decision.lifecycle_trace.model_copy(
                        update={
                            "signal_id": trade.signal_id,
                            "pending_entry_intent_id": pending_entry_intent_id,
                            "virtual_trade_id": trade_id,
                        }
                    )
                }
            )
        execution = execution.model_copy(update={"lifecycle_trace": trace, "risk_decision": risk_decision})
    return trade.model_copy(
        update={
            "id": trade_id,
            "pending_entry_intent_id": pending_entry_intent_id,
            "origin": origin,
            "lifecycle_trace": trace,
            "lifecycle_events": lifecycle_events,
            "execution": execution,
        }
    )


def _workflow_funnel_events(
    *,
    pending_events: list[dict[str, str | None]],
    trade: VirtualTrade,
    realtime_events: list[dict[str, Any]],
) -> list[str]:
    events: list[str] = []
    if any(event["status"] == "pending" for event in pending_events):
        events.append("armed")
    if any(event.event_type == "created_from_pending_entry" for event in trade.lifecycle_events):
        events.append("touched")
    if any(event["status"] == "filled" for event in pending_events):
        events.append("filled")
    if trade.close_reason in {"take_profit", "stop_loss"} and any(
        event.get("type") == "trade.closed" for event in realtime_events
    ):
        events.append("closed")
    return events


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


def _create_sqlite_pending_entry_tables(engine: Any) -> None:
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
                timezone="Europe/Moscow",
                risk_profile="balanced",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


if __name__ == "__main__":
    unittest.main()
