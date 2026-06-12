from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.schemas.trade import CloseReason, VirtualTrade
from app.services.execution_ambiguity import (
    DEFAULT_VIRTUAL_EXECUTION_AMBIGUITY_POLICY,
    VirtualExecutionAmbiguityPolicy,
)
from app.services.virtual_trade_lifecycle import (
    TargetFillPrice,
    VirtualTradeLifecycleResult,
    apply_virtual_trade_candle,
    apply_virtual_trade_market_price,
    close_virtual_trade_lifecycle,
)


@dataclass(frozen=True)
class PositionManagementResult:
    trade: VirtualTrade
    realized_pnl_delta: float = 0.0
    closed: bool = False
    reason_code: str | None = None


class PositionManagementEngine:
    def apply_price(
        self,
        trade: VirtualTrade,
        *,
        price: float,
        now: datetime,
        target_fill_price: TargetFillPrice = "target",
    ) -> PositionManagementResult:
        return _result(
            apply_virtual_trade_market_price(
                trade,
                price,
                now,
                target_fill_price=target_fill_price,
            )
        )

    def apply_candle(
        self,
        trade: VirtualTrade,
        *,
        high: float,
        low: float,
        close: float,
        now: datetime,
        ambiguity_policy: VirtualExecutionAmbiguityPolicy | str | None = (
            DEFAULT_VIRTUAL_EXECUTION_AMBIGUITY_POLICY
        ),
        candle_open_time: int | None = None,
        candle_close_time: int | None = None,
    ) -> PositionManagementResult:
        return _result(
            apply_virtual_trade_candle(
                trade,
                high=high,
                low=low,
                close=close,
                now=now,
                ambiguity_policy=ambiguity_policy,
                candle_open_time=candle_open_time,
                candle_close_time=candle_close_time,
            )
        )

    def close(
        self,
        trade: VirtualTrade,
        *,
        exit_price: float,
        reason: CloseReason,
        now: datetime,
    ) -> PositionManagementResult:
        return _result(close_virtual_trade_lifecycle(trade, exit_price, reason, now))


def _result(result: VirtualTradeLifecycleResult) -> PositionManagementResult:
    return PositionManagementResult(
        trade=result.trade,
        realized_pnl_delta=result.realized_pnl_delta,
        closed=result.closed,
        reason_code=result.trade.close_reason,
    )


position_management_engine = PositionManagementEngine()
