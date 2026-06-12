from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.schemas.trade import VirtualTrade, VirtualTradeTargetState
from app.services.position_management import PositionManagementEngine


class PositionManagementEngineTest(unittest.TestCase):
    def test_apply_price_partially_closes_first_target_with_reason_code(self) -> None:
        now = datetime.now(timezone.utc)
        trade = _trade(now)

        result = PositionManagementEngine().apply_price(trade, price=110.0, now=now)

        self.assertEqual(result.reason_code, "partial_take_profit")
        self.assertFalse(result.closed)
        self.assertEqual(result.trade.status, "partially_closed")
        self.assertAlmostEqual(result.trade.remaining_quantity or 0.0, 0.5)
        self.assertAlmostEqual(result.trade.realized_pnl, 5.0)


def _trade(now: datetime) -> VirtualTrade:
    return VirtualTrade(
        id="pm_trade",
        user_id="demo_user",
        signal_id="pm_signal",
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        timeframe="15m",
        side="long",
        entry_price=100.0,
        current_price=100.0,
        size_usd=100.0,
        quantity=1.0,
        leverage=1,
        risk_percent=1.0,
        risk_amount=10.0,
        stop_loss=95.0,
        take_profit=[110.0, 120.0],
        target_states=[
            VirtualTradeTargetState(
                label="TP1",
                price=110.0,
                close_percent=50.0,
                action="partial_close",
            ),
            VirtualTradeTargetState(
                label="TP2",
                price=120.0,
                close_percent=100.0,
                action="full_close",
            ),
        ],
        opened_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
