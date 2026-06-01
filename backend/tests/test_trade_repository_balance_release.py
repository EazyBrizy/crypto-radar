import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.trade import VirtualTradeLifecycleEvent
from app.services.trade_repository import _close_order_quantity, _release_risk_balance


class CapturingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


class TradeRepositoryBalanceReleaseTest(unittest.TestCase):
    def test_release_legacy_unlocked_position_applies_only_pnl(self) -> None:
        session = CapturingSession()
        balance = SimpleNamespace(available=Decimal("100"), locked=Decimal("0"), updated_at=None)

        _release_risk_balance(
            session=session,
            balance=balance,
            portfolio=SimpleNamespace(id=uuid4()),
            asset=SimpleNamespace(id=uuid4()),
            risk_amount=Decimal("25"),
            pnl=Decimal("-2.50"),
            position_id=uuid4(),
            now=datetime.now(timezone.utc),
        )

        self.assertEqual(balance.available, Decimal("97.50"))
        self.assertEqual(balance.locked, Decimal("0"))
        self.assertEqual(session.added[0].delta_available, Decimal("-2.50"))
        self.assertEqual(session.added[0].delta_locked, Decimal("0"))

    def test_release_reserved_position_unlocks_only_available_locked_amount(self) -> None:
        session = CapturingSession()
        balance = SimpleNamespace(available=Decimal("75"), locked=Decimal("25"), updated_at=None)

        _release_risk_balance(
            session=session,
            balance=balance,
            portfolio=SimpleNamespace(id=uuid4()),
            asset=SimpleNamespace(id=uuid4()),
            risk_amount=Decimal("25"),
            pnl=Decimal("5"),
            position_id=uuid4(),
            now=datetime.now(timezone.utc),
        )

        self.assertEqual(balance.available, Decimal("105"))
        self.assertEqual(balance.locked, Decimal("0"))
        self.assertEqual(session.added[0].delta_available, Decimal("30"))
        self.assertEqual(session.added[0].delta_locked, Decimal("-25"))

    def test_close_order_quantity_uses_final_lifecycle_event_quantity(self) -> None:
        trade = SimpleNamespace(
            lifecycle_events=[
                VirtualTradeLifecycleEvent(
                    event_type="partial_take_profit",
                    reason="partial_take_profit",
                    quantity=Decimal("0.30"),
                    created_at=datetime.now(timezone.utc),
                ),
                VirtualTradeLifecycleEvent(
                    event_type="take_profit",
                    reason="take_profit",
                    quantity=Decimal("0.70"),
                    created_at=datetime.now(timezone.utc),
                ),
            ]
        )

        self.assertEqual(_close_order_quantity(trade, Decimal("1.00")), Decimal("0.7"))


if __name__ == "__main__":
    unittest.main()
