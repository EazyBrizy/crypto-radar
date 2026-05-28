import unittest
from datetime import datetime, timezone
from typing import Optional

from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, RealTrade, TradeJournalEntry, VirtualTrade
from app.services.trade_service import TradeService


class EphemeralTradeRepository:
    def __init__(self) -> None:
        self._virtual_trades: dict[str, VirtualTrade] = {}

    def save_virtual_trade(self, trade: VirtualTrade) -> VirtualTrade:
        self._virtual_trades[trade.id] = trade
        return trade

    def get_virtual_trade(self, trade_id: str) -> Optional[VirtualTrade]:
        return self._virtual_trades.get(trade_id)

    def list_virtual_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
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

    def get_real_trade(self, trade_id: str) -> Optional[RealTrade]:
        return None

    def list_real_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[RealTrade]:
        return []

    def list_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        if mode == "real":
            return []
        return [
            TradeJournalEntry.model_validate(trade.model_dump())
            for trade in self.list_virtual_trades(status=status, signal_id=signal_id)
        ]


class VirtualTradeLifecycleTest(unittest.TestCase):
    def test_long_position_closes_on_take_profit_and_updates_account(self) -> None:
        service = TradeService(repository=EphemeralTradeRepository())
        trade = service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(),
        )

        self.assertEqual(trade.risk_amount, 10.0)
        self.assertEqual(trade.take_profit, [130.0])

        updated = service.update_market_price("bybit", "BTCUSDT", 130.0)

        self.assertEqual(updated[0].status, "closed")
        self.assertEqual(updated[0].close_reason, "take_profit")
        self.assertAlmostEqual(updated[0].pnl or 0.0, 30.0)

        account = service.get_virtual_account()
        self.assertAlmostEqual(account.balance, 130.0)
        self.assertAlmostEqual(account.realized_pnl, 30.0)
        self.assertEqual(account.wins, 1)

    def test_long_position_closes_on_stop_loss_and_updates_account(self) -> None:
        service = TradeService(repository=EphemeralTradeRepository())
        service.open_virtual_trade(
            self._signal(direction="long", stop_loss=90.0),
            ManualConfirmRequest(),
        )

        updated = service.update_market_price("bybit", "BTCUSDT", 90.0)

        self.assertEqual(updated[0].status, "closed")
        self.assertEqual(updated[0].close_reason, "stop_loss")
        self.assertAlmostEqual(updated[0].pnl or 0.0, -10.0)

        account = service.get_virtual_account()
        self.assertAlmostEqual(account.balance, 90.0)
        self.assertAlmostEqual(account.realized_pnl, -10.0)
        self.assertEqual(account.losses, 1)

    @staticmethod
    def _signal(direction: str, stop_loss: float) -> RadarSignal:
        now = datetime.now(timezone.utc)
        return RadarSignal(
            id=f"sig_{direction}",
            symbol="BTCUSDT",
            exchange="bybit",
            strategy="trend_pullback_continuation",
            direction=direction,
            confidence=0.8,
            risk_reward=3.0,
            urgency="medium",
            score=78,
            timeframe="15m",
            entry_min=100.0,
            entry_max=100.0,
            stop_loss=stop_loss,
            take_profit_1=120.0,
            take_profit_2=130.0,
            explanation=[],
            risks=[],
            created_at=now,
            updated_at=now,
        )


if __name__ == "__main__":
    unittest.main()
