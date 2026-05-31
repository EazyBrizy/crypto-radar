from typing import Optional

from pydantic import BaseModel


class MarketData(BaseModel):
    exchange: str = "bybit"
    symbol: str
    price: float
    volume: float
    timestamp: int


class Features(BaseModel):
    exchange: str = "bybit"
    symbol: str
    timeframe: str = "stream"
    timestamp: int

    price: float
    open: float
    high: float
    low: float
    close: float
    price_change_1m: float

    volume: float
    volume_spike: float
    volume_ma_20: float

    volatility: float
    history_length: int

    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    sma_20: Optional[float] = None
    vwap: Optional[float] = None
    rsi_14: Optional[float] = None
    atr_14: Optional[float] = None
    adx: Optional[float] = None
    adx_rising: bool = False

    bb_width: Optional[float] = None
    bb_width_percentile: Optional[float] = None
    donchian_high_20: Optional[float] = None
    donchian_low_20: Optional[float] = None

    swing_high: Optional[float] = None
    swing_low: Optional[float] = None
    candle_bullish: bool = False
    candle_bearish: bool = False
    upper_wick_ratio: Optional[float] = None
    lower_wick_ratio: Optional[float] = None
    atr_increasing: bool = False

    oi_change: Optional[float] = None
    funding_rate: Optional[float] = None
