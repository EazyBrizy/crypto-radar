from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, object_session, sessionmaker

from app.core.database import SessionLocal
from app.domain.signal_status import is_terminal_signal_status
from app.models.audit import AuditLog
from app.models.external_exchange import ExternalExchangeTrade
from app.models.market import MarketAsset, MarketPair
from app.models.outbox import OutboxEvent
from app.models.portfolio import (
    Order,
    OrderFill,
    Portfolio,
    PortfolioBalance,
    PortfolioBalanceLedger,
    Position,
)
from app.models.risk import PositionRiskSnapshot, RiskDecisionRecord, RiskProtectionState
from app.models.signal import TradingSignal
from app.models.user import AppUser
from app.repositories.signal_repository import (
    SIGNAL_CONFIRMED_EVENT,
    SignalWriteResult,
    _analytics_event,
    _get_signal_record,
    _persist_signal_event,
    _record_to_radar_signal,
)
from app.schemas.trade import ManualConfirmRequest, RealTrade, TradeJournalEntry, VirtualAccount, VirtualTrade
from app.services.bootstrap_service import INITIAL_VIRTUAL_BALANCE
from app.models.strategy import StrategyVersion
from app.services.risk_state import risk_state_service
from app.services.user_identity import resolve_app_user


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


@dataclass(frozen=True)
class VirtualTradePersistenceEvent:
    event_type: str
    trade: VirtualTrade
    user_id: UUID
    portfolio_id: UUID
    order_id: UUID
    position_id: UUID
    signal_id: UUID | None
    fee: Decimal | None = None


@dataclass(frozen=True)
class VirtualTradeConfirmationResult:
    signal_result: SignalWriteResult
    trade: VirtualTrade
    events: list[VirtualTradePersistenceEvent] = field(default_factory=list)


class PostgresVirtualTradeRepository:
    """PostgreSQL source of truth for virtual trading."""

    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._events: list[VirtualTradePersistenceEvent] = []

    def save_virtual_trade(self, trade: VirtualTrade) -> VirtualTrade:
        with self._session_factory() as session:
            position = _get_position_by_trade_id(session, trade.id)
            if position is None:
                signal = _get_signal_record(session, trade.signal_id)
                if signal is None:
                    raise ValueError("Signal is not found for virtual trade")
                user = resolve_app_user(session, trade.user_id)
                portfolio = _resolve_virtual_portfolio(session, user)
                quote_asset = _quote_asset(signal)
                balance = _resolve_balance(session, portfolio, quote_asset)
                persisted_trade, event = self._create_open_trade(
                    session=session,
                    signal=signal,
                    user=user,
                    portfolio=portfolio,
                    balance=balance,
                    quote_asset=quote_asset,
                    trade=trade,
                    idempotency_key=f"virtual-open:{signal.id}",
                    confirm_signal=False,
                    request=None,
                )
                session.commit()
                self._events.append(event)
                return persisted_trade

            if trade.status == "closed" and position.status == "open":
                updated, event = self._close_position(session, position, trade)
                session.commit()
                self._events.append(event)
                return updated

            updated = self._update_position_snapshot(session, position, trade)
            session.commit()
            return updated

    def confirm_signal_with_trade(
        self,
        signal_id: str,
        request: ManualConfirmRequest,
        trade: VirtualTrade,
    ) -> VirtualTradeConfirmationResult:
        with self._session_factory() as session:
            signal = _get_signal_record(session, signal_id)
            if signal is None:
                raise ValueError("Signal is not found")
            if is_terminal_signal_status(signal.status):
                raise ValueError("Signal cannot be confirmed in current status")

            user = resolve_app_user(session, request.user_id)
            existing_position = session.scalars(
                _position_select()
                .where(
                    Position.user_id == user.id,
                    Position.signal_id == signal.id,
                    Position.mode == "virtual",
                )
                .order_by(Position.opened_at.desc())
                .limit(1)
            ).one_or_none()
            if existing_position is not None:
                existing_trade = _position_to_virtual_trade(existing_position)
                if signal.status != "confirmed":
                    signal_result = self._confirm_signal_record(
                        session=session,
                        signal=signal,
                        trade_id=existing_trade.id,
                        request=request,
                        now=datetime.now(timezone.utc),
                    )
                    _add_virtual_trade_audit(
                        session=session,
                        user=user,
                        position_id=existing_position.id,
                        action="virtual_trade.confirm_existing",
                        payload={"trade": existing_trade.model_dump(mode="json")},
                    )
                    session.commit()
                    return VirtualTradeConfirmationResult(signal_result, existing_trade, [])

                signal_result = _signal_result_for_confirmed(signal, existing_trade.id)
                session.commit()
                return VirtualTradeConfirmationResult(signal_result, existing_trade, [])

            idempotency_key = f"virtual-confirm:{signal.id}"
            existing_order = _get_order_by_idempotency(session, user.id, idempotency_key)
            if existing_order is not None:
                position = _position_from_order_metadata(session, existing_order)
                if position is None:
                    raise ValueError("Existing virtual order has no position metadata")
                existing_trade = _position_to_virtual_trade(position)
                if signal.status != "confirmed":
                    signal_result = self._confirm_signal_record(
                        session=session,
                        signal=signal,
                        trade_id=existing_trade.id,
                        request=request,
                        now=datetime.now(timezone.utc),
                    )
                    _add_virtual_trade_audit(
                        session=session,
                        user=user,
                        position_id=position.id,
                        action="virtual_trade.confirm_idempotent",
                        payload={"trade": existing_trade.model_dump(mode="json")},
                    )
                    session.commit()
                    return VirtualTradeConfirmationResult(signal_result, existing_trade, [])

                signal_result = _signal_result_for_confirmed(signal, existing_trade.id)
                session.commit()
                return VirtualTradeConfirmationResult(signal_result, existing_trade, [])

            portfolio = _resolve_virtual_portfolio(session, user)
            quote_asset = _quote_asset(signal)
            balance = _resolve_balance(session, portfolio, quote_asset)
            open_positions = _count_open_positions(session, user.id)
            if open_positions >= request.max_open_positions:
                raise ValueError("Достигнут лимит открытых виртуальных позиций")

            persisted_trade, event = self._create_open_trade(
                session=session,
                signal=signal,
                user=user,
                portfolio=portfolio,
                balance=balance,
                quote_asset=quote_asset,
                trade=trade,
                idempotency_key=idempotency_key,
                confirm_signal=True,
                request=request,
            )
            signal_result = self._confirm_signal_record(
                session=session,
                signal=signal,
                trade_id=persisted_trade.id,
                request=request,
                now=persisted_trade.opened_at,
            )
            session.commit()
            self._events.append(event)
            return VirtualTradeConfirmationResult(signal_result, persisted_trade, [event])

    def get_virtual_account(self, user_id: str = "demo_user") -> VirtualAccount:
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            portfolio = _resolve_virtual_portfolio(session, user)
            quote_asset = _resolve_asset(session, portfolio.base_currency)
            balance = _resolve_balance(session, portfolio, quote_asset)
            open_positions = session.scalars(
                _position_select().where(
                    Position.user_id == user.id,
                    Position.mode == "virtual",
                    Position.status == "open",
                )
            ).all()
            open_trades = [_position_to_virtual_trade(position) for position in open_positions]
            closed_positions = session.scalars(
                _position_select().where(
                    Position.user_id == user.id,
                    Position.mode == "virtual",
                    Position.status == "closed",
                )
            ).all()
            unrealized_pnl = sum(
                _gross_pnl(trade, trade.current_price)
                for trade in open_trades
            )
            open_realized_pnl = sum(trade.realized_pnl for trade in open_trades)
            wins = losses = breakeven = 0
            realized_pnl = Decimal("0")
            for position in closed_positions:
                pnl = position.realized_pnl or Decimal("0")
                realized_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                else:
                    breakeven += 1
            updated_at = max(
                [balance.updated_at]
                + [position.updated_at for position in open_positions]
                + [position.updated_at for position in closed_positions],
            )
            starting_balance = _starting_balance(session, portfolio, quote_asset)
            return VirtualAccount(
                user_id=user_id,
                starting_balance=float(starting_balance),
                balance=float(balance.available),
                equity=float(balance.available + balance.locked + _decimal(open_realized_pnl + unrealized_pnl)),
                realized_pnl=float(realized_pnl + _decimal(open_realized_pnl)),
                unrealized_pnl=float(unrealized_pnl),
                open_positions=len(open_positions),
                closed_trades=len(closed_positions),
                wins=wins,
                losses=losses,
                breakeven=breakeven,
                updated_at=updated_at,
            )

    def get_virtual_trade(self, trade_id: str) -> Optional[VirtualTrade]:
        with self._session_factory() as session:
            position = _get_position_by_trade_id(session, trade_id)
            return _position_to_virtual_trade(position) if position is not None else None

    def list_virtual_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[VirtualTrade]:
        with self._session_factory() as session:
            statement = _position_select().where(Position.mode == "virtual")
            if status is not None:
                db_status = "open" if status == "open" else "closed"
                statement = statement.where(Position.status == db_status)
            if signal_id is not None:
                signal_uuid = _parse_uuid(signal_id)
                if signal_uuid is None:
                    return []
                statement = statement.where(Position.signal_id == signal_uuid)
            statement = statement.order_by(Position.opened_at.desc())
            return [_position_to_virtual_trade(position) for position in session.scalars(statement).all()]

    def delete_virtual_trade(self, trade_id: str) -> None:
        raise NotImplementedError("PostgreSQL virtual trades are append-only")

    def save_real_trade(self, trade: RealTrade) -> RealTrade:
        raise NotImplementedError("Real trade sync uses external_exchange_trades")

    def get_real_trade(self, trade_id: str) -> Optional[RealTrade]:
        trade_uuid = _parse_uuid(trade_id)
        if trade_uuid is None:
            return None
        with self._session_factory() as session:
            trade = session.scalars(
                _external_trade_select().where(ExternalExchangeTrade.id == trade_uuid)
            ).one_or_none()
            return _external_trade_to_real_trade(trade) if trade is not None else None

    def list_real_trades(
        self,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[RealTrade]:
        if signal_id is not None:
            return []
        if status is not None and status != "closed":
            return []
        with self._session_factory() as session:
            trades = session.scalars(
                _external_trade_select().order_by(
                    ExternalExchangeTrade.traded_at.desc(),
                    ExternalExchangeTrade.imported_at.desc(),
                )
            ).all()
            return [_external_trade_to_real_trade(trade) for trade in trades]

    def list_journal(
        self,
        mode: Optional[str] = None,
        status: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> list[TradeJournalEntry]:
        trades: list[TradeJournalEntry] = []
        if mode in {None, "virtual"}:
            trades.extend(
                TradeJournalEntry.model_validate(trade.model_dump())
                for trade in self.list_virtual_trades(status=status, signal_id=signal_id)
            )
        if mode in {None, "real"}:
            trades.extend(
                TradeJournalEntry.model_validate(trade.model_dump())
                for trade in self.list_real_trades(status=status, signal_id=signal_id)
            )
        return sorted(trades, key=lambda trade: trade.opened_at, reverse=True)

    def consume_events(self) -> list[VirtualTradePersistenceEvent]:
        events = self._events
        self._events = []
        return events

    def _create_open_trade(
        self,
        *,
        session: Session,
        signal: TradingSignal,
        user: AppUser,
        portfolio: Portfolio,
        balance: PortfolioBalance,
        quote_asset: MarketAsset,
        trade: VirtualTrade,
        idempotency_key: str,
        confirm_signal: bool,
        request: ManualConfirmRequest | None,
    ) -> tuple[VirtualTrade, VirtualTradePersistenceEvent]:
        risk_amount = _decimal(trade.risk_amount)
        if balance.available < risk_amount:
            raise ValueError("Недостаточно доступного виртуального баланса")

        now = trade.opened_at
        order_status = "partially_filled" if trade.execution_status == "partially_filled" else "filled"
        requested_quantity = _decimal((trade.requested_size_usd or trade.size_usd) / trade.entry_price)
        order = Order(
            user_id=user.id,
            portfolio_id=portfolio.id,
            signal_id=signal.id,
            exchange_id=signal.exchange_id,
            pair_id=signal.pair_id,
            mode="virtual",
            side="buy" if trade.side == "long" else "sell",
            order_type="market",
            status=order_status,
            quantity=requested_quantity,
            price=_decimal(trade.entry_price),
            idempotency_key=idempotency_key,
            metadata_={
                "role": "entry",
                "external_user_id": trade.user_id,
                "virtual_trade": trade.model_dump(mode="json"),
                "virtual_execution": trade.execution.model_dump(mode="json") if trade.execution is not None else None,
                "confirm_signal": confirm_signal,
            },
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        session.flush()

        fill = OrderFill(
            order_id=order.id,
            price=_decimal(trade.entry_price),
            quantity=_decimal(trade.quantity),
            fee_amount=_decimal(trade.fees),
            fee_asset_id=quote_asset.id,
            liquidity="simulated",
            source_event_id=f"virtual-entry:{signal.id}",
            filled_at=now,
        )
        session.add(fill)

        position = Position(
            user_id=user.id,
            portfolio_id=portfolio.id,
            signal_id=signal.id,
            pair_id=signal.pair_id,
            mode="virtual",
            side=trade.side,
            status="open",
            quantity=_decimal(trade.quantity),
            entry_avg_price=_decimal(trade.entry_price),
            stop_loss=_decimal(trade.stop_loss),
            take_profit=trade.take_profit,
            opened_at=now,
            realized_pnl=Decimal("0"),
            fees_total=_decimal(trade.fees),
            created_at=now,
            updated_at=now,
        )
        session.add(position)
        session.flush()

        persisted_trade = _trade_with_lifecycle_trace(
            trade.model_copy(update={"id": str(position.id)}),
            signal_id=str(signal.id),
            virtual_trade_id=str(position.id),
        )
        order.metadata_ = {
            **(order.metadata_ or {}),
            "position_id": str(position.id),
            "virtual_trade": persisted_trade.model_dump(mode="json"),
            "virtual_execution": (
                persisted_trade.execution.model_dump(mode="json")
                if persisted_trade.execution is not None
                else None
            ),
        }
        risk_decision = _persist_open_trade_risk_snapshot(
            session=session,
            signal=signal,
            user=user,
            portfolio=portfolio,
            order=order,
            position=position,
            trade=persisted_trade,
            request=request,
            idempotency_key=idempotency_key,
        )
        if risk_decision is not None:
            persisted_trade = _trade_with_lifecycle_trace(
                persisted_trade,
                signal_id=str(signal.id),
                virtual_trade_id=str(position.id),
                risk_decision_id=str(risk_decision.id),
            )
            order.metadata_ = {
                **(order.metadata_ or {}),
                "risk_decision_id": str(risk_decision.id),
                "lifecycle_trace": persisted_trade.lifecycle_trace.model_dump(
                    mode="json",
                    exclude_none=True,
                ),
                "virtual_trade": persisted_trade.model_dump(mode="json"),
                "virtual_execution": (
                    persisted_trade.execution.model_dump(mode="json")
                    if persisted_trade.execution is not None
                    else None
                ),
            }
        _reserve_risk_balance(
            session=session,
            balance=balance,
            portfolio=portfolio,
            asset=quote_asset,
            risk_amount=risk_amount,
            position_id=position.id,
            now=now,
        )
        _add_virtual_trade_outbox(session, position.id, "virtual_trade.opened", persisted_trade)
        _add_virtual_trade_audit(
            session=session,
            user=user,
            position_id=position.id,
            action="virtual_trade.opened",
            payload={
                "trade": persisted_trade.model_dump(mode="json"),
                "order_id": str(order.id),
                "portfolio_id": str(portfolio.id),
                "request": request.model_dump(mode="json") if request is not None else None,
            },
        )
        event = VirtualTradePersistenceEvent(
            event_type="virtual_trade.opened",
            trade=persisted_trade,
            user_id=user.id,
            portfolio_id=portfolio.id,
            order_id=order.id,
            position_id=position.id,
            signal_id=signal.id,
            fee=_decimal(trade.fees),
        )
        return persisted_trade, event

    def _close_position(
        self,
        session: Session,
        position: Position,
        trade: VirtualTrade,
    ) -> tuple[VirtualTrade, VirtualTradePersistenceEvent]:
        now = trade.closed_at or datetime.now(timezone.utc)
        quote_asset = position.pair.quote_asset
        entry_order = _entry_order_for_position(session, position)
        if entry_order is None:
            raise ValueError("Entry order is not found for virtual position")
        close_order = _get_order_by_idempotency(
            session,
            position.user_id,
            f"virtual-close:{position.id}",
        )
        close_quantity = _close_order_quantity(trade, position.quantity)
        if close_order is None:
            close_order = Order(
                user_id=position.user_id,
                portfolio_id=position.portfolio_id,
                signal_id=position.signal_id,
                exchange_id=position.pair.exchange_id,
                pair_id=position.pair_id,
                mode="virtual",
                side="sell" if position.side == "long" else "buy",
                order_type="market",
                status="filled",
                quantity=close_quantity,
                price=_decimal(trade.exit_price or trade.current_price),
                idempotency_key=f"virtual-close:{position.id}",
                metadata_={
                    "role": "exit",
                    "position_id": str(position.id),
                    "close_reason": trade.close_reason,
                    "virtual_trade": trade.model_dump(mode="json"),
                    "virtual_execution": trade.execution.model_dump(mode="json") if trade.execution is not None else None,
                },
                created_at=now,
                updated_at=now,
            )
            session.add(close_order)
            session.flush()
            session.add(
                OrderFill(
                    order_id=close_order.id,
                    price=_decimal(trade.exit_price or trade.current_price),
                    quantity=close_quantity,
                    fee_amount=max(_decimal(trade.fees) - (position.fees_total or Decimal("0")), Decimal("0")),
                    fee_asset_id=quote_asset.id,
                    liquidity="simulated",
                    source_event_id=f"virtual-exit:{position.id}",
                    filled_at=now,
                )
            )

        position.status = "closed"
        position.exit_avg_price = _decimal(trade.exit_price or trade.current_price)
        position.closed_at = now
        position.realized_pnl = _decimal(trade.pnl or 0)
        position.fees_total = _decimal(trade.fees)
        position.updated_at = now
        entry_order.metadata_ = {
            **(entry_order.metadata_ or {}),
            "virtual_trade": trade.model_dump(mode="json"),
            "virtual_execution": trade.execution.model_dump(mode="json") if trade.execution is not None else None,
            "current_price": trade.current_price,
            "mfe": trade.mfe,
            "mae": trade.mae,
            "close_reason": trade.close_reason,
            "pnl_percent": trade.pnl_percent,
        }
        balance = _resolve_balance(session, position.portfolio, quote_asset)
        _release_risk_balance(
            session=session,
            balance=balance,
            portfolio=position.portfolio,
            asset=quote_asset,
            risk_amount=_snapshot_decimal(entry_order, "risk_amount", Decimal("0")),
            pnl=_decimal(trade.pnl or 0),
            position_id=position.id,
            now=now,
        )
        risk_state_service.update_after_trade_close(
            session=session,
            user=position.user,
            realized_pnl=_decimal(trade.pnl or 0),
            current_equity=_decimal(balance.available + balance.locked),
        )
        _add_virtual_trade_outbox(session, position.id, "virtual_trade.closed", trade)
        _add_virtual_trade_audit(
            session=session,
            user=position.user,
            position_id=position.id,
            action="virtual_trade.closed",
            payload={
                "trade": trade.model_dump(mode="json"),
                "order_id": str(close_order.id),
                "portfolio_id": str(position.portfolio_id),
            },
        )
        event = VirtualTradePersistenceEvent(
            event_type="virtual_trade.closed",
            trade=trade,
            user_id=position.user_id,
            portfolio_id=position.portfolio_id,
            order_id=close_order.id,
            position_id=position.id,
            signal_id=position.signal_id,
            fee=_decimal(trade.fees),
        )
        return trade, event

    def _update_position_snapshot(
        self,
        session: Session,
        position: Position,
        trade: VirtualTrade,
    ) -> VirtualTrade:
        entry_order = _entry_order_for_position(session, position)
        if entry_order is None:
            return _position_to_virtual_trade(position)
        entry_order.metadata_ = {
            **(entry_order.metadata_ or {}),
            "virtual_trade": trade.model_dump(mode="json"),
            "virtual_execution": trade.execution.model_dump(mode="json") if trade.execution is not None else None,
            "current_price": trade.current_price,
            "mfe": trade.mfe,
            "mae": trade.mae,
        }
        position.updated_at = trade.updated_at
        return trade

    @staticmethod
    def _confirm_signal_record(
        *,
        session: Session,
        signal: TradingSignal,
        trade_id: str,
        request: ManualConfirmRequest,
        now: datetime,
    ) -> SignalWriteResult:
        old_status = signal.status
        signal.status = "confirmed"
        signal.updated_at = now
        snapshot = dict(signal.features_snapshot or {})
        snapshot["decision"] = {
            "confirmed_trade_id": trade_id,
            "decision_mode": request.mode,
            "decision_note": "Пользователь подтвердил сигнал в virtual mode",
        }
        auto_entry = snapshot.get("auto_entry")
        if isinstance(auto_entry, dict) and auto_entry.get("status") == "pending":
            snapshot["auto_entry"] = {
                **auto_entry,
                "enabled": False,
                "status": "triggered",
                "triggered_at": now.isoformat(),
                "trade_id": trade_id,
                "message": "Auto-entry confirmed the setup and opened a virtual trade",
            }
        signal.features_snapshot = snapshot
        return _persist_signal_event(
            session,
            signal,
            SIGNAL_CONFIRMED_EVENT,
            old_status=old_status,
            now=now,
        )


VIRTUAL_STARTING_BALANCE_REASONS = (
    "bootstrap_initial_balance",
    "settings_virtual_starting_balance",
)


def sync_virtual_starting_balance(
    session: Session,
    user: AppUser,
    target_balance: Decimal | float | str,
) -> None:
    target = _decimal(target_balance)
    if target <= 0:
        raise ValueError("virtual starting balance must be greater than zero")

    portfolio = _resolve_virtual_portfolio(session, user)
    asset = _resolve_asset(session, portfolio.base_currency)
    balance = _resolve_balance(session, portfolio, asset)
    current_starting_balance = _starting_balance(session, portfolio, asset)
    delta = target - current_starting_balance
    if delta == 0:
        return

    if balance.available + delta < 0:
        raise ValueError("virtual starting balance cannot be lower than current reserved account changes")

    now = datetime.now(timezone.utc)
    balance.available += delta
    balance.updated_at = now
    session.add(
        PortfolioBalanceLedger(
            portfolio_id=portfolio.id,
            asset_id=asset.id,
            delta_available=delta,
            delta_locked=Decimal("0"),
            reason="settings_virtual_starting_balance",
            ref_type="user_settings",
            ref_id=user.id,
            created_at=now,
        )
    )

    state = session.get(RiskProtectionState, user.id)
    if state is not None:
        equity = max(balance.available + balance.locked, Decimal("0"))
        state.current_equity = equity
        state.peak_equity = equity
        state.daily_loss_amount = Decimal("0")
        state.weekly_loss_amount = Decimal("0")
        state.loss_streak = 0
        state.adaptive_multiplier = Decimal("1")
        state.state = "normal"
        state.reason = None
        state.updated_at = now


def _external_trade_select():
    return select(ExternalExchangeTrade).options(
        joinedload(ExternalExchangeTrade.pair).joinedload(MarketPair.exchange),
        joinedload(ExternalExchangeTrade.fee_asset),
    )


def _external_trade_to_real_trade(trade: ExternalExchangeTrade) -> RealTrade:
    metadata = trade.metadata_ or {}
    price = float(trade.price)
    quantity = float(trade.quantity)
    size_usd = price * quantity
    take_profit = metadata.get("take_profit")
    screenshots = metadata.get("screenshots")
    return RealTrade(
        id=str(trade.id),
        user_id=str(trade.user_id),
        signal_id=metadata.get("signal_id"),
        exchange=trade.pair.exchange.code,
        symbol=trade.pair.symbol,
        strategy=str(metadata.get("strategy") or "external_import"),
        timeframe=str(metadata.get("timeframe") or "trade"),
        side=_external_trade_side(trade.side),
        entry_price=price,
        current_price=price,
        exit_price=price,
        size_usd=size_usd,
        quantity=quantity,
        leverage=int(metadata.get("leverage") or 1),
        risk_percent=float(metadata.get("risk_percent") or 0),
        risk_amount=float(metadata.get("risk_amount") or 0),
        risk_reward=float(metadata.get("risk_reward") or 0),
        stop_loss=float(metadata.get("stop_loss") or 0),
        take_profit=[float(value) for value in take_profit] if isinstance(take_profit, list) else [],
        fees=float(trade.fee_amount or 0),
        slippage_bps=float(metadata.get("slippage_bps") or 0),
        status="closed",
        result=_optional_value(metadata.get("result"), {"win", "loss", "breakeven"}),
        close_reason=_optional_value(
            metadata.get("close_reason"),
            {
                "take_profit",
                "stop_loss",
                "manual_close",
                "invalidation",
                "cancelled",
                "partial_take_profit",
                "breakeven_stop",
                "trailing_stop",
                "time_stop",
            },
        ),
        pnl=float(metadata["pnl"]) if metadata.get("pnl") is not None else None,
        pnl_percent=float(metadata["pnl_percent"]) if metadata.get("pnl_percent") is not None else None,
        mfe=float(metadata.get("mfe") or 0),
        mae=float(metadata.get("mae") or 0),
        screenshots=screenshots if isinstance(screenshots, list) else [],
        ai_review=metadata.get("ai_review"),
        opened_at=trade.traded_at,
        updated_at=trade.imported_at,
        closed_at=trade.traded_at,
        exchange_order_id=trade.exchange_order_id,
    )


def _external_trade_side(side: str) -> str:
    return "short" if side.lower() == "sell" else "long"


def _optional_value(value: Any, allowed: set[str]) -> str | None:
    if isinstance(value, str) and value in allowed:
        return value
    return None


def _position_select():
    return select(Position).options(
        joinedload(Position.user),
        joinedload(Position.portfolio),
        joinedload(Position.pair).joinedload(MarketPair.exchange),
        joinedload(Position.pair).joinedload(MarketPair.quote_asset),
        joinedload(Position.signal)
        .joinedload(TradingSignal.strategy_version)
        .joinedload(StrategyVersion.strategy),
    )


def _resolve_virtual_portfolio(session: Session, user: AppUser) -> Portfolio:
    portfolio = session.scalars(
        select(Portfolio).where(
            Portfolio.user_id == user.id,
            Portfolio.type == "virtual",
            Portfolio.status == "active",
        )
        .order_by(Portfolio.created_at.asc())
        .limit(1)
    ).one_or_none()
    if portfolio is not None:
        return portfolio

    portfolio = Portfolio(
        user_id=user.id,
        type="virtual",
        name="Default Virtual Portfolio",
        base_currency="USDT",
        status="active",
    )
    session.add(portfolio)
    session.flush()
    return portfolio


def _resolve_asset(session: Session, symbol: str) -> MarketAsset:
    asset = session.scalars(select(MarketAsset).where(MarketAsset.symbol == symbol.upper())).one_or_none()
    if asset is None:
        raise ValueError(f"Asset is not seeded: {symbol}")
    return asset


def _quote_asset(signal: TradingSignal) -> MarketAsset:
    return signal.pair.quote_asset


def _resolve_balance(
    session: Session,
    portfolio: Portfolio,
    asset: MarketAsset,
) -> PortfolioBalance:
    balance = session.scalars(
        select(PortfolioBalance)
        .where(
            PortfolioBalance.portfolio_id == portfolio.id,
            PortfolioBalance.asset_id == asset.id,
        )
        .with_for_update()
    ).one_or_none()
    if balance is not None:
        return balance

    balance = PortfolioBalance(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        available=INITIAL_VIRTUAL_BALANCE,
        locked=Decimal("0"),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(balance)
    session.flush()
    return balance


def _starting_balance(
    session: Session,
    portfolio: Portfolio,
    asset: MarketAsset,
) -> Decimal:
    value = session.scalar(
        select(func.coalesce(func.sum(PortfolioBalanceLedger.delta_available), 0)).where(
            PortfolioBalanceLedger.portfolio_id == portfolio.id,
            PortfolioBalanceLedger.asset_id == asset.id,
            PortfolioBalanceLedger.reason.in_(VIRTUAL_STARTING_BALANCE_REASONS),
        )
    )
    return _decimal(value or INITIAL_VIRTUAL_BALANCE)


def _count_open_positions(session: Session, user_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(Position).where(
                Position.user_id == user_id,
                Position.mode == "virtual",
                Position.status == "open",
            )
        )
        or 0
    )


def _get_order_by_idempotency(
    session: Session,
    user_id: UUID,
    idempotency_key: str,
) -> Order | None:
    return session.scalars(
        select(Order).where(Order.user_id == user_id, Order.idempotency_key == idempotency_key)
    ).one_or_none()


def _position_from_order_metadata(session: Session, order: Order) -> Position | None:
    position_id = (order.metadata_ or {}).get("position_id")
    if not position_id:
        return None
    return _get_position_by_trade_id(session, str(position_id))


def _get_position_by_trade_id(session: Session, trade_id: str) -> Position | None:
    position_uuid = _parse_uuid(trade_id)
    if position_uuid is None:
        return None
    return session.scalars(_position_select().where(Position.id == position_uuid)).one_or_none()


def _entry_order_for_position(session: Session, position: Position) -> Order | None:
    order = session.scalars(
        select(Order).where(
            Order.user_id == position.user_id,
            Order.signal_id == position.signal_id,
            Order.mode == "virtual",
            Order.idempotency_key == f"virtual-confirm:{position.signal_id}",
        )
    ).one_or_none()
    if order is not None:
        return order
    return session.scalars(
        select(Order).where(
            Order.user_id == position.user_id,
            Order.signal_id == position.signal_id,
            Order.mode == "virtual",
            Order.idempotency_key == f"virtual-open:{position.signal_id}",
        )
    ).one_or_none()


def _reserve_risk_balance(
    *,
    session: Session,
    balance: PortfolioBalance,
    portfolio: Portfolio,
    asset: MarketAsset,
    risk_amount: Decimal,
    position_id: UUID,
    now: datetime,
) -> None:
    balance.available -= risk_amount
    balance.locked += risk_amount
    balance.updated_at = now
    session.add(
        PortfolioBalanceLedger(
            portfolio_id=portfolio.id,
            asset_id=asset.id,
            delta_available=-risk_amount,
            delta_locked=risk_amount,
            reason="virtual_trade_opened",
            ref_type="position",
            ref_id=position_id,
            created_at=now,
        )
    )


def _release_risk_balance(
    *,
    session: Session,
    balance: PortfolioBalance,
    portfolio: Portfolio,
    asset: MarketAsset,
    risk_amount: Decimal,
    pnl: Decimal,
    position_id: UUID,
    now: datetime,
) -> None:
    released_locked = min(balance.locked, risk_amount)
    delta_available = released_locked + pnl
    balance.available += delta_available
    balance.locked -= released_locked
    balance.updated_at = now
    session.add(
        PortfolioBalanceLedger(
            portfolio_id=portfolio.id,
            asset_id=asset.id,
            delta_available=delta_available,
            delta_locked=-released_locked,
            reason="virtual_trade_closed",
            ref_type="position",
            ref_id=position_id,
            created_at=now,
        )
    )


def _add_virtual_trade_outbox(
    session: Session,
    position_id: UUID,
    event_type: str,
    trade: VirtualTrade,
) -> None:
    session.add(
        OutboxEvent(
            aggregate_type="virtual_trade",
            aggregate_id=position_id,
            event_type=event_type,
            payload={"trade": trade.model_dump(mode="json")},
            status="pending",
            attempts=0,
            created_at=datetime.now(timezone.utc),
        )
    )


def _add_virtual_trade_audit(
    *,
    session: Session,
    user: AppUser,
    position_id: UUID,
    action: str,
    payload: dict[str, Any],
) -> None:
    session.add(
        AuditLog(
            user_id=user.id,
            action=action,
            entity_type="virtual_trade",
            entity_id=position_id,
            payload=payload,
            created_at=datetime.now(timezone.utc),
        )
    )


def _persist_open_trade_risk_snapshot(
    *,
    session: Session,
    signal: TradingSignal,
    user: AppUser,
    portfolio: Portfolio,
    order: Order,
    position: Position,
    trade: VirtualTrade,
    request: ManualConfirmRequest | None,
    idempotency_key: str,
) -> RiskDecisionRecord | None:
    execution = trade.execution
    if execution is None or execution.risk_decision is None:
        return None

    decision = execution.risk_decision
    pending_entry_intent_id = decision.lifecycle_trace.pending_entry_intent_id
    trace = _risk_lifecycle_trace(
        decision,
        risk_decision_id=None,
        signal_id=str(signal.id),
        virtual_trade_id=str(position.id),
    )
    input_snapshot = {
        "flow": "virtual_trade.opened",
        "lifecycle_trace": trace,
        "idempotency_key": idempotency_key,
        "external_user_id": trade.user_id,
        "request": request.model_dump(mode="json") if request is not None else None,
        "signal": {
            "id": str(signal.id),
            "exchange_id": str(signal.exchange_id),
            "pair_id": str(signal.pair_id),
            "symbol": signal.pair.symbol,
        },
        "execution": execution.model_dump(mode="json"),
    }
    risk_decision = RiskDecisionRecord(
        user_id=user.id,
        signal_id=signal.id,
        pending_entry_intent_id=_parse_uuid(pending_entry_intent_id),
        portfolio_id=portfolio.id,
        order_id=order.id,
        position_id=position.id,
        mode=decision.mode,
        instrument_type=decision.instrument_type,
        stage=decision.stage,
        status=decision.status,
        blockers=decision.blockers,
        warnings=decision.warnings,
        input_snapshot=input_snapshot,
        result_snapshot=decision.model_dump(mode="json"),
        created_at=trade.opened_at,
    )
    session.add(risk_decision)
    session.flush()
    trace = _risk_lifecycle_trace(
        decision,
        risk_decision_id=str(risk_decision.id),
        signal_id=str(signal.id),
        virtual_trade_id=str(position.id),
    )
    risk_decision.input_snapshot = _snapshot_with_lifecycle_trace(input_snapshot, trace)
    risk_decision.result_snapshot = _snapshot_with_lifecycle_trace(
        decision.model_dump(mode="json"),
        trace,
    )

    sizing = decision.checked_position_sizing
    adjustment = decision.risk_adjustment_plan
    futures = decision.futures_risk_plan
    session.add(
        PositionRiskSnapshot(
            position_id=position.id,
            risk_decision_id=risk_decision.id,
            risk_amount=_decimal(sizing.risk_amount),
            risk_percent=_decimal(sizing.risk_per_trade_percent),
            adjusted_risk_amount=_decimal(adjustment.adjusted_risk_amount),
            rr=_optional_decimal(decision.risk_check.rr),
            leverage=trade.leverage,
            margin_mode="isolated" if trade.leverage > 1 else "spot",
            liquidation_price=(
                _optional_decimal(futures.liquidation_price)
                if futures is not None
                else None
            ),
            liquidation_buffer_percent=(
                _optional_decimal(futures.liquidation_buffer_percent)
                if futures is not None
                else None
            ),
            correlation_group=_primary_risk_group(signal.pair),
            strategy_multiplier=_decimal(adjustment.strategy_risk_multiplier),
            signal_multiplier=_decimal(adjustment.signal_score_multiplier),
            fee_estimate=_position_fee_estimate(sizing),
            slippage_estimate=_position_slippage_estimate(sizing),
            funding_buffer=_position_funding_buffer(sizing),
            created_at=trade.opened_at,
        )
    )
    return risk_decision


def _position_to_virtual_trade(position: Position) -> VirtualTrade:
    session = object_session(position)
    entry_order = _entry_order_for_position(session, position) if session is not None else None
    metadata = entry_order.metadata_ if entry_order is not None else {}
    snapshot = metadata.get("virtual_trade", {}) if isinstance(metadata, dict) else {}
    entry_price = float(position.entry_avg_price)
    snapshot_quantity = _optional_float(snapshot.get("quantity"))
    quantity = snapshot_quantity if snapshot_quantity is not None else float(position.quantity)
    initial_quantity = _optional_float(snapshot.get("initial_quantity"))
    if initial_quantity is None:
        initial_quantity = quantity
    remaining_quantity = _optional_float(snapshot.get("remaining_quantity"))
    if remaining_quantity is None:
        remaining_quantity = 0.0 if position.status == "closed" else quantity
    closed_quantity = _optional_float(snapshot.get("closed_quantity"))
    if closed_quantity is None:
        closed_quantity = max(initial_quantity - remaining_quantity, 0.0)
    size_usd = _optional_float(snapshot.get("size_usd"))
    if size_usd is None:
        size_usd = entry_price * quantity
    initial_size_usd = _optional_float(snapshot.get("initial_size_usd"))
    if initial_size_usd is None:
        initial_size_usd = size_usd
    remaining_size_usd = _optional_float(snapshot.get("remaining_size_usd"))
    if remaining_size_usd is None:
        remaining_size_usd = entry_price * remaining_quantity
    pnl = float(position.realized_pnl or 0) if position.status == "closed" else None
    pnl_percent = snapshot.get("pnl_percent")
    if pnl_percent is None and pnl is not None and size_usd:
        pnl_percent = pnl / size_usd * 100
    current_stop_loss = _optional_float(snapshot.get("current_stop_loss"))
    if current_stop_loss is None and position.stop_loss is not None and float(position.stop_loss) > 0:
        current_stop_loss = float(position.stop_loss)
    snapshot_fees = _optional_float(snapshot.get("fees"))
    realized_pnl = _optional_float(snapshot.get("realized_pnl"))
    if realized_pnl is None:
        realized_pnl = pnl if pnl is not None else 0.0
    return VirtualTrade(
        id=str(position.id),
        user_id=snapshot.get("user_id") or (position.user.username or str(position.user_id)),
        signal_id=str(position.signal_id),
        exchange=position.pair.exchange.code,
        symbol=position.pair.symbol,
        strategy=position.signal.strategy_version.strategy.code if position.signal else snapshot.get("strategy", "unknown"),
        timeframe=position.signal.timeframe if position.signal else snapshot.get("timeframe", "unknown"),
        side=position.side,
        entry_price=entry_price,
        current_price=float(snapshot.get("current_price") or position.exit_avg_price or position.entry_avg_price),
        exit_price=float(position.exit_avg_price) if position.exit_avg_price is not None else None,
        size_usd=size_usd,
        quantity=quantity,
        initial_quantity=initial_quantity,
        remaining_quantity=remaining_quantity,
        closed_quantity=closed_quantity,
        initial_size_usd=initial_size_usd,
        remaining_size_usd=remaining_size_usd,
        leverage=int(snapshot.get("leverage") or 1),
        risk_percent=float(snapshot.get("risk_percent") or 0),
        risk_amount=float(snapshot.get("risk_amount") or 0),
        risk_reward=float(snapshot.get("risk_reward") or 3),
        stop_loss=float(position.stop_loss or 0),
        current_stop_loss=current_stop_loss,
        stop_moved_to_breakeven=bool(snapshot.get("stop_moved_to_breakeven") or False),
        trailing_active=bool(snapshot.get("trailing_active") or False),
        trailing_distance=_optional_float(snapshot.get("trailing_distance")),
        highest_price_after_trailing=_optional_float(
            snapshot.get("highest_price_after_trailing")
        ),
        lowest_price_after_trailing=_optional_float(
            snapshot.get("lowest_price_after_trailing")
        ),
        take_profit=[float(value) for value in (position.take_profit or [])],
        fees=float(snapshot_fees if snapshot_fees is not None else position.fees_total or 0),
        realized_pnl=realized_pnl,
        unrealized_pnl=float(snapshot.get("unrealized_pnl") or 0),
        exit_fees=float(snapshot.get("exit_fees") or 0),
        slippage_bps=float(snapshot.get("slippage_bps") or 0),
        simulation_mode=snapshot.get("simulation_mode") or (snapshot.get("execution") or {}).get("mode") or "passive",
        execution_status=snapshot.get("execution_status") or (snapshot.get("execution") or {}).get("status") or "filled",
        requested_size_usd=(
            float(snapshot["requested_size_usd"])
            if snapshot.get("requested_size_usd") is not None
            else None
        ),
        filled_size_usd=(
            float(snapshot["filled_size_usd"])
            if snapshot.get("filled_size_usd") is not None
            else None
        ),
        unfilled_size_usd=float(snapshot.get("unfilled_size_usd") or 0),
        execution=snapshot.get("execution"),
        status="open" if position.status == "open" else "closed",
        result=_trade_result(position.realized_pnl) if position.status == "closed" else None,
        close_reason=snapshot.get("close_reason"),
        pnl=pnl,
        pnl_percent=float(pnl_percent) if pnl_percent is not None else None,
        mfe=float(snapshot.get("mfe") or 0),
        mae=float(snapshot.get("mae") or 0),
        screenshots=snapshot.get("screenshots") or [],
        ai_review=snapshot.get("ai_review"),
        opened_at=position.opened_at,
        updated_at=position.updated_at,
        closed_at=position.closed_at,
        target_states=snapshot.get("target_states") or [],
        lifecycle_events=snapshot.get("lifecycle_events") or [],
        lifecycle_trace=snapshot.get("lifecycle_trace") or {},
    )


def _signal_result_for_confirmed(signal: TradingSignal, trade_id: str) -> SignalWriteResult:
    now = datetime.now(timezone.utc)
    return SignalWriteResult(
        signal=_record_to_radar_signal(signal),
        created=False,
        event_type=SIGNAL_CONFIRMED_EVENT,
        analytics_event=_analytics_event(signal, SIGNAL_CONFIRMED_EVENT, now),
    )


def _snapshot_decimal(order: Order, key: str, default: Decimal) -> Decimal:
    snapshot = (order.metadata_ or {}).get("virtual_trade", {})
    return _decimal(snapshot.get(key, default))


def _close_order_quantity(trade: VirtualTrade, fallback_quantity: Decimal) -> Decimal:
    for event in reversed(trade.lifecycle_events):
        if event.reason in {
            "take_profit",
            "stop_loss",
            "manual_close",
            "invalidation",
            "cancelled",
            "breakeven_stop",
            "trailing_stop",
            "time_stop",
        } and event.quantity is not None:
            return _decimal(event.quantity)
    return _decimal(fallback_quantity)


def _gross_pnl(trade: VirtualTrade, price: float) -> float:
    quantity = trade.remaining_quantity if trade.remaining_quantity is not None else trade.quantity
    if trade.side == "long":
        return (price - trade.entry_price) * quantity
    return (trade.entry_price - price) * quantity


def _trade_result(pnl: Decimal | None) -> str:
    if pnl is None or pnl == 0:
        return "breakeven"
    return "win" if pnl > 0 else "loss"


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _optional_float(value: Any | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: Any | None) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value)


def _position_fee_estimate(sizing: Any) -> Decimal:
    position_size = _decimal(sizing.position_size_base)
    fee_per_unit = _decimal(sizing.estimated_entry_fee_per_unit) + _decimal(
        sizing.estimated_exit_fee_per_unit
    )
    return position_size * fee_per_unit


def _position_slippage_estimate(sizing: Any) -> Decimal:
    return _decimal(sizing.position_size_base) * _decimal(sizing.slippage_buffer_per_unit)


def _position_funding_buffer(sizing: Any) -> Decimal:
    return _decimal(sizing.position_size_base) * _decimal(getattr(sizing, "funding_buffer_per_unit", 0))


def _primary_risk_group(pair: MarketPair) -> str | None:
    groups = [
        group
        for group in pair.base_asset.risk_groups
        if group.is_primary
    ]
    if not groups:
        return None
    return groups[0].group_code


def _trade_with_lifecycle_trace(
    trade: VirtualTrade,
    *,
    signal_id: str,
    virtual_trade_id: str,
    risk_decision_id: str | None = None,
) -> VirtualTrade:
    trace = trade.lifecycle_trace.model_copy(
        update={
            "signal_id": signal_id,
            "virtual_trade_id": virtual_trade_id,
            "risk_decision_id": risk_decision_id or trade.lifecycle_trace.risk_decision_id,
            "audit_id": risk_decision_id or trade.lifecycle_trace.audit_id,
        }
    )
    execution = trade.execution
    if execution is not None:
        risk_decision = execution.risk_decision
        if risk_decision is not None:
            risk_decision = risk_decision.model_copy(
                update={
                    "lifecycle_trace": risk_decision.lifecycle_trace.model_copy(
                        update={
                            "signal_id": signal_id,
                            "virtual_trade_id": virtual_trade_id,
                            "risk_decision_id": risk_decision_id
                            or risk_decision.lifecycle_trace.risk_decision_id,
                            "audit_id": risk_decision_id
                            or risk_decision.lifecycle_trace.audit_id,
                        }
                    )
                }
            )
        execution = execution.model_copy(
            update={
                "lifecycle_trace": trace,
                "risk_decision": risk_decision,
            }
        )
    return trade.model_copy(update={"lifecycle_trace": trace, "execution": execution})


def _risk_lifecycle_trace(
    decision: Any,
    *,
    risk_decision_id: str | None,
    signal_id: str,
    virtual_trade_id: str,
) -> dict[str, Any]:
    trace = decision.lifecycle_trace.model_dump(mode="json", exclude_none=True)
    trace.update(
        {
            "signal_id": signal_id,
            "virtual_trade_id": virtual_trade_id,
        }
    )
    if risk_decision_id is not None:
        trace["risk_decision_id"] = risk_decision_id
        trace["audit_id"] = risk_decision_id
    return trace


def _snapshot_with_lifecycle_trace(snapshot: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    updated = dict(snapshot)
    updated["lifecycle_trace"] = trace
    return updated


def _parse_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError:
        return None
