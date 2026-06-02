from typing import Literal, Optional

from pydantic import BaseModel, Field

CandleState = Literal["open", "closed"]


class MarketData(BaseModel):
    exchange: str = "bybit"
    symbol: str
    price: float
    volume: float
    timestamp: int


class OrderBookLevel(BaseModel):
    price: float = Field(..., gt=0)
    quantity: float = Field(..., ge=0)


class OrderBookSnapshot(BaseModel):
    exchange: str = "bybit"
    symbol: str
    category: Optional[str] = None
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    timestamp: int = Field(..., ge=0)
    ts: Optional[str] = None
    source: str
    spread_bps: Optional[float] = Field(default=None, ge=0)
    bid_depth_usd_0_1_pct: float = Field(default=0.0, ge=0)
    ask_depth_usd_0_1_pct: float = Field(default=0.0, ge=0)
    bid_depth_usd_0_5_pct: float = Field(default=0.0, ge=0)
    ask_depth_usd_0_5_pct: float = Field(default=0.0, ge=0)
    bid_depth_usd_1_pct: float = Field(default=0.0, ge=0)
    ask_depth_usd_1_pct: float = Field(default=0.0, ge=0)


class Features(BaseModel):
    exchange: str = "bybit"
    symbol: str
    timeframe: str = "stream"
    timestamp: int
    candle_state: CandleState = "closed"

    price: float
    open: float
    high: float
    low: float
    close: float
    price_change_1m: float
    previous_open: Optional[float] = None
    previous_high: Optional[float] = None
    previous_low: Optional[float] = None
    previous_close: Optional[float] = None
    previous_volume: Optional[float] = None

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
    session_high: Optional[float] = None
    session_low: Optional[float] = None
    previous_day_high: Optional[float] = None
    previous_day_low: Optional[float] = None
    rsi_14: Optional[float] = None
    atr_14: Optional[float] = None
    atr_sma_50: Optional[float] = None
    adx: Optional[float] = None
    adx_rising: bool = False
    adx_slope_5: Optional[float] = None
    adx_rising_bars: int = 0

    ema_200_cross_count_50: int = 0
    ema_200_near_ratio_50: Optional[float] = None
    ema_200_slope_atr_20: Optional[float] = None
    ema_200_chop_score: Optional[float] = None

    bb_width: Optional[float] = None
    bb_width_percentile: Optional[float] = None
    donchian_high_20: Optional[float] = None
    donchian_low_20: Optional[float] = None
    range_20: Optional[float] = None
    range_50_average: Optional[float] = None
    range_20_atr: Optional[float] = None

    swing_high: Optional[float] = None
    swing_low: Optional[float] = None
    swing_high_touch_count: int = 0
    swing_low_touch_count: int = 0
    swing_high_volume_score: Optional[float] = None
    swing_low_volume_score: Optional[float] = None
    swing_high_age_candles: Optional[int] = None
    swing_low_age_candles: Optional[int] = None
    candle_bullish: bool = False
    candle_bearish: bool = False
    upper_wick_ratio: Optional[float] = None
    lower_wick_ratio: Optional[float] = None
    atr_increasing: bool = False

    oi_change: Optional[float] = None
    funding_rate: Optional[float] = None
