from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID
import unittest

from fastapi.testclient import TestClient

from app.api.v1 import trades as trades_api
from app.main import app
from app.schemas.trade import TradeJournalEntry, VirtualAccount
from app.services.strategy_testing.journal_adapter import StrategyTestJournalAdapter
from app.services.strategy_testing.schemas import StrategyTestTrade
from app.services.trade_journal_service import TradeJournalService


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
ENTRY_AT = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
EXIT_AT = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)


class StrategyTestJournalAdapterTest(unittest.TestCase):
    def test_backtest_trade_maps_to_trade_journal_entry(self) -> None:
        store = _FakeStrategyTestJournalStore([_strategy_test_trade()])
        adapter = StrategyTestJournalAdapter(store)

        entries = adapter.list_journal(tag="backtest", run_id=RUN_ID)

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.id, "strategy-test-trade-1")
        self.assertEqual(entry.user_id, str(USER_ID))
        self.assertIsNone(entry.signal_id)
        self.assertEqual(entry.mode, "virtual")
        self.assertEqual(entry.source, "backtest")
        self.assertIn("backtest", entry.tags)
        self.assertIn("research", entry.tags)
        self.assertEqual(entry.run_id, RUN_ID)
        self.assertEqual(entry.status, "closed")
        self.assertEqual(entry.result, "win")
        self.assertEqual(entry.close_reason, "take_profit")
        self.assertEqual(entry.size_usd, 1000.0)
        self.assertEqual(entry.quantity, 0.25)
        self.assertEqual(entry.risk_reward, 2.5)
        self.assertEqual(entry.opened_at, ENTRY_AT)
        self.assertEqual(entry.closed_at, EXIT_AT)

    def test_get_entry_uses_adapter_store(self) -> None:
        store = _FakeStrategyTestJournalStore([_strategy_test_trade()])
        adapter = StrategyTestJournalAdapter(store)

        entry = adapter.get_entry("strategy-test-trade-1")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.source, "backtest")
        self.assertEqual(entry.run_id, RUN_ID)


class TradeJournalApiBacktestTest(unittest.TestCase):
    def test_source_backtest_calls_adapter_without_virtual_account(self) -> None:
        fake_virtual = _FakeVirtualTradingService()
        fake_adapter = _FakeBacktestJournalAdapter([_journal_entry()])
        original_journal_service = trades_api.trade_journal_service
        original_virtual_service = trades_api.virtual_trading_service
        trades_api.trade_journal_service = TradeJournalService(
            execution_journal=fake_virtual,
            strategy_test_journal=fake_adapter,
        )
        trades_api.virtual_trading_service = fake_virtual
        client = TestClient(app)

        try:
            response = client.get(f"/api/v1/trades?source=backtest&tag=backtest&run_id={RUN_ID}")
        finally:
            trades_api.trade_journal_service = original_journal_service
            trades_api.virtual_trading_service = original_virtual_service

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["account"])
        self.assertEqual(payload["trades"][0]["source"], "backtest")
        self.assertEqual(payload["trades"][0]["tags"], ["backtest"])
        self.assertEqual(payload["trades"][0]["run_id"], str(RUN_ID))
        self.assertEqual(fake_adapter.calls, [{"run_id": RUN_ID, "tag": "backtest", "status": None, "limit": 500}])
        self.assertFalse(fake_virtual.account_called)
        self.assertFalse(fake_virtual.list_called)

    def test_mode_real_does_not_include_backtest_projection(self) -> None:
        fake_virtual = _FakeVirtualTradingService()
        fake_adapter = _FakeBacktestJournalAdapter([_journal_entry()])
        service = TradeJournalService(
            execution_journal=fake_virtual,
            strategy_test_journal=fake_adapter,
        )

        trades = service.list_journal(mode="real")

        self.assertEqual(trades, [])
        self.assertTrue(fake_virtual.list_called)
        self.assertEqual(fake_virtual.last_mode, "real")
        self.assertEqual(fake_adapter.calls, [])


class _FakeStrategyTestJournalStore:
    def __init__(self, trades: list[StrategyTestTrade]) -> None:
        self._trades = trades

    def list_journal_trades(
        self,
        *,
        run_id: UUID | None = None,
        tag: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[StrategyTestTrade]:
        _ = (run_id, tag, status, limit)
        return list(self._trades)

    def get_trade(self, trade_id: str) -> StrategyTestTrade | None:
        return next((trade for trade in self._trades if trade.trade_id == trade_id), None)


class _FakeBacktestJournalAdapter:
    def __init__(self, entries: list[TradeJournalEntry]) -> None:
        self._entries = entries
        self.calls: list[dict[str, Any]] = []

    def list_journal(
        self,
        run_id: UUID | None = None,
        tag: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[TradeJournalEntry]:
        self.calls.append({"run_id": run_id, "tag": tag, "status": status, "limit": limit})
        return list(self._entries)

    def get_entry(self, trade_id: str) -> TradeJournalEntry | None:
        return next((entry for entry in self._entries if entry.id == trade_id), None)


class _FakeVirtualTradingService:
    def __init__(self) -> None:
        self.account_called = False
        self.list_called = False
        self.last_mode: str | None = None

    def list_trade_journal(
        self,
        mode: str | None = None,
        status: str | None = None,
        signal_id: str | None = None,
    ) -> list[TradeJournalEntry]:
        _ = (mode, status, signal_id)
        self.list_called = True
        self.last_mode = mode
        return []

    def get_virtual_trade(self, trade_id: str) -> None:
        _ = trade_id
        return None

    def get_real_trade(self, trade_id: str) -> None:
        _ = trade_id
        return None

    def get_virtual_account(self, user_id: str = "demo_user") -> VirtualAccount:
        _ = user_id
        self.account_called = True
        raise AssertionError("backtest source must not request virtual account state")


def _strategy_test_trade() -> StrategyTestTrade:
    return StrategyTestTrade(
        run_id=RUN_ID,
        trade_id="strategy-test-trade-1",
        user_id=USER_ID,
        mode="research_virtual",
        strategy_code="trend_pullback_continuation",
        strategy_version="v1",
        exchange="bybit",
        symbol="BTCUSDT",
        timeframe="1h",
        direction="long",
        signal_score=82.5,
        market_regime="trend:strong:aligned",
        score_bucket="80-89",
        entry_time=ENTRY_AT,
        exit_time=EXIT_AT,
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        stop_loss=Decimal("95"),
        targets=[{"price": "110"}],
        selected_rr=2.5,
        realized_r=2.0,
        pnl=Decimal("100"),
        pnl_pct=10.0,
        fees=Decimal("1"),
        slippage=Decimal("0.5"),
        mfe_r=2.8,
        mae_r=-0.2,
        bars_to_entry=1,
        bars_in_trade=10,
        close_reason="target",
        outcome="win",
        risk_rejected=False,
        execution_rejected=False,
        warnings=[],
        features_snapshot={},
        trade_plan={"size_usd": 1000, "quantity": 0.25, "leverage": 3, "risk_percent": 1},
        tags=["research"],
        created_at=CREATED_AT,
    )


def _journal_entry() -> TradeJournalEntry:
    return TradeJournalEntry(
        id="strategy-test-trade-1",
        user_id=str(USER_ID),
        signal_id=None,
        mode="virtual",
        source="backtest",
        tags=["backtest"],
        run_id=RUN_ID,
        exchange="bybit",
        symbol="BTCUSDT",
        strategy="trend_pullback_continuation",
        timeframe="1h",
        side="long",
        entry_price=100.0,
        current_price=110.0,
        exit_price=110.0,
        size_usd=1000.0,
        quantity=0.25,
        leverage=3,
        risk_percent=1.0,
        stop_loss=95.0,
        take_profit=[110.0],
        status="closed",
        result="win",
        close_reason="take_profit",
        pnl=100.0,
        pnl_percent=10.0,
        opened_at=ENTRY_AT,
        updated_at=EXIT_AT,
        closed_at=EXIT_AT,
    )


if __name__ == "__main__":
    unittest.main()
