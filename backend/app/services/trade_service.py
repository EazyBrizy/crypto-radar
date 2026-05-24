from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import uuid4

from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    CloseReason,
    CloseVirtualTradeRequest,
    ManualConfirmRequest,
    TradeResult,
    VirtualTrade,
)

MAX_STORED_TRADES = 500


class TradeService:
    """Хранит и обновляет виртуальные сделки для MVP manual workflow.

    Сейчас это in-memory журнал. Граница сервиса повторяет будущий Trade Journal
    из architectureproject.md и позволит вынести данные в PostgreSQL.
    """

    def __init__(self) -> None:
        self._virtual_trades: Dict[str, VirtualTrade] = {}
        self._trade_by_signal: Dict[str, str] = {}

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

    def get_virtual_trade(self, trade_id: str) -> Optional[VirtualTrade]:
        return self._virtual_trades.get(trade_id)

    def get_virtual_trade_by_signal(self, signal_id: str) -> Optional[VirtualTrade]:
        trade_id = self._trade_by_signal.get(signal_id)
        if trade_id is None:
            return None
        return self.get_virtual_trade(trade_id)

    def open_virtual_trade(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> VirtualTrade:
        existing = self.get_virtual_trade_by_signal(signal.id)
        if existing is not None:
            return existing
        open_user_positions = [
            trade
            for trade in self._virtual_trades.values()
            if trade.user_id == request.user_id and trade.status == "open"
        ]
        if len(open_user_positions) >= request.max_open_positions:
            raise ValueError("Достигнут лимит открытых виртуальных позиций")

        raw_entry = self._entry_price(signal)
        if signal.stop_loss is None:
            raise ValueError("У сигнала нет stop_loss для расчета риска")

        side = signal.direction
        entry_price = self._apply_entry_slippage(
            raw_entry,
            side,
            request.slippage_bps,
        )
        stop_loss = signal.stop_loss
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            raise ValueError("Некорректная дистанция до stop_loss")

        risk_amount = request.account_balance * request.risk_percent / 100
        risk_sized_usd = risk_amount / risk_per_unit * entry_price
        max_notional = request.account_balance * request.leverage
        size_usd = min(request.size_usd or risk_sized_usd, max_notional)
        quantity = size_usd / entry_price
        entry_fee = size_usd * request.fee_rate
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
            risk_percent=request.risk_percent,
            stop_loss=stop_loss,
            take_profit=[
                price
                for price in (signal.take_profit_1, signal.take_profit_2)
                if price is not None
            ],
            fees=entry_fee,
            slippage_bps=request.slippage_bps,
            opened_at=now,
            updated_at=now,
        )
        self._virtual_trades[trade.id] = trade
        self._trade_by_signal[signal.id] = trade.id
        self._trim_trades()
        return trade

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
        for trade in list(self._virtual_trades.values()):
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
        self._virtual_trades[trade.id] = updated
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

        slipped_exit = self._apply_exit_slippage(
            exit_price,
            trade.side,
            trade.slippage_bps,
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
        self._virtual_trades[trade.id] = updated
        return updated

    def _trim_trades(self) -> None:
        if len(self._virtual_trades) <= MAX_STORED_TRADES:
            return

        sorted_trades = sorted(
            self._virtual_trades.values(),
            key=lambda trade: trade.opened_at,
            reverse=True,
        )
        keep_ids = {trade.id for trade in sorted_trades[:MAX_STORED_TRADES]}
        self._virtual_trades = {
            trade_id: trade
            for trade_id, trade in self._virtual_trades.items()
            if trade_id in keep_ids
        }
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
