from __future__ import annotations

from typing import Optional, Protocol
from uuid import UUID

from app.schemas.trade import TradeJournalEntry, VirtualAccount, VirtualTrade
from app.services.strategy_testing.journal_adapter import StrategyTestJournalAdapter
from app.services.virtual_trading import virtual_trading_service


class ExecutionJournalService(Protocol):
    def list_trade_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        ...

    def get_virtual_trade(self, trade_id: str) -> VirtualTrade | None:
        ...

    def get_real_trade(self, trade_id: str) -> TradeJournalEntry | None:
        ...

    def get_virtual_account(self, user_id: str = "demo_user") -> VirtualAccount:
        ...


class BacktestJournalAdapter(Protocol):
    def list_journal(
        self,
        run_id: UUID | None = None,
        tag: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[TradeJournalEntry]:
        ...

    def get_entry(self, trade_id: str) -> TradeJournalEntry | None:
        ...


class TradeJournalService:
    def __init__(
        self,
        execution_journal: ExecutionJournalService | None = None,
        strategy_test_journal: BacktestJournalAdapter | None = None,
    ) -> None:
        self._execution_journal = execution_journal or virtual_trading_service
        self._strategy_test_journal = strategy_test_journal or StrategyTestJournalAdapter()

    def list_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
        source: Optional[str] = None,
        tag: Optional[str] = None,
        run_id: UUID | None = None,
    ) -> list[TradeJournalEntry]:
        trades: list[TradeJournalEntry] = []
        if self._include_execution_source(source, tag=tag, run_id=run_id):
            trades.extend(
                self._execution_journal.list_trade_journal(
                    mode=self._execution_mode_filter(source, mode),
                    status=status,
                    signal_id=signal_id,
                )
            )
        if self._include_backtest_source(
            source,
            mode=mode,
            signal_id=signal_id,
            tag=tag,
            run_id=run_id,
        ):
            trades.extend(
                self._strategy_test_journal.list_journal(
                    run_id=run_id,
                    tag=tag,
                    status=status,
                )
            )
        return sorted(trades, key=lambda trade: trade.opened_at, reverse=True)

    def get_entry(self, trade_id: str) -> TradeJournalEntry | None:
        virtual_trade = self._execution_journal.get_virtual_trade(trade_id)
        if virtual_trade is not None:
            return TradeJournalEntry.model_validate(virtual_trade.model_dump())

        real_trade = self._execution_journal.get_real_trade(trade_id)
        if real_trade is not None:
            return real_trade

        return self._strategy_test_journal.get_entry(trade_id)

    @staticmethod
    def _include_execution_source(
        source: Optional[str],
        *,
        tag: Optional[str],
        run_id: UUID | None,
    ) -> bool:
        if source == "backtest":
            return False
        if tag is not None or run_id is not None:
            return False
        return source in {None, "virtual", "real"}

    @staticmethod
    def _include_backtest_source(
        source: Optional[str],
        *,
        mode: Optional[str],
        signal_id: Optional[str],
        tag: Optional[str],
        run_id: UUID | None,
    ) -> bool:
        if signal_id is not None:
            return False
        if mode == "real":
            return False
        if source == "backtest":
            return True
        if source in {"virtual", "real"}:
            return False
        return tag is not None or run_id is not None

    @staticmethod
    def _execution_mode_filter(source: Optional[str], mode: Optional[str]) -> Optional[str]:
        if source in {"virtual", "real"}:
            return source
        return mode


trade_journal_service = TradeJournalService()
