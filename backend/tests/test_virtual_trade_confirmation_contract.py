import unittest
from datetime import datetime, timezone
from uuid import UUID

from app.repositories.signal_repository import SignalWriteResult
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, VirtualAccount, VirtualTrade
from app.services.trade_repository import (
    VirtualTradeConfirmationResult,
    VirtualTradePersistenceEvent,
)
from app.services.trade_service import TradeService


class FakeConfirmRepository:
    def __init__(self) -> None:
        self.received_trade: VirtualTrade | None = None

    def list_virtual_trades(self, status=None, signal_id=None):
        return []

    def get_virtual_trade(self, trade_id):
        return None

    def list_real_trades(self, status=None, signal_id=None):
        return []

    def get_real_trade(self, trade_id):
        return None

    def list_journal(self, mode=None, status=None, signal_id=None):
        return []

    def get_virtual_account(self, user_id: str = "demo_user") -> VirtualAccount:
        return VirtualAccount(
            user_id=user_id,
            balance=100,
            equity=100,
            updated_at=datetime.now(timezone.utc),
        )

    def confirm_signal_with_trade(
        self,
        signal_id: str,
        request: ManualConfirmRequest,
        trade: VirtualTrade,
    ) -> VirtualTradeConfirmationResult:
        self.received_trade = trade
        persisted_trade = trade.model_copy(
            update={"id": "2a25701d-35ee-44e3-bff1-48d510735a27"}
        )
        confirmed_signal = _signal().model_copy(
            update={
                "status": "confirmed",
                "confirmed_trade_id": persisted_trade.id,
            }
        )
        signal_result = SignalWriteResult(
            signal=confirmed_signal,
            created=False,
            event_type="signal.confirmed",
            analytics_event={"event_type": "signal.confirmed"},
        )
        event = VirtualTradePersistenceEvent(
            event_type="virtual_trade.opened",
            trade=persisted_trade,
            user_id=UUID("ba520631-d035-4f95-a4c0-3b40553dd524"),
            portfolio_id=UUID("ba520631-d035-4f95-a4c0-3b40553dd525"),
            order_id=UUID("ba520631-d035-4f95-a4c0-3b40553dd526"),
            position_id=UUID(persisted_trade.id),
            signal_id=UUID("ba520631-d035-4f95-a4c0-3b40553dd527"),
        )
        return VirtualTradeConfirmationResult(signal_result, persisted_trade, [event])


class FakeSignalAnalyticsWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def write_event(self, event: dict[str, object]) -> None:
        self.events.append(event)


class FakeSignalHotStore:
    def __init__(self) -> None:
        self.results: list[SignalWriteResult] = []

    def write_signal(self, result: SignalWriteResult) -> None:
        self.results.append(result)


class VirtualTradeConfirmationContractTest(unittest.TestCase):
    def test_confirm_signal_uses_repository_boundary_and_signal_side_effects(self) -> None:
        repository = FakeConfirmRepository()
        analytics = FakeSignalAnalyticsWriter()
        hot_store = FakeSignalHotStore()
        service = TradeService(
            repository=repository,
            signal_analytics_writer=analytics,
            signal_hot_store=hot_store,
        )

        signal, trade = service.confirm_signal(_signal(), ManualConfirmRequest())

        self.assertEqual(signal.status, "confirmed")
        self.assertEqual(signal.confirmed_trade_id, trade.id)
        self.assertIsNotNone(repository.received_trade)
        self.assertEqual(repository.received_trade.signal_id, _signal().id)
        self.assertEqual(analytics.events, [{"event_type": "signal.confirmed"}])
        self.assertEqual(hot_store.results[0].signal.id, signal.id)


def _signal() -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id="ba520631-d035-4f95-a4c0-3b40553dd527",
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=0.82,
        risk_reward=3.0,
        score=82,
        timeframe="15m",
        entry_min=100,
        entry_max=100,
        stop_loss=90,
        take_profit_1=120,
        take_profit_2=130,
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
