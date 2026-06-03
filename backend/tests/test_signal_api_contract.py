import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import signals as signals_api
from app.api.v1.signals import confirm_signal, list_active_signals, list_open_signals
from app.api.v1.trades import confirm_real_trade
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, RealConfirmRequest, RealExecutionResult
from app.schemas.user import RiskManagementSettings
from app.services.execution_service import RealExecutionService
from app.services.risk_market_data import RiskMarketDataSnapshot
from backend.tests.ephemeral_signal_service import ephemeral_signal_service


class _FakeRealtimeBroker:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


class _FakeRealExecutionService:
    def __init__(self, result: RealExecutionResult) -> None:
        self.result = result
        self.calls = 0

    async def place_order(self, signal: RadarSignal, request: ManualConfirmRequest) -> RealExecutionResult:
        self.calls += 1
        return self.result


class _FakeMarketDataService:
    def build_snapshot(self, *args, **kwargs) -> RiskMarketDataSnapshot:
        entry_price = float(kwargs["fallback_entry_price"])
        return RiskMarketDataSnapshot(
            exchange=kwargs["exchange"],
            symbol=kwargs["symbol"],
            category="spot",
            entry_price=entry_price,
            slippage_bps=kwargs.get("manual_slippage_bps", 0.0),
            best_bid=entry_price - 0.05,
            best_ask=entry_price + 0.05,
            mark_price=entry_price,
            spread_percent=0.1,
            spread_bps=10.0,
            orderbook_depth_usd=100_000.0,
            market_data_status="fresh",
            market_data_source="test",
        )


class SignalApiContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.signal_service = ephemeral_signal_service()

    async def asyncTearDown(self) -> None:
        self.signal_service = None

    async def test_active_signals_endpoint_returns_only_open_execution_candidates(self) -> None:
        now = datetime.now(timezone.utc)
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_active_market_opportunity",
                symbol="SOL/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="long",
                confidence=0.8,
                status="active",
                score=80,
                created_at=now,
                updated_at=now,
            )
        )
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_actionable",
                symbol="BTC/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="long",
                confidence=0.8,
                status="actionable",
                score=80,
                created_at=now,
                updated_at=now,
            )
        )
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_confirmed",
                symbol="ETH/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="long",
                confidence=0.8,
                status="confirmed",
                score=80,
                created_at=now,
                updated_at=now,
            )
        )

        with patch("app.api.v1.signals.signal_service", self.signal_service):
            signals = await list_active_signals()

        self.assertEqual([signal.id for signal in signals], ["sig_actionable"])

    async def test_active_signals_endpoint_expires_stale_signals(self) -> None:
        now = datetime.now(timezone.utc)
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_stale",
                symbol="BTC/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="long",
                confidence=0.8,
                status="actionable",
                score=80,
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            )
        )
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_fresh",
                symbol="ETH/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="short",
                confidence=0.8,
                status="actionable",
                score=80,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(minutes=20),
            )
        )

        with patch("app.api.v1.signals.signal_service", self.signal_service):
            signals = await list_active_signals()

        self.assertEqual([signal.id for signal in signals], ["sig_fresh"])
        stale_signal = self.signal_service.get_signal("sig_stale")
        self.assertEqual(stale_signal.status if stale_signal else None, "expired")

    async def test_open_signals_endpoint_keeps_watchlist_candidates(self) -> None:
        now = datetime.now(timezone.utc)
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_watchlist",
                symbol="BTC/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="long",
                confidence=0.62,
                status="watchlist",
                score=62,
                created_at=now,
                updated_at=now,
            )
        )
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_wait_for_pullback",
                symbol="ETH/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="short",
                confidence=0.82,
                status="wait_for_pullback",
                score=82,
                created_at=now,
                updated_at=now,
            )
        )
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_confirmed",
                symbol="SOL/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="long",
                confidence=0.9,
                status="confirmed",
                score=90,
                created_at=now,
                updated_at=now,
            )
        )

        with patch("app.api.v1.signals.signal_service", self.signal_service):
            signals = await list_open_signals()

        self.assertEqual([signal.id for signal in signals], ["sig_watchlist", "sig_wait_for_pullback"])

    async def test_confirm_endpoint_arms_auto_entry_for_non_actionable_signal(self) -> None:
        now = datetime.now(timezone.utc)
        signal = RadarSignal(
            id="sig_ready",
            symbol="BTC/USDT:PERP",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction="long",
            confidence=0.74,
            status="ready",
            score=74,
            created_at=now,
            updated_at=now,
        )
        self.signal_service.add_signal(signal)
        broker = _FakeRealtimeBroker()

        with (
            patch("app.api.v1.signals.signal_service", self.signal_service),
            patch("app.api.v1.signals.realtime_event_broker", broker),
        ):
            response = await confirm_signal(
                signal.id,
                ManualConfirmRequest(mode="virtual", user_id="demo_user", auto_enter_on_confirmation=True),
            )

        self.assertEqual(response.signal.status, "ready")
        self.assertEqual(response.signal.auto_entry.status if response.signal.auto_entry else None, "pending")
        self.assertEqual(response.signal.auto_entry.mode if response.signal.auto_entry else None, "virtual")
        self.assertIn("Auto-entry armed", response.message)
        self.assertEqual(broker.events[0]["type"], "signal.updated")

    async def test_confirm_endpoint_allows_auto_entry_when_virtual_rr_guard_is_soft(self) -> None:
        now = datetime.now(timezone.utc)
        signal = _rr_failed_signal("sig_low_rr", now=now, status="ready")
        self.signal_service.add_signal(signal)
        broker = _FakeRealtimeBroker()

        with (
            patch("app.api.v1.signals.signal_service", self.signal_service),
            patch("app.api.v1.signals.realtime_event_broker", broker),
        ):
            response = await confirm_signal(
                signal.id,
                ManualConfirmRequest(mode="virtual", user_id="demo_user", auto_enter_on_confirmation=True),
            )

        self.assertEqual(response.signal.status, "ready")
        self.assertEqual(response.signal.auto_entry.status if response.signal.auto_entry else None, "pending")
        self.assertIn("Auto-entry armed", response.message)

    async def test_real_confirm_signal_returns_dry_run_structured_response(self) -> None:
        signal = _real_ready_signal("sig_real_dry_run")
        self.signal_service.add_signal(signal)
        service = _FakeRealExecutionService(
            _real_execution_result(signal, status="dry_run", message="Dry-run real execution plan built.")
        )

        response = _post_real_confirm(signal.id, self.signal_service, service)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["real_execution"]["status"], "dry_run")
        self.assertEqual(payload["real_execution_result"]["status"], "dry_run")
        self.assertIn("Dry-run", payload["message"])
        self.assertEqual(service.calls, 1)

    async def test_real_confirm_signal_returns_risk_failed_structured_response(self) -> None:
        signal = _real_ready_signal("sig_real_risk_failed")
        self.signal_service.add_signal(signal)
        service = _FakeRealExecutionService(
            _real_execution_result(
                signal,
                status="risk_failed",
                execution_allowed=False,
                message="Real execution rejected by risk policy.",
            )
        )

        response = _post_real_confirm(signal.id, self.signal_service, service)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["real_execution"]["status"], "risk_failed")
        self.assertFalse(payload["real_execution"]["execution_allowed"])
        self.assertEqual(payload["real_execution_result"]["status"], "risk_failed")

    async def test_real_confirm_signal_returns_not_implemented_structured_response(self) -> None:
        signal = _real_ready_signal("sig_real_not_implemented")
        self.signal_service.add_signal(signal)
        service = _FakeRealExecutionService(
            _real_execution_result(
                signal,
                status="not_implemented",
                message="Live real execution adapter is not implemented.",
            )
        )

        response = _post_real_confirm(signal.id, self.signal_service, service)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["real_execution"]["status"], "not_implemented")
        self.assertIn("not implemented", payload["message"])

    async def test_real_confirm_signal_does_not_throw_501_after_place_order(self) -> None:
        signal = _real_ready_signal("sig_real_submitted")
        self.signal_service.add_signal(signal)
        service = _FakeRealExecutionService(
            _real_execution_result(signal, status="submitted", message="Real execution adapter submitted.")
        )

        response = _post_real_confirm(signal.id, self.signal_service, service)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["real_execution"]["status"], "submitted")
        self.assertEqual(service.calls, 1)

    async def test_real_execution_service_blocks_low_rr_as_execution_policy(self) -> None:
        now = datetime.now(timezone.utc)
        service = RealExecutionService(
            risk_audit=None,
            risk_state=None,
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=None,
            risk_settings_provider=lambda _user_id: _low_rr_real_settings(),
        )

        result = await service.place_order(
            _rr_failed_signal("sig_real_service", now=now, status="actionable"),
            ManualConfirmRequest(mode="real", user_id="demo_user", account_balance=1_000),
        )

        self.assertEqual(result.status, "risk_failed")
        self.assertTrue(result.signal_valid)
        self.assertFalse(result.execution_allowed)
        self.assertIsNotNone(result.risk_decision)
        self.assertIn("Real execution RR policy rejected", result.message)
        self.assertNotIn("signal rejected", result.message.lower())
        self.assertNotIn("invalid signal", result.message.lower())

    async def test_real_confirm_endpoint_reports_rr_execution_policy_rejection(self) -> None:
        now = datetime.now(timezone.utc)
        signal = _rr_failed_signal("sig_real_confirm", now=now, status="actionable")
        self.signal_service.add_signal(signal)
        service = RealExecutionService(
            risk_audit=None,
            risk_state=None,
            market_data_service=_FakeMarketDataService(),
            fee_rate_service=None,
            risk_settings_provider=lambda _user_id: _low_rr_real_settings(),
        )

        with (
            patch("app.api.v1.trades.signal_service", self.signal_service),
            patch("app.api.v1.trades.real_execution_service", service),
        ):
            with self.assertRaises(HTTPException) as exc:
                await confirm_real_trade(
                    RealConfirmRequest(signal_id=signal.id, user_id="demo_user", account_balance=1_000),
                )

        self.assertEqual(exc.exception.status_code, 422)
        self.assertEqual(exc.exception.detail["status"], "risk_failed")
        self.assertTrue(exc.exception.detail["signal_valid"])
        self.assertFalse(exc.exception.detail["execution_allowed"])
        self.assertIn("Real execution RR policy rejected", exc.exception.detail["message"])
        self.assertNotIn("signal rejected", exc.exception.detail["message"].lower())


def _post_real_confirm(signal_id: str, signal_service, real_execution_service) -> object:
    app = FastAPI()
    app.include_router(signals_api.router)
    with (
        patch("app.api.v1.signals.signal_service", signal_service),
        patch("app.api.v1.signals.real_execution_service", real_execution_service),
    ):
        client = TestClient(app)
        return client.post(
            f"/signals/{signal_id}/confirm",
            json={"mode": "real", "user_id": "demo_user", "account_balance": 1_000},
        )


def _real_execution_result(
    signal: RadarSignal,
    *,
    status: str,
    execution_allowed: bool = True,
    message: str,
) -> RealExecutionResult:
    return RealExecutionResult(
        status=status,
        signal_valid=True,
        execution_allowed=execution_allowed,
        exchange=signal.exchange,
        symbol=signal.symbol,
        message=message,
    )


def _real_ready_signal(signal_id: str) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=signal_id,
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        status="actionable",
        score=82,
        entry_min=100.0,
        entry_max=100.0,
        stop_loss=95.0,
        take_profit_1=105.0,
        take_profit_2=110.0,
        created_at=now,
        updated_at=now,
    )


def _low_rr_real_settings() -> RiskManagementSettings:
    return RiskManagementSettings(
        risk_profile="balanced",
        risk_per_trade_percent=1.0,
        min_rr_ratio=2.0,
        real_rr_guard_mode="hard",
        max_daily_loss_percent=3.0,
        max_account_drawdown_percent=10.0,
        max_open_risk_percent=5.0,
        spot_max_position_size_percent=100.0,
        stop_loss_mode="structure",
        tp1_r_multiple=0.5,
        tp2_r_multiple=1.0,
        tp3_r_multiple=1.5,
        real_requires_fresh_market_data=False,
        real_requires_positive_edge=False,
    )


def _rr_failed_signal(signal_id: str, *, now: datetime, status: str) -> RadarSignal:
    return RadarSignal(
        id=signal_id,
        symbol="SOL/USDT:PERP",
        exchange="bybit",
        strategy="liquidity_sweep_reversal",
        direction="short",
        confidence=0.7,
        status=status,
        score=80,
        selected_rr=0.32,
        selected_rr_target="nearest",
        min_rr_ratio=1.5,
        entry_min=100,
        entry_max=100,
        stop_loss=101,
        take_profit_1=99.68,
        take_profit_2=99.5,
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
