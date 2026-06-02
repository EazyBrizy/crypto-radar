from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.schemas.market import (
    AlphaMarketContext,
    DeltaFeatures,
    DeltaDivergence,
    DepthWallSide,
    DerivativeAlphaFeatures,
    Features,
    LiquidityPoolFeatures,
    LiquidityPoolSide,
    OrderBookAlphaFeatures,
    OrderBookSnapshot,
    RecentTrade,
    RecentTradesAggregate,
    VwapAcceptance,
    VwapReactionFeatures,
)
from app.services.derivative_market import DerivativeMarketSnapshot
from app.services.market_persistence import orderbook_hot_key

logger = logging.getLogger(__name__)

EPSILON = 1e-12
DEFAULT_FUNDING_PRESSURE_THRESHOLD = 0.0015
DEFAULT_DEPTH_WALL_MIN_SHARE = 0.30


class RedisHotClient(Protocol):
    def get(self, name: str) -> object:
        ...


class AlphaMarketContextService:
    """Builds strategy-readable alpha context from already available market data."""

    def __init__(
        self,
        *,
        redis_client_factory: Callable[[], RedisHotClient] = get_redis_client,
        orderbook_max_age_seconds: int | None = None,
        funding_pressure_threshold: float = DEFAULT_FUNDING_PRESSURE_THRESHOLD,
        depth_wall_min_share: float = DEFAULT_DEPTH_WALL_MIN_SHARE,
    ) -> None:
        self._redis_client_factory = redis_client_factory
        self._orderbook_max_age_seconds = int(orderbook_max_age_seconds or settings.orderbook_snapshot_ttl_seconds)
        self._funding_pressure_threshold = abs(funding_pressure_threshold)
        self._depth_wall_min_share = max(0.0, min(1.0, depth_wall_min_share))

    def build_context(
        self,
        *,
        features: Features,
        recent_trades: Sequence[RecentTrade] | None = None,
        orderbook: OrderBookSnapshot | None = None,
        derivative_snapshot: DerivativeMarketSnapshot | None = None,
        derivative_history: Sequence[DerivativeMarketSnapshot] | None = None,
        previous_context: AlphaMarketContext | None = None,
    ) -> AlphaMarketContext:
        data_quality = _empty_data_quality()

        aggregate = self.aggregate_recent_trades(recent_trades or ())
        _merge_quality(data_quality, aggregate.metadata)

        delta = self.delta_features(
            features=features,
            aggregate=aggregate,
            previous_context=previous_context,
        )

        orderbook_snapshot = orderbook or self._read_hot_orderbook(
            exchange=features.exchange,
            symbol=features.symbol,
            data_quality=data_quality,
        )
        orderbook_features = self.orderbook_alpha_features(
            orderbook_snapshot,
            data_quality=data_quality,
        )

        derivative_features = self.derivative_alpha_features(
            derivative_snapshot=derivative_snapshot,
            derivative_history=derivative_history or (),
            data_quality=data_quality,
        )
        liquidity_pools = self.liquidity_pool_features(features)
        vwap = self.vwap_reaction_features(features)

        return AlphaMarketContext(
            symbol=features.symbol,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            buy_volume=delta.buy_volume,
            sell_volume=delta.sell_volume,
            aggressive_delta=delta.aggressive_delta,
            cvd=delta.cvd,
            cvd_change=delta.cvd_change,
            delta_divergence=delta.delta_divergence,
            oi_delta_5m=derivative_features.oi_delta_5m,
            oi_delta_15m=derivative_features.oi_delta_15m,
            funding_rate=derivative_features.funding_rate,
            funding_pressure=derivative_features.funding_pressure,
            liquidation_proximity=derivative_features.liquidation_proximity,
            liquidation_clusters=derivative_features.liquidation_clusters,
            orderbook_imbalance=orderbook_features.orderbook_imbalance,
            bid_depth_usd=orderbook_features.bid_depth_usd,
            ask_depth_usd=orderbook_features.ask_depth_usd,
            depth_wall_side=orderbook_features.depth_wall_side,
            depth_wall_price=orderbook_features.depth_wall_price,
            absorption_score=orderbook_features.absorption_score,
            sweep_through_book=orderbook_features.sweep_through_book,
            session_liquidity_pools=liquidity_pools,
            pdh_pdl_reaction=vwap.pdh_pdl_reaction,
            vwap_deviation=vwap.vwap_deviation,
            vwap_acceptance=vwap.vwap_acceptance,
            data_quality=_finalize_data_quality(data_quality),
        )

    def aggregate_recent_trades(
        self,
        trades: Sequence[RecentTrade],
    ) -> RecentTradesAggregate:
        metadata = _empty_data_quality()
        total_volume = sum(trade.quantity for trade in trades)
        if not trades:
            _mark_missing(metadata, "recent_trades")
            return RecentTradesAggregate(
                trades_count=0,
                total_volume=0.0,
                metadata=_finalize_data_quality(metadata),
            )

        sided_trades = [trade for trade in trades if trade.side in {"buy", "sell"}]
        if not sided_trades:
            _mark_missing(metadata, "recent_trade_side")
            return RecentTradesAggregate(
                trades_count=len(trades),
                total_volume=total_volume,
                side_available=False,
                metadata=_finalize_data_quality(metadata),
            )
        if len(sided_trades) < len(trades):
            _mark_missing(metadata, "recent_trade_side")

        buy_volume = sum(trade.quantity for trade in sided_trades if trade.side == "buy")
        sell_volume = sum(trade.quantity for trade in sided_trades if trade.side == "sell")
        aggressive_delta = buy_volume - sell_volume
        _mark_available(metadata, "recent_trades")
        return RecentTradesAggregate(
            trades_count=len(trades),
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            total_volume=total_volume,
            aggressive_delta=aggressive_delta,
            cvd=aggressive_delta,
            side_available=True,
            metadata={
                **_finalize_data_quality(metadata),
                "sided_trades_count": len(sided_trades),
            },
        )

    def delta_features(
        self,
        *,
        features: Features,
        aggregate: RecentTradesAggregate,
        previous_context: AlphaMarketContext | None = None,
    ) -> DeltaFeatures:
        cvd_change = None
        if aggregate.cvd is not None and previous_context is not None and previous_context.cvd is not None:
            cvd_change = aggregate.cvd - previous_context.cvd
        return DeltaFeatures(
            buy_volume=aggregate.buy_volume,
            sell_volume=aggregate.sell_volume,
            aggressive_delta=aggregate.aggressive_delta,
            cvd=aggregate.cvd,
            cvd_change=cvd_change,
            delta_divergence=_delta_divergence(features, aggregate, previous_context),
        )

    def orderbook_alpha_features(
        self,
        orderbook: OrderBookSnapshot | None,
        *,
        data_quality: dict[str, Any] | None = None,
    ) -> OrderBookAlphaFeatures:
        quality = data_quality if data_quality is not None else _empty_data_quality()
        if orderbook is None:
            _mark_missing(quality, "orderbook_l2")
            return OrderBookAlphaFeatures(
                depth_wall_side="none",
                metadata=_finalize_data_quality(quality),
            )
        if not orderbook.bids or not orderbook.asks:
            _mark_missing(quality, "orderbook_l2")
            return OrderBookAlphaFeatures(
                depth_wall_side="none",
                metadata=_finalize_data_quality(quality),
            )

        _mark_available(quality, "orderbook_l2")
        bid_depth = orderbook.bid_depth_usd_0_5_pct
        ask_depth = orderbook.ask_depth_usd_0_5_pct
        denominator = max(bid_depth + ask_depth, EPSILON)
        imbalance = (bid_depth - ask_depth) / denominator
        depth_wall_side, depth_wall_price = self._depth_wall(orderbook)
        return OrderBookAlphaFeatures(
            orderbook_imbalance=imbalance,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
            depth_wall_side=depth_wall_side,
            depth_wall_price=depth_wall_price,
            absorption_score=abs(imbalance),
            sweep_through_book=None,
            metadata=_finalize_data_quality(quality),
        )

    def derivative_alpha_features(
        self,
        *,
        derivative_snapshot: DerivativeMarketSnapshot | None,
        derivative_history: Sequence[DerivativeMarketSnapshot],
        data_quality: dict[str, Any] | None = None,
    ) -> DerivativeAlphaFeatures:
        quality = data_quality if data_quality is not None else _empty_data_quality()
        if derivative_snapshot is None:
            _mark_missing(quality, "derivative_snapshot")
            _mark_missing(quality, "derivative_history")
            return DerivativeAlphaFeatures(metadata=_finalize_data_quality(quality))

        _mark_available(quality, "derivative_snapshot")
        if derivative_history:
            _mark_available(quality, "derivative_history")
        else:
            _mark_missing(quality, "derivative_history")

        oi_delta_15m = _open_interest_delta(derivative_snapshot, derivative_history)
        return DerivativeAlphaFeatures(
            oi_delta_5m=derivative_snapshot.oi_change,
            oi_delta_15m=oi_delta_15m,
            funding_rate=derivative_snapshot.funding_rate,
            funding_pressure=_funding_pressure(
                derivative_snapshot.funding_rate,
                self._funding_pressure_threshold,
            ),
            liquidation_proximity=None,
            liquidation_clusters=None,
            metadata={
                **_finalize_data_quality(quality),
                "open_interest": derivative_snapshot.open_interest,
                "open_interest_value": derivative_snapshot.open_interest_value,
                "source": derivative_snapshot.source,
            },
        )

    def liquidity_pool_features(self, features: Features) -> list[LiquidityPoolFeatures]:
        candidates: tuple[tuple[str, str, float | None, float | None], ...] = (
            ("session_high", "session", features.session_high, None),
            ("session_low", "session", features.session_low, None),
            ("previous_day_high", "previous_day", features.previous_day_high, None),
            ("previous_day_low", "previous_day", features.previous_day_low, None),
            ("swing_high", "swing", features.swing_high, features.swing_high_volume_score),
            ("swing_low", "swing", features.swing_low, features.swing_low_volume_score),
            ("range_high", "donchian", features.donchian_high_20, None),
            ("range_low", "donchian", features.donchian_low_20, None),
        )
        pools: list[LiquidityPoolFeatures] = []
        seen: set[tuple[str, float]] = set()
        for name, source, price, strength in candidates:
            if price is None or price <= 0:
                continue
            key = (source, round(price, 8))
            if key in seen:
                continue
            seen.add(key)
            pools.append(
                LiquidityPoolFeatures(
                    name=name,
                    price=price,
                    side=_pool_side(features.close, price),
                    source=source,
                    distance_pct=_distance_pct(features.close, price),
                    strength=strength,
                )
            )
        return pools

    def vwap_reaction_features(self, features: Features) -> VwapReactionFeatures:
        return VwapReactionFeatures(
            pdh_pdl_reaction=_pdh_pdl_reaction(features),
            vwap_deviation=_vwap_deviation(features),
            vwap_acceptance=_vwap_acceptance(features),
        )

    def _read_hot_orderbook(
        self,
        *,
        exchange: str,
        symbol: str,
        data_quality: dict[str, Any],
    ) -> OrderBookSnapshot | None:
        key = orderbook_hot_key(exchange=exchange, symbol=symbol)
        try:
            raw = self._redis_client_factory().get(key)
        except Exception as exc:
            logger.warning("Alpha orderbook hot snapshot read failed for %s: %s", key, exc)
            _mark_missing(data_quality, "orderbook_l2")
            return None
        if raw is None:
            _mark_missing(data_quality, "orderbook_l2")
            return None

        payload = raw.decode("utf8") if isinstance(raw, bytes) else str(raw)
        try:
            snapshot = OrderBookSnapshot.model_validate(json.loads(payload))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Alpha orderbook hot snapshot is malformed for %s: %s", key, exc)
            _mark_missing(data_quality, "orderbook_l2")
            return None
        if _is_orderbook_stale(snapshot, self._orderbook_max_age_seconds):
            _mark_missing(data_quality, "orderbook_l2_stale")
            return None
        return snapshot

    def _depth_wall(self, orderbook: OrderBookSnapshot) -> tuple[DepthWallSide, float | None]:
        wall_candidates: list[tuple[DepthWallSide, float, float]] = []
        for level in orderbook.bids:
            wall_candidates.append(("bid", level.price, level.price * level.quantity))
        for level in orderbook.asks:
            wall_candidates.append(("ask", level.price, level.price * level.quantity))
        if not wall_candidates:
            return "none", None
        total_notional = sum(candidate[2] for candidate in wall_candidates)
        if total_notional <= 0:
            return "none", None
        side, price, notional = max(wall_candidates, key=lambda candidate: candidate[2])
        if notional / total_notional < self._depth_wall_min_share:
            return "none", None
        return side, price


def recent_trade_from_market_data(data: Any) -> RecentTrade:
    return RecentTrade(
        exchange=str(data.exchange),
        symbol=str(data.symbol),
        price=float(data.price),
        quantity=float(data.volume),
        timestamp=int(data.timestamp),
        side=getattr(data, "side", None),
        trade_id=getattr(data, "trade_id", None),
        is_buyer_maker=getattr(data, "is_buyer_maker", None),
    )


def _delta_divergence(
    features: Features,
    aggregate: RecentTradesAggregate,
    previous_context: AlphaMarketContext | None,
) -> DeltaDivergence | None:
    if aggregate.cvd is None or previous_context is None or previous_context.cvd is None:
        return None
    if features.previous_low is not None and features.low < features.previous_low and aggregate.cvd >= previous_context.cvd:
        return "bullish_divergence"
    if features.previous_high is not None and features.high > features.previous_high and aggregate.cvd <= previous_context.cvd:
        return "bearish_divergence"
    return None


def _open_interest_delta(
    snapshot: DerivativeMarketSnapshot,
    history: Sequence[DerivativeMarketSnapshot],
) -> float | None:
    current = snapshot.open_interest
    if current is None or current <= 0:
        return None
    candidates = [item for item in history if item.open_interest is not None and item.open_interest > 0]
    if not candidates:
        return None
    previous = candidates[0].open_interest
    if previous is None or previous <= 0:
        return None
    return (current - previous) / previous


def _funding_pressure(funding_rate: float | None, threshold: float) -> float | None:
    if funding_rate is None or threshold <= 0:
        return None
    return funding_rate / threshold


def _pool_side(close: float, price: float) -> LiquidityPoolSide:
    if price > close:
        return "above"
    if price < close:
        return "below"
    return "neutral"


def _distance_pct(close: float, price: float) -> float | None:
    if close <= 0:
        return None
    return abs(price - close) / abs(close) * 100


def _pdh_pdl_reaction(features: Features) -> str | None:
    if features.previous_day_high is not None:
        if features.high >= features.previous_day_high and features.close < features.previous_day_high:
            return "rejecting_pdh"
        if features.close > features.previous_day_high:
            return "accepting_above_pdh"
    if features.previous_day_low is not None:
        if features.low <= features.previous_day_low and features.close > features.previous_day_low:
            return "rejecting_pdl"
        if features.close < features.previous_day_low:
            return "accepting_below_pdl"
    return None


def _vwap_deviation(features: Features) -> float | None:
    if features.vwap is None or features.vwap <= 0:
        return None
    return (features.close - features.vwap) / features.vwap


def _vwap_acceptance(features: Features) -> VwapAcceptance | None:
    deviation = _vwap_deviation(features)
    if deviation is None:
        return None
    if abs(deviation) <= 0.001:
        return "at_vwap"
    if deviation > 0:
        return "above_vwap"
    return "below_vwap"


def _is_orderbook_stale(snapshot: OrderBookSnapshot, max_age_seconds: int) -> bool:
    if max_age_seconds <= 0:
        return False
    return (int(time.time() * 1000) - snapshot.timestamp) / 1000 > max_age_seconds


def _empty_data_quality() -> dict[str, Any]:
    return {
        "available_sources": [],
        "missing_sources": [],
        "warnings": [],
    }


def _mark_available(data_quality: dict[str, Any], source: str) -> None:
    _append_unique(data_quality, "available_sources", source)


def _mark_missing(data_quality: dict[str, Any], source: str) -> None:
    _append_unique(data_quality, "missing_sources", source)


def _append_unique(data_quality: dict[str, Any], key: str, value: str) -> None:
    values = data_quality.setdefault(key, [])
    if isinstance(values, list) and value not in values:
        values.append(value)


def _merge_quality(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in ("available_sources", "missing_sources", "warnings"):
        values = source.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str):
                _append_unique(target, key, value)


def _finalize_data_quality(data_quality: dict[str, Any]) -> dict[str, Any]:
    result = dict(data_quality)
    for key in ("available_sources", "missing_sources", "warnings"):
        values = result.get(key)
        result[key] = list(dict.fromkeys(str(value) for value in values)) if isinstance(values, list) else []
    result["source"] = "alpha_market_context"
    return result


alpha_market_context_service = AlphaMarketContextService()
