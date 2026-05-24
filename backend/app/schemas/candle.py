from typing import Literal, Optional

from pydantic import BaseModel, Field

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
DEFAULT_TIMEFRAMES: list[Timeframe] = ["1m", "5m", "15m", "1h", "4h", "1d"]


class OHLCVCandle(BaseModel):
    exchange: str
    symbol: str
    timeframe: Timeframe
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int = 0
    is_closed: bool = False


class CandleResponse(BaseModel):
    candles: list[OHLCVCandle]


class RadarConfig(BaseModel):
    exchanges: list[str] = Field(default_factory=lambda: ["bybit"])
    symbols: list[str] = Field(default_factory=list)
    use_all_symbols: bool = False
    timeframes: list[Timeframe] = Field(default_factory=lambda: list(DEFAULT_TIMEFRAMES))


class RadarConfigUpdate(BaseModel):
    exchanges: Optional[list[str]] = None
    symbols: Optional[list[str]] = None
    use_all_symbols: Optional[bool] = None
    timeframes: Optional[list[Timeframe]] = None
