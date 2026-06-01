import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException

from app.api.v1.signals import confirm_signal, list_active_signals, list_open_signals
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest
from backend.tests.ephemeral_signal_service import ephemeral_signal_service


class _FakeRealtimeBroker:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


class SignalApiContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.signal_service = ephemeral_signal_service()

    async def asyncTearDown(self) -> None:
        self.signal_service = None

    async def test_active_signals_endpoint_returns_only_active_snapshot(self) -> None:
        now = datetime.now(timezone.utc)
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
                status="active",
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
                status="active",
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

    async def test_confirm_endpoint_rejects_auto_entry_when_strategy_rr_failed(self) -> None:
        now = datetime.now(timezone.utc)
        signal = RadarSignal(
            id="sig_low_rr",
            symbol="SOL/USDT:PERP",
            exchange="bybit",
            strategy="liquidity_sweep_reversal",
            direction="short",
            confidence=0.7,
            status="ready",
            score=70,
            selected_rr=0.32,
            selected_rr_target="nearest",
            min_rr_ratio=1.5,
            created_at=now,
            updated_at=now,
        )
        self.signal_service.add_signal(signal)

        with patch("app.api.v1.signals.signal_service", self.signal_service):
            with self.assertRaises(HTTPException) as exc:
                await confirm_signal(
                    signal.id,
                    ManualConfirmRequest(mode="virtual", user_id="demo_user", auto_enter_on_confirmation=True),
                )

        self.assertEqual(exc.exception.status_code, 409)
        self.assertIn("Risk/reward blocked", str(exc.exception.detail))


if __name__ == "__main__":
    unittest.main()
