from collections.abc import AsyncIterator
from typing import Protocol

from app.schemas.market import MarketData


class ExchangeAdapter(Protocol):
    async def get_symbols(self) -> list[str]:
        ...

    def stream_trades(self, symbols: list[str]) -> AsyncIterator[MarketData]:
        ...
