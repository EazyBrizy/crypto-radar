from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

CandleState = Literal["open", "closed"]
TradeSide = Literal["buy", "sell"]
DepthWallSide = Literal["bid", "ask", "none"]
DeltaDivergence = Literal["bullish_divergence", "bearish_divergence"]
VwapAcceptance = Literal["above_vwap", "below_vwap", "at_vwap", "rejected_from_vwap"]
LiquidityPoolSide = Literal["above", "below", "neutral"]
OrderBookFreshnessStatus = Literal["fresh", "stale", "missing", "unknown"]
MarketUniverseLimit = Literal["top_100", "top_200", "top_500", "all"]


class MarketUniverseSyncRequest(BaseModel):
    exchange: str = "bybit"
    category: str = "linear"
    quote: str = "USDT"
    limit: MarketUniverseLimit = "top_200"
    sort: str = "turnover_24h_desc"
    persist: bool = True


class MarketUniversePairResponse(BaseModel):
    id: UUID
    exchange: str
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    category: str | None
    market_type: str | None
    turnover_24h: Decimal | None
    volume_24h: Decimal | None
    last_price: Decimal | None
    mark_price: Decimal | None
    bid_price: Decimal | None
    ask_price: Decimal | None
    spread_bps: Decimal | None
    funding_rate: Decimal | None
    liquidity_rank: int | None
    liquidity_tier: str | None
    synced_at: datetime | None


class MarketUniverseSyncResponse(BaseModel):
    exchange: str
    category: str
    quote: str
    requested_limit: MarketUniverseLimit
    synced_count: int
    total_available_count: int
    skipped_count: int
    synced_at: datetime
    warnings: list[str] = Field(default_factory=list)


class MarketData(BaseModel):
    exchange: str = "bybit"
    symbol: str
    price: float
    volume: float
    timestamp: int
    bid: Optional[float] = Field(default=None, gt=0)
    ask: Optional[float] = Field(default=None, gt=0)
    best_bid: Optional[float] = Field(default=None, gt=0)
    best_ask: Optional[float] = Field(default=None, gt=0)
    last: Optional[float] = Field(default=None, gt=0)
    side: Optional[TradeSide] = None
    trade_id: Optional[str] = None
    is_buyer_maker: Optional[bool] = None


class OrderBookLevel(BaseModel):
    price: float = Field(..., gt=0)
    quantity: float = Field(..., ge=0)


class OrderBookSnapshot(BaseModel):
    exchange: str = "bybit"
    symbol: str
    category: Optional[str] = None
    best_bid: Optional[float] = Field(default=None, gt=0)
    best_ask: Optional[float] = Field(default=None, gt=0)
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    timestamp: int = Field(..., ge=0)
    fetched_at: Optional[datetime] = None
    ts: Optional[str] = None
    freshness_status: OrderBookFreshnessStatus = "unknown"
    age_seconds: Optional[float] = Field(default=None, ge=0)
    source: str
    spread_bps: Optional[float] = Field(default=None, ge=0)
    bid_levels_count: int = Field(default=0, ge=0)
    ask_levels_count: int = Field(default=0, ge=0)
    depth_levels: int = Field(default=0, ge=0)
    bid_depth_usd_0_1_pct: float = Field(default=0.0, ge=0)
    ask_depth_usd_0_1_pct: float = Field(default=0.0, ge=0)
    bid_depth_usd_0_5_pct: float = Field(default=0.0, ge=0)
    ask_depth_usd_0_5_pct: float = Field(default=0.0, ge=0)
    bid_depth_usd_1_pct: float = Field(default=0.0, ge=0)
    ask_depth_usd_1_pct: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def populate_orderbook_derived_fields(self) -> "OrderBookSnapshot":
        if self.bids:
            self.best_bid = self.best_bid or self.bids[0].price
        if self.asks:
            self.best_ask = self.best_ask or self.asks[0].price
        self.bid_levels_count = len(self.bids)
        self.ask_levels_count = len(self.asks)
        self.depth_levels = self.bid_levels_count + self.ask_levels_count
        if self.fetched_at is None and self.timestamp > 0:
            self.fetched_at = datetime.fromtimestamp(
                self.timestamp / 1000,
                tz=timezone.utc,
            )
        return self


class RecentTrade(BaseModel):
    exchange: str = "bybit"
    symbol: str
    price: float = Field(..., gt=0)
    quantity: float = Field(..., ge=0)
    timestamp: int = Field(..., ge=0)
    side: Optional[TradeSide] = None
    trade_id: Optional[str] = None
    is_buyer_maker: Optional[bool] = None


class RecentTradesAggregate(BaseModel):
    trades_count: int = Field(default=0, ge=0)
    buy_volume: Optional[float] = Field(default=None, ge=0)
    sell_volume: Optional[float] = Field(default=None, ge=0)
    total_volume: float = Field(default=0.0, ge=0)
    aggressive_delta: Optional[float] = None
    cvd: Optional[float] = None
    side_available: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeltaFeatures(BaseModel):
    buy_volume: Optional[float] = Field(default=None, ge=0)
    sell_volume: Optional[float] = Field(default=None, ge=0)
    aggressive_delta: Optional[float] = None
    cvd: Optional[float] = None
    cvd_change: Optional[float] = None
    delta_divergence: Optional[DeltaDivergence] = None


class OrderBookAlphaFeatures(BaseModel):
    orderbook_imbalance: Optional[float] = None
    bid_depth_usd: Optional[float] = Field(default=None, ge=0)
    ask_depth_usd: Optional[float] = Field(default=None, ge=0)
    depth_wall_side: Optional[DepthWallSide] = None
    depth_wall_price: Optional[float] = Field(default=None, gt=0)
    absorption_score: Optional[float] = Field(default=None, ge=0)
    sweep_through_book: Optional[bool] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DerivativeAlphaFeatures(BaseModel):
    oi_delta_5m: Optional[float] = None
    oi_delta_15m: Optional[float] = None
    funding_rate: Optional[float] = None
    funding_pressure: Optional[float] = None
    liquidation_proximity: Optional[float] = None
    liquidation_clusters: Optional[list[dict[str, Any]]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LiquidityPoolFeatures(BaseModel):
    name: str
    price: float = Field(..., gt=0)
    side: LiquidityPoolSide
    source: str
    distance_pct: Optional[float] = None
    strength: Optional[float] = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VwapReactionFeatures(BaseModel):
    pdh_pdl_reaction: Optional[str] = None
    vwap_deviation: Optional[float] = None
    vwap_acceptance: Optional[VwapAcceptance] = None


class AlphaMarketContext(BaseModel):
    symbol: str
    timeframe: str
    timestamp: int
    buy_volume: Optional[float] = Field(default=None, ge=0)
    sell_volume: Optional[float] = Field(default=None, ge=0)
    aggressive_delta: Optional[float] = None
    cvd: Optional[float] = None
    cvd_change: Optional[float] = None
    delta_divergence: Optional[DeltaDivergence] = None
    oi_delta_5m: Optional[float] = None
    oi_delta_15m: Optional[float] = None
    funding_rate: Optional[float] = None
    funding_pressure: Optional[float] = None
    liquidation_proximity: Optional[float] = None
    liquidation_clusters: Optional[list[dict[str, Any]]] = None
    orderbook_imbalance: Optional[float] = None
    bid_depth_usd: Optional[float] = Field(default=None, ge=0)
    ask_depth_usd: Optional[float] = Field(default=None, ge=0)
    depth_wall_side: Optional[DepthWallSide] = None
    depth_wall_price: Optional[float] = Field(default=None, gt=0)
    absorption_score: Optional[float] = Field(default=None, ge=0)
    sweep_through_book: Optional[bool] = None
    session_liquidity_pools: list[LiquidityPoolFeatures] = Field(default_factory=list)
    pdh_pdl_reaction: Optional[str] = None
    vwap_deviation: Optional[float] = None
    vwap_acceptance: Optional[VwapAcceptance] = None
    data_quality: dict[str, Any] = Field(default_factory=dict)


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
