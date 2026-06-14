import asyncio
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.exchange_connection import ExchangeConnectionResponse
from app.schemas.risk import AccountRiskSnapshot, ResolvedExecutionProfile
from app.schemas.decision import SignalDecisionSnapshot
from app.schemas.signal import RadarSignal, SignalExecutionGateSnapshot
from app.schemas.trade import VirtualAccount
from app.schemas.user import RiskManagementSettings
from app.schemas.signal_action import SignalActionRequest
from app.services.signal_actions import REAL_PENDING_NOT_IMPLEMENTED_REASON_CODE, SignalActionService

USER_ID = "usr_demo"
SIGNAL_UUID = UUID("ba520631-d035-4f95-a4c0-3b40553dd527")
INTENT_UUID = UUID("ba520631-d035-4f95-a4c0-3b40553dd530")


class SignalActionStateTest(unittest.TestCase):
    def test_waiting_signal_can_arm_pending(self) -> None:
        state = _service().state_for_signal(_signal(status="ready"), mode="virtual", user_id=USER_ID)

        self.assertTrue(state.can_arm_pending)
        self.assertFalse(state.can_enter_now)
        self.assertEqual(state.primary_action, "arm_pending_entry")
        self.assertIsNone(state.disabled_reason_code)
        self.assertEqual(state.blockers, [])

    def test_wait_for_pullback_can_arm_pending_only_in_virtual_mode(self) -> None:
        connection = _exchange_connection(
            order_placement_mode="testnet_real_orders",
            can_place_orders=True,
            safety_blockers=[],
            account_snapshot_status="fresh",
        )
        signal = _signal(
            status="wait_for_pullback",
            decision=_decision(execution_allowed_real=True),
            execution_gate=_gate(can_arm_pending=True),
        )

        virtual_state = _service().state_for_signal(
            _signal(status="wait_for_pullback"),
            mode="virtual",
            user_id=USER_ID,
        )
        real_state = _service(connection=connection, account_snapshot=_fresh_account_snapshot()).state_for_signal(
            signal,
            mode="real",
            connection_id=str(connection.id),
            user_id=USER_ID,
        )

        self.assertTrue(virtual_state.can_arm_pending)
        self.assertEqual(virtual_state.primary_action, "arm_pending_entry")
        self.assertIsNone(virtual_state.disabled_reason_code)
        self.assertEqual(virtual_state.blockers, [])
        self.assertFalse(real_state.can_arm_pending)
        self.assertFalse(real_state.can_enter_now)
        self.assertIsNone(real_state.primary_action)
        self.assertEqual(real_state.disabled_reason_code, "real_pending_not_implemented")
        self.assertEqual(real_state.blockers[0].code, "real_pending_not_implemented")
        self.assertEqual(
            real_state.blockers[0].message,
            "Real pending entry is not implemented yet. Use virtual waiting entry or manual real execution.",
        )

    def test_real_pending_not_implemented_does_not_mask_connection_required(self) -> None:
        state = _service().state_for_signal(
            _signal(
                status="wait_for_pullback",
                decision=_decision(execution_allowed_real=True),
                execution_gate=_gate(can_arm_pending=True),
            ),
            mode="real",
            connection_id=None,
            user_id=USER_ID,
        )

        blocker_codes = [blocker.code for blocker in state.blockers]
        self.assertFalse(state.can_arm_pending)
        self.assertFalse(state.can_enter_now)
        self.assertEqual(state.disabled_reason_code, "exchange_connection_required")
        self.assertEqual(blocker_codes[0], "exchange_connection_required")
        self.assertIn("real_pending_not_implemented", blocker_codes[1:])

    def test_actionable_signal_can_enter_now(self) -> None:
        state = _service().state_for_signal(_signal(status="actionable"), mode="virtual", user_id=USER_ID)

        self.assertTrue(state.can_enter_now)
        self.assertFalse(state.can_arm_pending)
        self.assertEqual(state.primary_action, "enter_now")

    def test_real_enter_now_requires_real_context_even_when_signal_gate_passes(self) -> None:
        connection = _exchange_connection()
        signal = _signal(
            status="actionable",
            decision=_decision(execution_allowed_real=True),
            execution_gate=_gate(can_enter_now=True),
        )

        virtual_state = _service().state_for_signal(signal, mode="virtual", user_id=USER_ID)
        real_state = _service(connection=connection).state_for_signal(
            signal,
            mode="real",
            connection_id=str(connection.id),
            user_id=USER_ID,
        )

        self.assertTrue(virtual_state.can_enter_now)
        self.assertEqual(virtual_state.primary_action, "enter_now")
        self.assertFalse(real_state.can_enter_now)
        self.assertIsNone(real_state.primary_action)
        self.assertIn("real_order_placement_unavailable", {blocker.reason_code for blocker in real_state.blockers})
        self.assertIn("real_account_snapshot_required", {blocker.reason_code for blocker in real_state.blockers})

    def test_real_enter_now_requires_decision_allowed_real_true(self) -> None:
        connection = _exchange_connection(
            order_placement_mode="testnet_real_orders",
            can_place_orders=True,
            safety_blockers=[],
            account_snapshot_status="fresh",
        )
        signal = _signal(
            status="actionable",
            decision=_decision(execution_allowed_real=None),
            execution_gate=_gate(can_enter_now=True),
        )

        virtual_state = _service().state_for_signal(signal, mode="virtual", user_id=USER_ID)
        real_state = _service(connection=connection, account_snapshot=_fresh_account_snapshot()).state_for_signal(
            signal,
            mode="real",
            connection_id=str(connection.id),
            user_id=USER_ID,
        )

        self.assertTrue(virtual_state.can_enter_now)
        self.assertFalse(real_state.can_enter_now)
        self.assertEqual(real_state.disabled_reason_code, "real_execution_not_allowed")
        self.assertEqual(real_state.blockers[0].reason_code, "real_execution_not_allowed")

    def test_active_pending_can_cancel_and_blocks_enter(self) -> None:
        state = _service(intent=_pending_intent(status="pending")).state_for_signal(
            _signal(status="actionable"),
            mode="virtual",
            user_id=USER_ID,
        )

        self.assertTrue(state.can_cancel)
        self.assertFalse(state.can_enter_now)
        self.assertEqual(state.disabled_reason_code, "pending_entry_exists")
        self.assertEqual(state.blockers[0].code, state.disabled_reason_code)

    def test_requires_reconfirmation_can_reconfirm(self) -> None:
        state = _service(intent=_pending_intent(status="requires_reconfirmation")).state_for_signal(
            _signal(status="ready"),
            mode="virtual",
            user_id=USER_ID,
        )

        self.assertTrue(state.can_reconfirm)
        self.assertTrue(state.can_cancel)
        self.assertFalse(state.can_enter_now)
        self.assertEqual(state.primary_action, "reconfirm_pending_entry")

    def test_terminal_signal_has_no_trade_actions(self) -> None:
        state = _service().state_for_signal(_signal(status="expired"), mode="virtual", user_id=USER_ID)

        self.assertFalse(state.can_enter_now)
        self.assertFalse(state.can_arm_pending)
        self.assertFalse(state.can_reconfirm)
        self.assertFalse(state.can_cancel)
        self.assertEqual(state.disabled_reason_code, "status_not_execution_candidate")
        self.assertEqual(state.blockers[0].code, state.disabled_reason_code)

    def test_backend_owned_context_builds_confirm_request(self) -> None:
        request = _service().build_backend_confirm_request(
            _signal(status="actionable"),
            mode="virtual",
            connection_id=None,
            user_id=USER_ID,
        )

        self.assertEqual(request.user_id, USER_ID)
        self.assertEqual(request.account_balance, 10_000)
        self.assertEqual(request.leverage, 3)
        self.assertEqual(request.fee_rate, 0.001)
        self.assertEqual(request.slippage_bps, 0.0)
        self.assertEqual(request.max_open_positions, 3)

    def test_real_waiting_signal_returns_human_readable_pending_not_implemented_blocker(self) -> None:
        connection = _exchange_connection(
            order_placement_mode="testnet_real_orders",
            can_place_orders=True,
            safety_blockers=[],
            account_snapshot_status="fresh",
        )

        state = _service(connection=connection, account_snapshot=_fresh_account_snapshot()).state_for_signal(
            _signal(
                status="ready",
                decision=_decision(execution_allowed_real=True),
                execution_gate=_gate(can_arm_pending=True),
            ),
            mode="real",
            connection_id=str(connection.id),
            user_id=USER_ID,
        )

        self.assertFalse(state.can_arm_pending)
        self.assertFalse(state.can_enter_now)
        self.assertEqual(state.primary_action, None)
        self.assertEqual(REAL_PENDING_NOT_IMPLEMENTED_REASON_CODE, "real_pending_not_implemented")
        self.assertEqual(state.disabled_reason_code, "real_pending_not_implemented")
        self.assertEqual(state.blockers[0].code, state.disabled_reason_code)
        self.assertEqual(
            state.blockers[0].message,
            "Real pending entry is not implemented yet. Use virtual waiting entry or manual real execution.",
        )
        self.assertEqual(state.blockers[0].display_label, "Real pending unavailable")
        self.assertEqual(state.display_labels["disabled_reason"], "Real pending unavailable")

    def test_virtual_armable_waiting_setup_executes_arm_pending_entry(self) -> None:
        signal = _signal(
            status="wait_for_pullback",
            execution_gate=_gate(can_arm_pending=True, can_arm_virtual_pending=True),
        )
        pending_entries = _FakePendingEntryService(None)
        service = _service(signal=signal, pending_entries=pending_entries)

        response = asyncio.run(
            service.execute_action(
                signal.id,
                SignalActionRequest(kind="arm_pending_entry", mode="virtual"),
                user_id=USER_ID,
            )
        )

        self.assertEqual(response.message, "Pending entry armed; waiting for accepted entry zone")
        self.assertEqual(response.pending_entry_intent.status if response.pending_entry_intent else None, "pending")
        self.assertEqual(pending_entries.armed_signal_ids, [signal.id])


def _service(
    intent: PendingEntryIntentRead | None = None,
    *,
    signal: RadarSignal | None = None,
    pending_entries: "_FakePendingEntryService | None" = None,
    connection: ExchangeConnectionResponse | None = None,
    account_snapshot: AccountRiskSnapshot | None = None,
) -> SignalActionService:
    return SignalActionService(
        signals=_FakeSignalService(signal),
        pending_entries=pending_entries or _FakePendingEntryService(intent),
        virtual_trading=_FakeVirtualTradingService(),
        risk_settings_provider=lambda _user_id: RiskManagementSettings(),
        market_data_service=_FakeMarketDataService(),
        fee_rate_service=_FakeFeeRateService(),
        exchange_connections=_FakeExchangeConnectionService(connection),
        account_snapshots=_FakeAccountSnapshotService(account_snapshot),
        realtime_broker=_FakeRealtimeBroker(),
    )


class _FakeSignalService:
    def __init__(self, signal: RadarSignal | None = None) -> None:
        self.signal = signal

    def get_signal(self, signal_id: str):
        if self.signal is None or self.signal.id != signal_id:
            return None
        return self.signal


class _FakePendingEntryService:
    def __init__(self, intent: PendingEntryIntentRead | None) -> None:
        self.intent = intent
        self.armed_signal_ids: list[str] = []

    def get_active_for_signal(self, **_kwargs):
        return self.intent

    def arm_signal_workflow(self, *, signal_id, request):
        self.armed_signal_ids.append(str(signal_id))
        self.intent = _pending_intent(status="pending")
        return self.intent

    def resolve_execution_profile(self, _signal, _request, *, mode):
        return ResolvedExecutionProfile(
            execution_mode=mode,
            instrument_type="futures",
            risk_mode="percent",
            risk_percent=Decimal("1.0"),
            leverage=Decimal("3"),
            rr_guard_mode="soft",
            min_rr_ratio=Decimal("2.0"),
            rr_target="final",
            radar_display_mode="all_market_opportunities",
        )


class _FakeVirtualTradingService:
    def get_virtual_account(self, user_id: str = USER_ID):
        now = datetime.now(timezone.utc)
        return VirtualAccount(
            user_id=user_id,
            starting_balance=10_000,
            balance=10_000,
            equity=10_000,
            updated_at=now,
        )


class _FakeMarketDataService:
    def build_snapshot(self, **kwargs):
        return SimpleNamespace(
            warnings=(),
            slippage_bps=0.0,
            liquidation_price=None,
            entry_price=kwargs["fallback_entry_price"],
            market_data_status="fresh",
            orderbook_freshness_status="fresh",
        )


class _FakeFeeRateService:
    def resolve(self, **_kwargs):
        return SimpleNamespace(warnings=(), fee_rate=0.001)


class _FakeExchangeConnectionService:
    def __init__(self, connection: ExchangeConnectionResponse | None = None) -> None:
        self.connection = connection

    def get_connection_for_user(self, connection_id: str, *, user_id: str = USER_ID) -> ExchangeConnectionResponse:
        if self.connection is None or str(self.connection.id) != connection_id:
            raise LookupError("Exchange connection is not found.")
        return self.connection


class _FakeAccountSnapshotService:
    def __init__(self, snapshot: AccountRiskSnapshot | None = None) -> None:
        self.snapshot = snapshot

    def get_snapshot(self, **_kwargs):
        return self.snapshot


class _FakeRealtimeBroker:
    async def publish(self, _event):
        return None


def _exchange_connection(
    *,
    order_placement_mode: str = "dry_run",
    can_place_orders: bool = False,
    safety_blockers: list[str] | None = None,
    account_snapshot_status: str = "missing",
) -> ExchangeConnectionResponse:
    now = datetime.now(timezone.utc)
    return ExchangeConnectionResponse(
        id=UUID("ba520631-d035-4f95-a4c0-3b40553dd540"),
        user_id=UUID("ba520631-d035-4f95-a4c0-3b40553dd524"),
        exchange_id=UUID("ba520631-d035-4f95-a4c0-3b40553dd525"),
        exchange_code="bybit",
        exchange_name="Bybit",
        label="Bybit testnet",
        account_type="linear",
        key_ref="vault://stub/exchange/demo/bybit/testnet",
        permissions={"read": True, "trade": False},
        status="active",
        environment="testnet",
        order_placement_mode=order_placement_mode,
        can_place_orders=can_place_orders,
        safety_blockers=safety_blockers if safety_blockers is not None else ["ORDER_PLACEMENT_DRY_RUN"],
        mainnet_explicitly_enabled=False,
        last_sync_at=None,
        last_account_snapshot_at=None,
        account_snapshot_status=account_snapshot_status,
        revoked_at=None,
        deleted_at=None,
        deletion_reason=None,
        metadata={},
        created_at=now,
    )


def _signal(
    *,
    status: str,
    decision: SignalDecisionSnapshot | None = None,
    execution_gate: SignalExecutionGateSnapshot | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=str(SIGNAL_UUID),
        symbol="BTC/USDT:PERP",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        status=status,
        score=82,
        entry_min=100.0,
        entry_max=101.0,
        stop_loss=95.0,
        take_profit_1=110.0,
        created_at=now,
        updated_at=now,
        decision=decision,
        execution_gate=execution_gate,
    )


def _fresh_account_snapshot() -> AccountRiskSnapshot:
    return AccountRiskSnapshot(
        status="fresh",
        fetched_at=datetime.now(timezone.utc),
        account_equity=Decimal("10000"),
        available_balance=Decimal("9000"),
        wallet_balance=Decimal("10000"),
        positions=[],
        source="exchange",
        warnings=[],
    )


def _decision(*, execution_allowed_real: bool | None = None) -> SignalDecisionSnapshot:
    return SignalDecisionSnapshot(
        setup_valid=True,
        trade_plan_valid=True,
        market_context_score=0.9,
        signal_actionable=True,
        execution_allowed_virtual=True,
        execution_allowed_real=execution_allowed_real,
    )


def _gate(
    *,
    can_enter_now: bool = False,
    can_arm_pending: bool = False,
    can_arm_virtual_pending: bool | None = None,
    can_arm_real_pending: bool | None = None,
) -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="passed",
        feed_kind="execution_signal" if can_enter_now else "watchlist",
        can_notify=can_enter_now,
        can_enter_now=can_enter_now,
        can_arm_pending=can_arm_pending,
        can_arm_virtual_pending=can_arm_pending if can_arm_virtual_pending is None else can_arm_virtual_pending,
        can_arm_real_pending=can_arm_pending if can_arm_real_pending is None else can_arm_real_pending,
        can_show_in_execution_feed=can_enter_now,
    )


def _pending_intent(*, status: str) -> PendingEntryIntentRead:
    now = datetime.now(timezone.utc)
    return PendingEntryIntentRead(
        id=INTENT_UUID,
        user_id=UUID("ba520631-d035-4f95-a4c0-3b40553dd524"),
        signal_id=SIGNAL_UUID,
        mode="virtual",
        status=status,
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
        execution_profile_snapshot={"rr_guard_mode": "soft"},
        request_snapshot={"auto_enter_on_confirmation": True},
        idempotency_key="pending-entry:test",
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
