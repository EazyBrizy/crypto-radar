import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.api.v1.signals import list_active_signals, list_open_signals
from app.schemas.signal import RadarSignal
from backend.tests.ephemeral_signal_service import ephemeral_signal_service


class SignalApiContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.signal_service = ephemeral_signal_service()

    async def asyncTearDown(self) -> None:
        self.signal_service = None

    async def test_active_signals_endpoint_returns_only_active_snapshot(self) -> None:
        now = datetime.now(timezone.utc)
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_active",
                symbol="BTC/USDT:PERP",
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

        self.assertEqual([signal.id for signal in signals], ["sig_active"])

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
                id="sig_new",
                symbol="BTC/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="long",
                confidence=0.62,
                status="new",
                score=62,
                created_at=now,
                updated_at=now,
            )
        )
        self.signal_service.add_signal(
            RadarSignal(
                id="sig_active",
                symbol="ETH/USDT:PERP",
                exchange="bybit",
                strategy="test",
                direction="short",
                confidence=0.82,
                status="active",
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

        self.assertEqual([signal.id for signal in signals], ["sig_new", "sig_active"])


if __name__ == "__main__":
    unittest.main()
