import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.exchange_connection import ExchangeConnectionResponse
from app.schemas.risk import ResolvedExecutionProfile
from app.schemas.signal import RadarSignal, SignalExecutionGateReason, SignalExecutionGateSnapshot
from app.schemas.trade import VirtualAccount
from app.schemas.user import RiskManagementSettings
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

    def test_actionable_signal_can_enter_now(self) -> None:
        state = _service().state_for_signal(_signal(status="actionable"), mode="virtual", user_id=USER_ID)

        self.assertTrue(state.can_enter_now)
        self.assertFalse(state.can_arm_pending)
        self.assertEqual(state.primary_action, "enter_now")

    def test_active_pending_can_cancel_and_blocks_enter(self) -> None:
        state = _service(intent=_pending_intent(status="pending")).state_for_signal(
            _signal(status="actionable"),
            mode="virtual",
            user_id=USER_ID,
        )

        self.assertTrue(state.can_cancel)
        self.assertFalse(state.can_enter_now)
        self.assertEqual(state.disabled_reason_code, "pending_entry_active")

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
        self.assertEqual(state.disabled_reason_code, "signal_terminal")

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

    def test_real_waiting_signal_cannot_arm_pending_until_tick_driven_execution_exists(self) -> None:
        connection = _exchange_connection()

        state = _service(connection=connection).state_for_signal(
            _signal(status="ready"),
            mode="real",
            connection_id=str(connection.id),
            user_id=USER_ID,
        )

        self.assertFalse(state.can_arm_pending)
        self.assertFalse(state.can_enter_now)
        self.assertEqual(state.primary_action, None)
        self.assertEqual(state.disabled_reason_code, REAL_PENDING_NOT_IMPLEMENTED_REASON_CODE)
        self.assertEqual(state.blockers[0].code, REAL_PENDING_NOT_IMPLEMENTED_REASON_CODE)

    def test_signal_action_state_always_has_disabled_reason(self) -> None:
        state = _service().state_for_signal(
            _signal(
                status="ready",
                execution_gate=_execution_gate(
                    can_enter_now=False,
                    can_arm_pending=True,
                    reasons=[
                        _gate_reason(
                            "trigger_not_confirmed",
                            "Trigger is waiting for a closed-candle confirmation.",
                            source="trigger",
                        )
                    ],
                ),
            ),
            mode="virtual",
            user_id=USER_ID,
        )

        self.assertFalse(state.can_enter_now)
        self.assertTrue(state.can_arm_pending)
        self.assertEqual(state.disabled_reason_code, "trigger_not_confirmed")
        self.assertEqual(state.blockers[0].code, "trigger_not_confirmed")
        self.assertEqual(
            state.display_labels["disabled_reason"],
            "Trigger is waiting for a closed-candle confirmation.",
        )

    def test_signal_action_reason_prioritizes_execution_gate_blocker(self) -> None:
        from app.services.signal_action_reason import main_execution_blocker

        reason = main_execution_blocker(
            _signal(
                status="ready",
                execution_gate=_execution_gate(
                    reasons=[
                        _gate_reason(
                            "edge_unknown",
                            "Edge is still being calibrated.",
                            severity="warning",
                            source="edge",
                        ),
                        _gate_reason(
                            "forming_candle",
                            "Candle is still forming.",
                            source="data",
                        ),
                    ],
                ),
            )
        )

        self.assertEqual(reason["code"], "forming_candle")
        self.assertEqual(reason["message"], "Candle is still forming.")
        self.assertEqual(reason["source"], "data")
        self.assertEqual(reason["severity"], "blocker")


def _service(
    intent: PendingEntryIntentRead | None = None,
    *,
    connection: ExchangeConnectionResponse | None = None,
) -> SignalActionService:
    return SignalActionService(
        signals=_FakeSignalService(),
        pending_entries=_FakePendingEntryService(intent),
        virtual_trading=_FakeVirtualTradingService(),
        risk_settings_provider=lambda _user_id: RiskManagementSettings(),
        market_data_service=_FakeMarketDataService(),
        fee_rate_service=_FakeFeeRateService(),
        exchange_connections=_FakeExchangeConnectionService(connection),
        account_snapshots=_FakeAccountSnapshotService(),
        realtime_broker=_FakeRealtimeBroker(),
    )


class _FakeSignalService:
    def get_signal(self, _signal_id: str):
        return None


class _FakePendingEntryService:
    def __init__(self, intent: PendingEntryIntentRead | None) -> None:
        self.intent = intent

    def get_active_for_signal(self, **_kwargs):
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
    pass


class _FakeRealtimeBroker:
    async def publish(self, _event):
        return None


def _exchange_connection() -> ExchangeConnectionResponse:
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
        order_placement_mode="dry_run",
        can_place_orders=False,
        safety_blockers=["ORDER_PLACEMENT_DRY_RUN"],
        mainnet_explicitly_enabled=False,
        last_sync_at=None,
        last_account_snapshot_at=None,
        account_snapshot_status="missing",
        revoked_at=None,
        deleted_at=None,
        deletion_reason=None,
        metadata={},
        created_at=now,
    )


def _signal(
    *,
    status: str,
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
        execution_gate=execution_gate,
        created_at=now,
        updated_at=now,
    )


def _execution_gate(
    *,
    can_enter_now: bool = False,
    can_arm_pending: bool = False,
    reasons: list[SignalExecutionGateReason] | None = None,
) -> SignalExecutionGateSnapshot:
    return SignalExecutionGateSnapshot(
        status="blocked",
        feed_kind="blocked",
        can_notify=False,
        can_enter_now=can_enter_now,
        can_arm_pending=can_arm_pending,
        can_show_in_execution_feed=False,
        reasons=reasons or [],
        warnings=[],
        metadata={},
    )


def _gate_reason(
    code: str,
    message: str,
    *,
    severity: str = "blocker",
    source: str = "execution_gate",
) -> SignalExecutionGateReason:
    return SignalExecutionGateReason(
        code=code,
        severity=severity,
        source=source,
        message=message,
        metadata={},
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
