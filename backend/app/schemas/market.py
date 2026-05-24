from typing import Optional

from pydantic import BaseModel


class MarketData(BaseModel):
    symbol: str
    price: float
    volume: float
    timestamp: int


class Features(BaseModel):
    symbol: str
    timestamp: int

    price: float
    price_change_1m: float

    volume: float
    volume_spike: float

    volatility: float

    oi_change: Optional[float] = None
    funding_rate: Optional[float] = None
