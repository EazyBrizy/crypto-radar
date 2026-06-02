from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.schemas.trade import CloseReason, TradeJournalEntry, TradeResult
from app.services.strategy_testing.schemas import StrategyTestTrade
from app.services.strategy_testing.stores import ClickHouseStrategyTestStore


BACKTEST_TAG = "backtest"


class StrategyTestJournalStore(Protocol):
    def list_journal_trades(
        self,
        *,
        run_id: UUID | None = None,
        tag: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[StrategyTestTrade]:
        ...

    def get_trade(self, trade_id: str) -> StrategyTestTrade | None:
        ...


class StrategyTestJournalAdapter:
    def __init__(self, store: ClickHouseStrategyTestStore | StrategyTestJournalStore | None = None) -> None:
        self._store = store or ClickHouseStrategyTestStore()

    def list_journal(
        self,
        run_id: UUID | None = None,
        tag: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[TradeJournalEntry]:
        trades = self._store.list_journal_trades(
            run_id=run_id,
            tag=tag,
            status=status,
            limit=limit,
        )
        return [
            entry
            for entry in (_strategy_test_trade_to_journal_entry(trade) for trade in trades)
            if _matches_journal_filters(entry, tag=tag, status=status, run_id=run_id)
        ]

    def get_entry(self, trade_id: str) -> TradeJournalEntry | None:
        trade = self._store.get_trade(trade_id)
        if trade is None:
            return None
        return _strategy_test_trade_to_journal_entry(trade)


def _strategy_test_trade_to_journal_entry(trade: StrategyTestTrade) -> TradeJournalEntry:
    entry_price = _decimal_to_float(trade.entry_price)
    exit_price = _optional_decimal_to_float(trade.exit_price)
    current_price = exit_price if exit_price is not None else entry_price
    size_usd = _numeric_from_snapshots(
        trade,
        ("size_usd", "notional", "position_size_usd", "requested_size_usd", "filled_size_usd"),
        default=0.0,
    )
    quantity = _numeric_from_snapshots(
        trade,
        ("quantity", "position_size_base", "position_size", "filled_quantity"),
        default=0.0,
    )
    status = "closed" if trade.exit_time is not None else "open"
    realized_pnl = _decimal_to_float(trade.pnl) if status == "closed" else 0.0
    unrealized_pnl = 0.0 if status == "closed" else _decimal_to_float(trade.pnl)

    return TradeJournalEntry(
        id=trade.trade_id,
        user_id=str(trade.user_id),
        signal_id=None,
        mode="virtual",
        source="backtest",
        tags=_backtest_tags(trade.tags),
        run_id=trade.run_id,
        exchange=trade.exchange,
        symbol=trade.symbol,
        strategy=trade.strategy_code,
        timeframe=trade.timeframe,
        side=_trade_side(trade.direction),
        entry_price=entry_price,
        current_price=current_price,
        exit_price=exit_price,
        size_usd=size_usd,
        quantity=quantity,
        initial_quantity=quantity,
        remaining_quantity=0.0 if status == "closed" else quantity,
        closed_quantity=quantity if status == "closed" else 0.0,
        initial_size_usd=size_usd,
        remaining_size_usd=0.0 if status == "closed" else size_usd,
        leverage=int(
            _numeric_from_snapshots(trade, ("leverage",), default=1.0)
        ),
        risk_percent=_numeric_from_snapshots(
            trade,
            ("risk_percent", "risk_per_trade_percent"),
            default=0.0,
        ),
        risk_amount=_numeric_from_snapshots(trade, ("risk_amount",), default=0.0),
        risk_reward=_risk_reward(trade),
        stop_loss=_optional_decimal_to_float(trade.stop_loss) or 0.0,
        take_profit=_target_prices(trade.targets),
        fees=_decimal_to_float(trade.fees),
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        slippage_bps=_decimal_to_float(trade.slippage),
        status=status,
        result=_trade_result(trade),
        close_reason=_close_reason(trade.close_reason),
        pnl=_decimal_to_float(trade.pnl),
        pnl_percent=trade.pnl_pct,
        mfe=trade.mfe_r or 0.0,
        mae=trade.mae_r or 0.0,
        opened_at=trade.entry_time,
        updated_at=trade.exit_time or trade.created_at,
        closed_at=trade.exit_time,
    )


def _matches_journal_filters(
    entry: TradeJournalEntry,
    *,
    tag: str | None,
    status: str | None,
    run_id: UUID | None,
) -> bool:
    if tag is not None and tag not in entry.tags:
        return False
    if status is not None and entry.status != status:
        return False
    if run_id is not None and entry.run_id != run_id:
        return False
    return True


def _trade_side(value: str) -> str:
    return "short" if value.strip().lower() == "short" else "long"


def _risk_reward(trade: StrategyTestTrade) -> float:
    if trade.selected_rr is not None:
        return float(trade.selected_rr)
    if trade.realized_r is not None:
        return float(trade.realized_r)
    return _numeric_from_snapshots(trade, ("risk_reward", "selected_rr"), default=0.0)


def _trade_result(trade: StrategyTestTrade) -> TradeResult:
    outcome = trade.outcome.strip().lower()
    if outcome in {"win", "loss", "breakeven"}:
        return outcome  # type: ignore[return-value]
    pnl = trade.pnl
    if pnl > 0:
        return "win"
    if pnl < 0:
        return "loss"
    return "breakeven"


def _close_reason(value: str) -> CloseReason | None:
    normalized = value.strip().lower()
    aliases = {
        "target": "take_profit",
        "tp": "take_profit",
        "takeprofit": "take_profit",
        "sl": "stop_loss",
        "stop": "stop_loss",
    }
    candidate = aliases.get(normalized, normalized)
    if candidate in {
        "take_profit",
        "stop_loss",
        "manual_close",
        "invalidation",
        "cancelled",
        "partial_take_profit",
        "breakeven_stop",
        "trailing_stop",
        "time_stop",
    }:
        return candidate  # type: ignore[return-value]
    return None


def _backtest_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in [BACKTEST_TAG, *tags]:
        value = str(tag).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _target_prices(targets: list[dict[str, Any]]) -> list[float]:
    prices: list[float] = []
    for target in targets:
        value = target.get("price")
        number = _optional_float(value)
        if number is not None:
            prices.append(number)
    return prices


def _numeric_from_snapshots(
    trade: StrategyTestTrade,
    keys: tuple[str, ...],
    *,
    default: float,
) -> float:
    for snapshot in (trade.trade_plan, trade.features_snapshot):
        value = _find_numeric(snapshot, keys)
        if value is not None:
            return value
    return default


def _find_numeric(value: Any, keys: tuple[str, ...]) -> float | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        number = _optional_float(value.get(key))
        if number is not None:
            return number
    for child in value.values():
        if isinstance(child, dict):
            number = _find_numeric(child, keys)
            if number is not None:
                return number
    return None


def _optional_decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return _decimal_to_float(value)


def _decimal_to_float(value: Decimal) -> float:
    return float(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
