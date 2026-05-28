from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Protocol
from typing import Optional
from uuid import uuid4

from app.core.clickhouse_client import get_clickhouse_client
from app.core.redis_client import get_redis_client
from app.repositories.signal_repository import SignalWriteResult
from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    CloseReason,
    CloseVirtualTradeRequest,
    ManualConfirmRequest,
    TradeResult,
    TradeJournalEntry,
    VirtualAccount,
    VirtualExecutionReport,
    VirtualTrade,
)
from app.services.signal_service import ClickHouseSignalAnalyticsWriter, RedisSignalHotStore
from app.services.trade_repository import (
    PostgresVirtualTradeRepository,
    TradeRepository,
    VirtualTradeConfirmationResult,
    VirtualTradePersistenceEvent,
)
from app.services.virtual_execution_engine import VirtualExecutionEngine, VirtualExecutionRejected

logger = logging.getLogger(__name__)
MAX_STORED_TRADES = 500
VIRTUAL_STARTING_BALANCE = 100.0
VIRTUAL_RISK_PER_TRADE = 10.0
VIRTUAL_RISK_REWARD = 3.0


@dataclass(frozen=True)
class _VirtualEntrySimulation:
    execution: VirtualExecutionReport
    account: VirtualAccount
    side: str
    stop_loss: float


class SignalWriteSideEffect(Protocol):
    def write_event(self, event: dict[str, Any]) -> None:
        ...


class SignalHotSideEffect(Protocol):
    def write_signal(self, result: SignalWriteResult) -> None:
        ...


class TradeService:
    """Stores and updates virtual trades through the configured repository."""

    def __init__(
        self,
        repository: TradeRepository | None = None,
        signal_analytics_writer: SignalWriteSideEffect | None = None,
        signal_hot_store: SignalHotSideEffect | None = None,
        execution_engine: VirtualExecutionEngine | None = None,
    ) -> None:
        self._repository = repository or PostgresVirtualTradeRepository()
        self._signal_analytics_writer = signal_analytics_writer or ClickHouseSignalAnalyticsWriter()
        self._signal_hot_store = signal_hot_store or RedisSignalHotStore()
        self._execution_engine = execution_engine or VirtualExecutionEngine()
        self._trade_by_signal: dict[str, str] = {}
        self._account_balance_by_user: dict[str, float] = {}
        self._realized_pnl_by_user: dict[str, float] = {}
        self._account_stats_by_user: dict[str, dict[str, int]] = {}

    def list_virtual_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[VirtualTrade]:
        return self._repository.list_virtual_trades(
            status=status,
            signal_id=signal_id,
        )

    def get_virtual_trade(self, trade_id: str) -> Optional[VirtualTrade]:
        return self._repository.get_virtual_trade(trade_id)

    def list_real_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        return [
            TradeJournalEntry.model_validate(trade.model_dump())
            for trade in self._repository.list_real_trades(
                status=status,
                signal_id=signal_id,
            )
        ]

    def get_real_trade(self, trade_id: str) -> Optional[TradeJournalEntry]:
        trade = self._repository.get_real_trade(trade_id)
        if trade is None:
            return None
        return TradeJournalEntry.model_validate(trade.model_dump())

    def list_trade_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        return self._repository.list_journal(
            mode=mode,
            status=status,
            signal_id=signal_id,
        )

    def get_virtual_account(self, user_id: str = "demo_user") -> VirtualAccount:
        repository_account = getattr(self._repository, "get_virtual_account", None)
        if repository_account is not None:
            return repository_account(user_id)

        balance = self._account_balance_by_user.setdefault(
            user_id,
            VIRTUAL_STARTING_BALANCE,
        )
        realized_pnl = self._realized_pnl_by_user.setdefault(user_id, 0.0)
        stats = self._account_stats_by_user.setdefault(
            user_id,
            {
                "closed_trades": 0,
                "wins": 0,
                "losses": 0,
                "breakeven": 0,
            },
        )
        open_trades = [
            trade
            for trade in self._repository.list_virtual_trades(status="open")
            if trade.user_id == user_id and trade.status == "open"
        ]
        unrealized_pnl = sum(
            self._gross_pnl(trade, trade.current_price)
            for trade in open_trades
        )
        updated_at = max(
            (trade.updated_at for trade in open_trades),
            default=datetime.now(timezone.utc),
        )
        return VirtualAccount(
            user_id=user_id,
            starting_balance=VIRTUAL_STARTING_BALANCE,
            balance=balance,
            equity=balance + unrealized_pnl,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            risk_per_trade=VIRTUAL_RISK_PER_TRADE,
            risk_reward=VIRTUAL_RISK_REWARD,
            open_positions=len(open_trades),
            closed_trades=stats["closed_trades"],
            wins=stats["wins"],
            losses=stats["losses"],
            breakeven=stats["breakeven"],
            updated_at=updated_at,
        )

    def get_virtual_trade_by_signal(self, signal_id: str) -> Optional[VirtualTrade]:
        trade_id = self._trade_by_signal.get(signal_id)
        if trade_id is not None:
            trade = self.get_virtual_trade(trade_id)
            if trade is not None:
                return trade
        trades = self._repository.list_virtual_trades(signal_id=signal_id)
        return trades[0] if trades else None

    def preview_virtual_execution(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> VirtualExecutionReport:
        return self._simulate_entry_execution(
            signal=signal,
            request=request,
            enforce_position_limit=False,
        ).execution

    def confirm_signal(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> tuple[RadarSignal, VirtualTrade]:
        confirm_with_trade = getattr(self._repository, "confirm_signal_with_trade", None)
        existing = self.get_virtual_trade_by_signal(signal.id)
        if existing is not None and confirm_with_trade is not None and signal.status != "confirmed":
            result: VirtualTradeConfirmationResult = confirm_with_trade(signal.id, request, existing)
            self._trade_by_signal[signal.id] = result.trade.id
            self._after_signal_write(result.signal_result)
            self._after_virtual_trade_events(result.events)
            return result.signal_result.signal, result.trade
        if existing is not None:
            updated_signal = signal.model_copy(
                update={
                    "status": "confirmed",
                    "confirmed_at": datetime.now(timezone.utc),
                    "decision_mode": request.mode,
                    "decision_note": "Пользователь подтвердил сигнал в virtual mode",
                    "confirmed_trade_id": existing.id,
                }
            )
            return updated_signal, existing

        trade = self._build_virtual_trade(signal, request)
        if confirm_with_trade is None:
            persisted_trade = self._repository.save_virtual_trade(trade)
            self._trade_by_signal[signal.id] = persisted_trade.id
            updated_signal = signal.model_copy(
                update={
                    "status": "confirmed",
                    "confirmed_at": datetime.now(timezone.utc),
                    "decision_mode": request.mode,
                    "decision_note": "Пользователь подтвердил сигнал в virtual mode",
                    "confirmed_trade_id": persisted_trade.id,
                }
            )
            return updated_signal, persisted_trade

        result: VirtualTradeConfirmationResult = confirm_with_trade(signal.id, request, trade)
        self._trade_by_signal[signal.id] = result.trade.id
        self._after_signal_write(result.signal_result)
        self._after_virtual_trade_events(result.events)
        return result.signal_result.signal, result.trade

    def open_virtual_trade(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> VirtualTrade:
        existing = self.get_virtual_trade_by_signal(signal.id)
        if existing is not None:
            return existing
        trade = self._build_virtual_trade(signal, request)
        persisted_trade = self._repository.save_virtual_trade(trade)
        self._trade_by_signal[signal.id] = persisted_trade.id
        self._after_virtual_trade_events(self._consume_repository_events())
        self._trim_trades()
        return persisted_trade

    def _build_virtual_trade(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> VirtualTrade:
        open_user_positions = [
            trade
            for trade in self._repository.list_virtual_trades(status="open")
            if trade.user_id == request.user_id and trade.status == "open"
        ]
        if len(open_user_positions) >= request.max_open_positions:
            raise ValueError("Достигнут лимит открытых виртуальных позиций")

        raw_entry = self._entry_price(signal)
        if signal.stop_loss is None:
            raise ValueError("У сигнала нет stop_loss для расчета риска")

        account = self.get_virtual_account(request.user_id)
        risk_amount = min(VIRTUAL_RISK_PER_TRADE, max(account.balance, 0.0))
        if risk_amount <= 0:
            raise ValueError("Virtual account balance is depleted")

        side = signal.direction
        stop_loss = signal.stop_loss
        if not self._stop_matches_side(raw_entry, stop_loss, side):
            stop_loss = self._fallback_stop(raw_entry, side)
        raw_risk_per_unit = abs(raw_entry - stop_loss)
        if raw_risk_per_unit <= 0:
            raise ValueError("Некорректная дистанция до stop_loss")

        risk_sized_usd = risk_amount / raw_risk_per_unit * raw_entry
        requested_size_usd = request.size_usd or risk_sized_usd
        execution = self._execution_engine.simulate_entry(
            signal=signal,
            request=request,
            reference_price=raw_entry,
            requested_size_usd=requested_size_usd,
        )
        if execution.status == "rejected_virtual_execution" or execution.average_price is None:
            raise VirtualExecutionRejected(execution)

        entry_price = execution.average_price
        if not self._stop_matches_side(entry_price, stop_loss, side):
            stop_loss = self._fallback_stop(entry_price, side)
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            raise ValueError("Некорректная дистанция до stop_loss")

        size_usd = execution.filled_size_usd
        if size_usd <= 0:
            raise VirtualExecutionRejected(execution)
        quantity = size_usd / entry_price
        risk_amount = risk_per_unit * quantity
        entry_fee = size_usd * request.fee_rate
        effective_risk_percent = (
            risk_amount / account.balance * 100
            if account.balance > 0
            else request.risk_percent
        )
        take_profit = self._take_profit(entry_price, risk_per_unit, side)
        now = datetime.now(timezone.utc)

        trade = VirtualTrade(
            id=f"vtr_{uuid4().hex[:12]}",
            user_id=request.user_id,
            signal_id=signal.id,
            exchange=signal.exchange,
            symbol=signal.symbol,
            strategy=signal.strategy,
            timeframe=signal.timeframe,
            side=side,
            entry_price=entry_price,
            current_price=entry_price,
            size_usd=size_usd,
            quantity=quantity,
            leverage=request.leverage,
            risk_percent=effective_risk_percent,
            risk_amount=risk_amount,
            risk_reward=VIRTUAL_RISK_REWARD,
            stop_loss=stop_loss,
            take_profit=[take_profit],
            fees=entry_fee,
            slippage_bps=execution.entry_slippage_bps,
            simulation_mode=execution.mode,
            execution_status=execution.status,
            requested_size_usd=execution.requested_size_usd,
            filled_size_usd=execution.filled_size_usd,
            unfilled_size_usd=execution.unfilled_size_usd,
            execution=execution,
            opened_at=now,
            updated_at=now,
        )
        return trade

    def _simulate_entry_execution(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        enforce_position_limit: bool,
    ) -> _VirtualEntrySimulation:
        if enforce_position_limit:
            open_user_positions = [
                trade
                for trade in self._repository.list_virtual_trades(status="open")
                if trade.user_id == request.user_id and trade.status == "open"
            ]
            if len(open_user_positions) >= request.max_open_positions:
                raise ValueError("Maximum open virtual positions limit reached")

        raw_entry = self._entry_price(signal)
        if signal.stop_loss is None:
            raise ValueError("Signal has no stop_loss for virtual risk calculation")

        account = self.get_virtual_account(request.user_id)
        risk_amount = min(VIRTUAL_RISK_PER_TRADE, max(account.balance, 0.0))
        if risk_amount <= 0:
            raise ValueError("Virtual account balance is depleted")

        side = signal.direction
        stop_loss = signal.stop_loss
        if not self._stop_matches_side(raw_entry, stop_loss, side):
            stop_loss = self._fallback_stop(raw_entry, side)
        raw_risk_per_unit = abs(raw_entry - stop_loss)
        if raw_risk_per_unit <= 0:
            raise ValueError("Invalid distance to stop_loss")

        risk_sized_usd = risk_amount / raw_risk_per_unit * raw_entry
        requested_size_usd = request.size_usd or risk_sized_usd
        execution = self._execution_engine.simulate_entry(
            signal=signal,
            request=request,
            reference_price=raw_entry,
            requested_size_usd=requested_size_usd,
        )
        return _VirtualEntrySimulation(
            execution=execution,
            account=account,
            side=side,
            stop_loss=stop_loss,
        )

    def close_virtual_trade(
        self,
        trade_id: str,
        request: CloseVirtualTradeRequest,
    ) -> Optional[VirtualTrade]:
        trade = self.get_virtual_trade(trade_id)
        if trade is None:
            return None
        exit_price = request.exit_price or trade.current_price
        return self._close_trade(trade, exit_price, request.reason)

    def update_market_price(
        self,
        exchange: str,
        symbol: str,
        price: float,
    ) -> list[VirtualTrade]:
        updated: list[VirtualTrade] = []
        for trade in self._repository.list_virtual_trades(status="open"):
            if trade.status != "open":
                continue
            if trade.exchange != exchange or trade.symbol != symbol:
                continue

            updated_trade = self._mark_price(trade, price)
            close_target = self._close_target(updated_trade, price)
            if close_target is not None:
                exit_price, reason = close_target
                updated_trade = self._close_trade(updated_trade, exit_price, reason)
            updated.append(updated_trade)
        return updated

    def _mark_price(self, trade: VirtualTrade, price: float) -> VirtualTrade:
        unrealized = self._gross_pnl(trade, price)
        updated = trade.model_copy(
            update={
                "current_price": price,
                "mfe": max(trade.mfe, unrealized),
                "mae": min(trade.mae, unrealized),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._repository.save_virtual_trade(updated)
        return updated

    def _close_target(
        self,
        trade: VirtualTrade,
        price: float,
    ) -> Optional[tuple[float, CloseReason]]:
        final_take_profit = trade.take_profit[-1] if trade.take_profit else None
        if trade.side == "long":
            if price <= trade.stop_loss:
                return trade.stop_loss, "stop_loss"
            if final_take_profit is not None and price >= final_take_profit:
                return final_take_profit, "take_profit"
        else:
            if price >= trade.stop_loss:
                return trade.stop_loss, "stop_loss"
            if final_take_profit is not None and price <= final_take_profit:
                return final_take_profit, "take_profit"
        return None

    def _close_trade(
        self,
        trade: VirtualTrade,
        exit_price: float,
        reason: CloseReason,
    ) -> VirtualTrade:
        if trade.status != "open":
            return trade

        exit_slippage_bps = self._exit_slippage_bps_for_trade(trade, reason)
        slipped_exit = self._apply_exit_slippage(
            exit_price,
            trade.side,
            exit_slippage_bps,
        )
        exit_fee = trade.quantity * slipped_exit * (trade.fees / trade.size_usd)
        gross_pnl = self._gross_pnl(trade, slipped_exit)
        total_fees = trade.fees + exit_fee
        net_pnl = gross_pnl - total_fees
        pnl_percent = net_pnl / trade.size_usd * 100 if trade.size_usd else 0.0
        now = datetime.now(timezone.utc)

        updated = trade.model_copy(
            update={
                "current_price": slipped_exit,
                "exit_price": slipped_exit,
                "fees": total_fees,
                "status": "closed",
                "result": self._result(net_pnl),
                "close_reason": reason,
                "pnl": net_pnl,
                "pnl_percent": pnl_percent,
                "updated_at": now,
                "closed_at": now,
            }
        )
        updated = self._repository.save_virtual_trade(updated)
        self._after_virtual_trade_events(self._consume_repository_events())
        self._apply_account_close(updated, net_pnl)
        return updated

    def _after_signal_write(self, result: SignalWriteResult) -> None:
        try:
            self._signal_analytics_writer.write_event(result.analytics_event)
        except Exception as exc:
            logger.warning("ClickHouse signal confirm analytics write failed: %s", exc)
        try:
            self._signal_hot_store.write_signal(result)
        except Exception as exc:
            logger.warning("Redis signal confirm hot write failed: %s", exc)

    def _after_virtual_trade_events(self, events: list[VirtualTradePersistenceEvent]) -> None:
        for event in events:
            try:
                _write_virtual_trade_analytics_event(event)
            except Exception as exc:
                logger.warning("ClickHouse virtual trade event write failed: %s", exc)
            try:
                _publish_portfolio_event(event)
            except Exception as exc:
                logger.warning("Redis portfolio publish failed: %s", exc)

    def _consume_repository_events(self) -> list[VirtualTradePersistenceEvent]:
        consume_events = getattr(self._repository, "consume_events", None)
        if consume_events is None:
            return []
        return consume_events()

    def _apply_account_close(self, trade: VirtualTrade, pnl: float) -> None:
        user_id = trade.user_id
        self._account_balance_by_user[user_id] = (
            self._account_balance_by_user.setdefault(
                user_id,
                VIRTUAL_STARTING_BALANCE,
            )
            + pnl
        )
        self._realized_pnl_by_user[user_id] = (
            self._realized_pnl_by_user.setdefault(user_id, 0.0)
            + pnl
        )
        stats = self._account_stats_by_user.setdefault(
            user_id,
            {
                "closed_trades": 0,
                "wins": 0,
                "losses": 0,
                "breakeven": 0,
            },
        )
        stats["closed_trades"] += 1
        if trade.result == "win":
            stats["wins"] += 1
        elif trade.result == "loss":
            stats["losses"] += 1
        else:
            stats["breakeven"] += 1

    def _trim_trades(self) -> None:
        virtual_trades = self._repository.list_virtual_trades()
        if len(virtual_trades) <= MAX_STORED_TRADES:
            return

        keep_ids = {trade.id for trade in virtual_trades[:MAX_STORED_TRADES]}
        for trade in virtual_trades[MAX_STORED_TRADES:]:
            self._repository.delete_virtual_trade(trade.id)
        self._trade_by_signal = {
            signal_id: trade_id
            for signal_id, trade_id in self._trade_by_signal.items()
            if trade_id in keep_ids
        }

    @staticmethod
    def _entry_price(signal: RadarSignal) -> float:
        if signal.entry_min is not None and signal.entry_max is not None:
            return (signal.entry_min + signal.entry_max) / 2
        if signal.entry_min is not None:
            return signal.entry_min
        if signal.entry_max is not None:
            return signal.entry_max
        raise ValueError("У сигнала нет entry zone")

    @staticmethod
    def _apply_entry_slippage(
        price: float,
        side: str,
        slippage_bps: float,
    ) -> float:
        multiplier = slippage_bps / 10_000
        return price * (1 + multiplier) if side == "long" else price * (1 - multiplier)

    @staticmethod
    def _apply_exit_slippage(
        price: float,
        side: str,
        slippage_bps: float,
    ) -> float:
        multiplier = slippage_bps / 10_000
        return price * (1 - multiplier) if side == "long" else price * (1 + multiplier)

    @staticmethod
    def _exit_slippage_bps_for_trade(
        trade: VirtualTrade,
        reason: CloseReason,
    ) -> float:
        if trade.execution is None:
            return trade.slippage_bps
        exit_slippage_bps = max(trade.execution.exit_slippage_bps, trade.slippage_bps)
        if reason == "stop_loss" and trade.execution.mode == "impact_aware":
            return exit_slippage_bps * 1.1
        return exit_slippage_bps

    @staticmethod
    def _stop_matches_side(entry_price: float, stop_loss: float, side: str) -> bool:
        if side == "long":
            return stop_loss < entry_price
        return stop_loss > entry_price

    @staticmethod
    def _fallback_stop(entry_price: float, side: str) -> float:
        fallback_distance = entry_price * 0.01
        if side == "long":
            return entry_price - fallback_distance
        return entry_price + fallback_distance

    @staticmethod
    def _take_profit(entry_price: float, risk_per_unit: float, side: str) -> float:
        target_distance = risk_per_unit * VIRTUAL_RISK_REWARD
        if side == "long":
            return entry_price + target_distance
        return entry_price - target_distance

    @staticmethod
    def _gross_pnl(trade: VirtualTrade, price: float) -> float:
        if trade.side == "long":
            return (price - trade.entry_price) * trade.quantity
        return (trade.entry_price - price) * trade.quantity

    @staticmethod
    def _result(pnl: float) -> TradeResult:
        if pnl > 0:
            return "win"
        if pnl < 0:
            return "loss"
        return "breakeven"


trade_service = TradeService()


_VIRTUAL_TRADE_EVENT_COLUMNS = [
    "user_id",
    "portfolio_id",
    "order_id",
    "position_id",
    "signal_id",
    "event_type",
    "exchange",
    "symbol",
    "side",
    "price",
    "quantity",
    "pnl",
    "fee",
    "event_ts",
    "ingest_ts",
]


def _write_virtual_trade_analytics_event(event: VirtualTradePersistenceEvent) -> None:
    trade = event.trade
    event_ts = trade.closed_at or trade.opened_at or datetime.now(timezone.utc)
    price = trade.exit_price or trade.current_price or trade.entry_price
    get_clickhouse_client().insert(
        "analytics.virtual_trade_events",
        [
            [
                event.user_id,
                event.portfolio_id,
                event.order_id,
                event.position_id,
                event.signal_id,
                event.event_type,
                trade.exchange,
                trade.symbol,
                trade.side,
                Decimal(str(price)),
                Decimal(str(trade.quantity)),
                Decimal(str(trade.pnl)) if trade.pnl is not None else None,
                event.fee,
                event_ts,
                datetime.now(timezone.utc),
            ]
        ],
        column_names=_VIRTUAL_TRADE_EVENT_COLUMNS,
    )


def _publish_portfolio_event(event: VirtualTradePersistenceEvent) -> None:
    payload = {
        "event_type": event.event_type,
        "user_id": str(event.user_id),
        "portfolio_id": str(event.portfolio_id),
        "order_id": str(event.order_id),
        "position_id": str(event.position_id),
        "signal_id": str(event.signal_id) if event.signal_id is not None else None,
        "trade": event.trade.model_dump(mode="json"),
    }
    get_redis_client().publish(
        f"pubsub:portfolio:{event.user_id}",
        json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")),
    )
