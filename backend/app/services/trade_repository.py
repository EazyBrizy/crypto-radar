from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.trade import TradeJournalRecord
from app.schemas.trade import RealTrade, TradeJournalEntry, VirtualTrade


class TradeRepository(Protocol):
    def save_virtual_trade(self, trade: VirtualTrade) -> VirtualTrade:
        ...

    def get_virtual_trade(self, trade_id: str) -> Optional[VirtualTrade]:
        ...

    def list_virtual_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[VirtualTrade]:
        ...

    def delete_virtual_trade(self, trade_id: str) -> None:
        ...

    def save_real_trade(self, trade: RealTrade) -> RealTrade:
        ...

    def get_real_trade(self, trade_id: str) -> Optional[RealTrade]:
        ...

    def list_real_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[RealTrade]:
        ...

    def list_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        ...


class InMemoryTradeRepository:
    """Временный repository для MVP, повторяет будущий контракт PostgreSQL."""

    def __init__(self) -> None:
        self._virtual_trades: dict[str, VirtualTrade] = {}
        self._real_trades: dict[str, RealTrade] = {}

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
        self._real_trades[trade.id] = trade
        return trade

    def get_real_trade(self, trade_id: str) -> Optional[RealTrade]:
        return self._real_trades.get(trade_id)

    def list_real_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[RealTrade]:
        trades = list(self._real_trades.values())
        if status is not None:
            trades = [trade for trade in trades if trade.status == status]
        if signal_id is not None:
            trades = [trade for trade in trades if trade.signal_id == signal_id]
        return sorted(trades, key=lambda trade: trade.opened_at, reverse=True)

    def list_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        trades: list[TradeJournalEntry] = []
        if mode in {None, "virtual"}:
            trades.extend(
                self._to_journal_entry(trade)
                for trade in self.list_virtual_trades(status=status, signal_id=signal_id)
            )
        if mode in {None, "real"}:
            trades.extend(
                TradeJournalEntry.model_validate(trade.model_dump())
                for trade in self.list_real_trades(status=status, signal_id=signal_id)
            )
        return sorted(trades, key=lambda trade: trade.opened_at, reverse=True)

    @staticmethod
    def _to_journal_entry(trade: VirtualTrade) -> TradeJournalEntry:
        return TradeJournalEntry.model_validate(trade.model_dump())


class SqlAlchemyTradeRepository:
    """PostgreSQL-ready repository для будущей постоянной записи журнала."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_virtual_trade(self, trade: VirtualTrade) -> VirtualTrade:
        self._upsert_record(TradeJournalEntry.model_validate(trade.model_dump()))
        return trade

    def get_virtual_trade(self, trade_id: str) -> Optional[VirtualTrade]:
        record = self._get_record(trade_id, mode="virtual")
        if record is None:
            return None
        return VirtualTrade.model_validate(self._record_to_dict(record))

    def list_virtual_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[VirtualTrade]:
        return [
            VirtualTrade.model_validate(self._record_to_dict(record))
            for record in self._list_records(
                mode="virtual",
                status=status,
                signal_id=signal_id,
            )
        ]

    def delete_virtual_trade(self, trade_id: str) -> None:
        with self._session_factory() as session:
            record = session.get(TradeJournalRecord, trade_id)
            if record is not None and record.mode == "virtual":
                session.delete(record)
                session.commit()

    def save_real_trade(self, trade: RealTrade) -> RealTrade:
        self._upsert_record(TradeJournalEntry.model_validate(trade.model_dump()))
        return trade

    def get_real_trade(self, trade_id: str) -> Optional[RealTrade]:
        record = self._get_record(trade_id, mode="real")
        if record is None:
            return None
        data = self._record_to_dict(record)
        return RealTrade.model_validate(data)

    def list_real_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[RealTrade]:
        return [
            RealTrade.model_validate(self._record_to_dict(record))
            for record in self._list_records(
                mode="real",
                status=status,
                signal_id=signal_id,
            )
        ]

    def list_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        return [
            TradeJournalEntry.model_validate(self._record_to_dict(record))
            for record in self._list_records(
                mode=mode,
                status=status,
                signal_id=signal_id,
            )
        ]

    def _upsert_record(self, trade: TradeJournalEntry) -> None:
        with self._session_factory() as session:
            record = session.get(TradeJournalRecord, trade.id)
            data = trade.model_dump()
            if record is None:
                session.add(TradeJournalRecord(**data))
            else:
                for key, value in data.items():
                    setattr(record, key, value)
            session.commit()

    def _get_record(
        self,
        trade_id: str,
        mode: Optional[str] = None,
    ) -> Optional[TradeJournalRecord]:
        with self._session_factory() as session:
            record = session.get(TradeJournalRecord, trade_id)
            if record is None:
                return None
            if mode is not None and record.mode != mode:
                return None
            session.expunge(record)
            return record

    def _list_records(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalRecord]:
        statement = select(TradeJournalRecord)
        if mode is not None:
            statement = statement.where(TradeJournalRecord.mode == mode)
        if status is not None:
            statement = statement.where(TradeJournalRecord.status == status)
        if signal_id is not None:
            statement = statement.where(TradeJournalRecord.signal_id == signal_id)
        statement = statement.order_by(TradeJournalRecord.opened_at.desc())

        with self._session_factory() as session:
            records = list(session.scalars(statement).all())
            for record in records:
                session.expunge(record)
            return records

    @staticmethod
    def _record_to_dict(record: TradeJournalRecord) -> dict[str, object]:
        return {
            "id": record.id,
            "user_id": record.user_id,
            "signal_id": record.signal_id,
            "mode": record.mode,
            "exchange": record.exchange,
            "symbol": record.symbol,
            "strategy": record.strategy,
            "timeframe": record.timeframe,
            "side": record.side,
            "entry_price": record.entry_price,
            "current_price": record.current_price,
            "exit_price": record.exit_price,
            "size_usd": record.size_usd,
            "quantity": record.quantity,
            "leverage": record.leverage,
            "risk_percent": record.risk_percent,
            "stop_loss": record.stop_loss,
            "take_profit": record.take_profit,
            "fees": record.fees,
            "slippage_bps": record.slippage_bps,
            "status": record.status,
            "result": record.result,
            "close_reason": record.close_reason,
            "pnl": record.pnl,
            "pnl_percent": record.pnl_percent,
            "mfe": record.mfe,
            "mae": record.mae,
            "screenshots": record.screenshots,
            "ai_review": record.ai_review,
            "opened_at": record.opened_at,
            "updated_at": record.updated_at,
            "closed_at": record.closed_at,
        }
