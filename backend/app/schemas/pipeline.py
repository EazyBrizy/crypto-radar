from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.candle import Timeframe
from app.schemas.market import Features
from app.schemas.signal import RadarSignal
from app.schemas.trade import RealTrade, VirtualTrade

PipelineStage = Literal[
    "Exchange WS",
    "Raw Market Event",
    "Normalizer",
    "Kafka Topic: market.trades",
    "Kafka Topic: market.orderbook",
    "Kafka Topic: market.candles",
    "Feature Builder",
    "Strategy Engine",
    "Signal Scoring",
    "Signal Store",
    "Frontend Radar",
]

KafkaTopic = Literal[
    "market.trades.raw",
    "market.orderbook.raw",
    "market.candles.raw",
    "market.liquidations.raw",
    "market.trades.normalized",
    "market.orderbook.normalized",
    "market.candles.normalized",
    "features.symbol.1m",
    "features.symbol.5m",
    "signals.created",
    "signals.updated",
    "signals.expired",
    "trades.virtual.opened",
    "trades.virtual.closed",
    "trades.real.synced",
    "ai.review.requested",
    "ai.review.completed",
]

MarketEventType = Literal["trade", "orderbook", "candle", "liquidation"]
NormalizedMarketEventType = Literal["trade", "orderbook", "candle"]
TradeSide = Literal["buy", "sell", "unknown"]
AiReviewEntityType = Literal["signal", "trade"]

PIPELINE_STAGES: tuple[PipelineStage, ...] = (
    "Exchange WS",
    "Raw Market Event",
    "Normalizer",
    "Kafka Topic: market.trades",
    "Kafka Topic: market.orderbook",
    "Kafka Topic: market.candles",
    "Feature Builder",
    "Strategy Engine",
    "Signal Scoring",
    "Signal Store",
    "Frontend Radar",
)

KAFKA_TOPICS: tuple[KafkaTopic, ...] = (
    "market.trades.raw",
    "market.orderbook.raw",
    "market.candles.raw",
    "market.liquidations.raw",
    "market.trades.normalized",
    "market.orderbook.normalized",
    "market.candles.normalized",
    "features.symbol.1m",
    "features.symbol.5m",
    "signals.created",
    "signals.updated",
    "signals.expired",
    "trades.virtual.opened",
    "trades.virtual.closed",
    "trades.real.synced",
    "ai.review.requested",
    "ai.review.completed",
)

RAW_TOPIC_BY_EVENT_TYPE: dict[MarketEventType, KafkaTopic] = {
    "trade": "market.trades.raw",
    "orderbook": "market.orderbook.raw",
    "candle": "market.candles.raw",
    "liquidation": "market.liquidations.raw",
}

NORMALIZED_TOPIC_BY_EVENT_TYPE: dict[NormalizedMarketEventType, KafkaTopic] = {
    "trade": "market.trades.normalized",
    "orderbook": "market.orderbook.normalized",
    "candle": "market.candles.normalized",
}

FEATURE_TOPIC_BY_TIMEFRAME: dict[Literal["1m", "5m"], KafkaTopic] = {
    "1m": "features.symbol.1m",
    "5m": "features.symbol.5m",
}


class PipelineEnvelope(BaseModel):
    topic: KafkaTopic
    key: str
    emitted_at: int
    trace_id: Optional[str] = None


class RawMarketEvent(PipelineEnvelope):
    exchange: str
    source_symbol: str
    event_type: MarketEventType
    source_channel: Optional[str] = None
    received_at: int
    payload: dict[str, Any] = Field(default_factory=dict)


class OrderBookLevel(BaseModel):
    price: float = Field(..., gt=0)
    quantity: float = Field(..., ge=0)


class NormalizedTradeEvent(PipelineEnvelope):
    topic: Literal["market.trades.normalized"] = "market.trades.normalized"
    exchange: str
    symbol: str
    event_type: Literal["trade"] = "trade"
    trade_id: Optional[str] = None
    price: float = Field(..., gt=0)
    volume: float = Field(..., ge=0)
    side: TradeSide = "unknown"
    event_time: int


class NormalizedOrderBookEvent(PipelineEnvelope):
    topic: Literal["market.orderbook.normalized"] = "market.orderbook.normalized"
    exchange: str
    symbol: str
    event_type: Literal["orderbook"] = "orderbook"
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    sequence: Optional[int] = None
    event_time: int


class NormalizedCandleEvent(PipelineEnvelope):
    topic: Literal["market.candles.normalized"] = "market.candles.normalized"
    exchange: str
    symbol: str
    event_type: Literal["candle"] = "candle"
    timeframe: Timeframe
    open_time: int
    close_time: int
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    volume: float = Field(..., ge=0)
    trades: int = Field(default=0, ge=0)
    is_closed: bool = False


class FeatureEvent(PipelineEnvelope):
    topic: Literal["features.symbol.1m", "features.symbol.5m"]
    exchange: str
    symbol: str
    timeframe: Literal["1m", "5m"]
    features: Features


class SignalLifecycleEvent(PipelineEnvelope):
    topic: Literal["signals.created", "signals.updated", "signals.expired"]
    signal: RadarSignal


class VirtualTradeLifecycleEvent(PipelineEnvelope):
    topic: Literal["trades.virtual.opened", "trades.virtual.closed"]
    trade: VirtualTrade


class RealTradeSyncedEvent(PipelineEnvelope):
    topic: Literal["trades.real.synced"] = "trades.real.synced"
    trade: RealTrade


class AiReviewEvent(PipelineEnvelope):
    topic: Literal["ai.review.requested", "ai.review.completed"]
    entity_type: AiReviewEntityType
    entity_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


def raw_topic_for(event_type: MarketEventType) -> KafkaTopic:
    return RAW_TOPIC_BY_EVENT_TYPE[event_type]


def normalized_topic_for(event_type: NormalizedMarketEventType) -> KafkaTopic:
    return NORMALIZED_TOPIC_BY_EVENT_TYPE[event_type]
