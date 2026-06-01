from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.schemas.market import MarketData
from app.schemas.trade import ExecutionPlannedOrder


class ExchangeAdapter(Protocol):
    async def get_symbols(self) -> list[str]:
        ...

    def stream_trades(self, symbols: list[str]) -> AsyncIterator[MarketData]:
        ...


class ExchangeExecutionAdapter(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def is_dry_run(self) -> bool:
        ...

    async def place_order(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        ...

    async def place_protective_stop(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        ...

    async def place_take_profit(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        ...

    async def cancel_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        ...

    async def get_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        ...

    async def get_position(
        self,
        *,
        exchange: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        ...


class DryRunExecutionAdapter:
    name = "dry_run"
    is_dry_run = True

    def __init__(self) -> None:
        self._orders: dict[tuple[str, str, str], ExecutionPlannedOrder] = {}

    async def place_order(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        return self._record(order)

    async def place_protective_stop(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        return self._record(order)

    async def place_take_profit(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        return self._record(order)

    async def cancel_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        order = await self.get_order(
            exchange=exchange,
            symbol=symbol,
            client_order_id=client_order_id,
        )
        if order is None:
            return None
        cancelled = order.model_copy(update={"status": "cancelled"})
        self._orders[_order_key(cancelled)] = cancelled
        return cancelled

    async def get_order(
        self,
        *,
        exchange: str,
        symbol: str,
        client_order_id: str,
    ) -> ExecutionPlannedOrder | None:
        return self._orders.get(
            (
                exchange.strip().lower(),
                symbol.strip().upper(),
                client_order_id,
            )
        )

    async def get_position(
        self,
        *,
        exchange: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        return None

    def _record(self, order: ExecutionPlannedOrder) -> ExecutionPlannedOrder:
        planned = order.model_copy(
            update={
                "status": "dry_run",
                "metadata": {**order.metadata, "dry_run": True},
            }
        )
        self._orders[_order_key(planned)] = planned
        return planned


def _order_key(order: ExecutionPlannedOrder) -> tuple[str, str, str]:
    return (
        order.exchange.strip().lower(),
        order.symbol.strip().upper(),
        order.client_order_id,
    )
