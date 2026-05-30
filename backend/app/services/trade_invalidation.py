from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features
from app.schemas.signal import RadarSignal, SignalInvalidationSnapshot
from app.schemas.trade import TradeInvalidationAlert, TradeJournalEntry, VirtualTrade
from app.services.candle_service import candle_service
from app.services.feature_engine import FeatureEngine
from app.services.signal_service import signal_service


class SignalLookup(Protocol):
    def get_signal(self, signal_id: str) -> RadarSignal | None:
        ...


class CandleLookup(Protocol):
    def list_candles(
        self,
        exchange: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        include_open: bool = True,
        limit: int = 100,
    ) -> list[OHLCVCandle]:
        ...


TradeLike = VirtualTrade | TradeJournalEntry


class TradeInvalidationService:
    def __init__(
        self,
        *,
        signals: SignalLookup | None = None,
        candles: CandleLookup | None = None,
        feature_engine: FeatureEngine | None = None,
    ) -> None:
        self._signals = signals or signal_service
        self._candles = candles or candle_service
        self._feature_engine = feature_engine or FeatureEngine()

    def evaluate_trade(self, trade: TradeLike) -> TradeInvalidationAlert:
        detected_at = datetime.now(timezone.utc)
        signal = self._signal_for_trade(trade)
        snapshot = signal.invalidation if signal is not None else None
        features = self._latest_features(trade)
        current_price = features.close if features is not None else trade.current_price

        if trade.status != "open":
            return self._alert(
                trade=trade,
                snapshot=snapshot,
                detected_at=detected_at,
                current_price=current_price,
                status="unavailable",
                reason="Trade is not open",
                metadata={"data_status": "trade_closed"},
            )

        if snapshot is None:
            return self._alert(
                trade=trade,
                snapshot=None,
                detected_at=detected_at,
                current_price=current_price,
                status="unavailable",
                reason="Signal invalidation plan is unavailable",
                metadata={"data_status": "missing_signal_invalidation"},
            )

        if features is None:
            return self._alert(
                trade=trade,
                snapshot=snapshot,
                detected_at=detected_at,
                current_price=current_price,
                status="unavailable",
                reason="Not enough candle data to evaluate logical invalidation",
                metadata={"data_status": "missing_candles", **snapshot.metadata},
            )

        triggered = self._triggered_conditions(trade, snapshot, features)
        latest_metadata = {
            **snapshot.metadata,
            "data_status": "evaluated",
            "latest_close": features.close,
            "latest_open": features.open,
            "latest_high": features.high,
            "latest_low": features.low,
            "latest_volume_spike": features.volume_spike,
            "latest_ema_50": features.ema_50,
            "latest_rsi_14": features.rsi_14,
            "latest_swing_high": features.swing_high,
            "latest_swing_low": features.swing_low,
        }
        if not triggered:
            return self._alert(
                trade=trade,
                snapshot=snapshot,
                detected_at=detected_at,
                current_price=current_price,
                metadata=latest_metadata,
            )

        return self._alert(
            trade=trade,
            snapshot=snapshot,
            detected_at=detected_at,
            current_price=current_price,
            status="invalidated",
            invalidated=True,
            reason="; ".join(triggered),
            triggered_conditions=triggered,
            suggested_action="close_market_or_wait_stop",
            metadata=latest_metadata,
        )

    def _signal_for_trade(self, trade: TradeLike) -> RadarSignal | None:
        if not trade.signal_id:
            return None
        return self._signals.get_signal(trade.signal_id)

    def _latest_features(self, trade: TradeLike) -> Features | None:
        timeframe = _safe_timeframe(trade.timeframe)
        if timeframe is None:
            return None
        candles = self._candles.list_candles(
            exchange=trade.exchange,
            symbol=trade.symbol,
            timeframe=timeframe,
            include_open=True,
            limit=250,
        )
        return self._feature_engine.process_candles(candles)

    def _triggered_conditions(
        self,
        trade: TradeLike,
        snapshot: SignalInvalidationSnapshot,
        features: Features,
    ) -> list[str]:
        strategy = trade.strategy
        if strategy == "trend_pullback_continuation":
            return _trend_pullback_conditions(trade.side, snapshot, features)
        if strategy == "volatility_squeeze_breakout":
            return _squeeze_breakout_conditions(trade.side, snapshot, features)
        if strategy == "liquidity_sweep_reversal":
            return _liquidity_sweep_conditions(trade.side, snapshot, features)
        return _fallback_conditions(trade, snapshot, features)

    @staticmethod
    def _alert(
        *,
        trade: TradeLike,
        snapshot: SignalInvalidationSnapshot | None,
        detected_at: datetime,
        current_price: float,
        status: str = "valid",
        invalidated: bool = False,
        reason: str | None = None,
        triggered_conditions: list[str] | None = None,
        suggested_action: str = "none",
        metadata: dict[str, Any] | None = None,
    ) -> TradeInvalidationAlert:
        return TradeInvalidationAlert(
            trade_id=trade.id,
            signal_id=trade.signal_id,
            exchange=trade.exchange,
            symbol=trade.symbol,
            strategy=trade.strategy,
            timeframe=trade.timeframe,
            side=trade.side,
            status=status,
            invalidated=invalidated,
            reason=reason,
            triggered_conditions=triggered_conditions or [],
            watched_conditions=list(snapshot.conditions) if snapshot is not None else [],
            suggested_action=suggested_action,
            current_price=current_price,
            stop_loss=trade.stop_loss,
            invalidation_price=(snapshot.price or snapshot.hard_stop) if snapshot is not None else None,
            detected_at=detected_at,
            metadata=metadata or {},
        )


def _trend_pullback_conditions(
    side: str,
    snapshot: SignalInvalidationSnapshot,
    features: Features,
) -> list[str]:
    metadata = snapshot.metadata
    triggered: list[str] = []
    ema_50 = _number(features.ema_50, metadata.get("ema_50"))
    swing_low = _number(metadata.get("trend_invalidation_level"), metadata.get("swing_low"), features.swing_low)
    swing_high = _number(metadata.get("trend_invalidation_level"), metadata.get("swing_high"), features.swing_high)
    rsi_14 = features.rsi_14

    if side == "long":
        if ema_50 is not None and features.close < ema_50:
            triggered.append("Close below EMA50")
        if swing_low is not None and features.close < swing_low:
            triggered.append("Break below last swing low")
        rsi_long_min = _number(metadata.get("rsi_long_min")) or 45.0
        if rsi_14 is not None and rsi_14 < rsi_long_min:
            triggered.append("RSI loses the 45 zone")
        return triggered

    if ema_50 is not None and features.close > ema_50:
        triggered.append("Close above EMA50")
    if swing_high is not None and features.close > swing_high:
        triggered.append("Break above last swing high")
    rsi_short_max = _number(metadata.get("rsi_short_max")) or 55.0
    if rsi_14 is not None and rsi_14 > rsi_short_max:
        triggered.append("RSI reclaims the 55 zone")
    return triggered


def _squeeze_breakout_conditions(
    side: str,
    snapshot: SignalInvalidationSnapshot,
    features: Features,
) -> list[str]:
    metadata = snapshot.metadata
    triggered: list[str] = []
    signal_open = _number(metadata.get("signal_open"))
    volume_threshold = _number(metadata.get("volume_disappears_below")) or 1.0

    if side == "long":
        breakout_level = _number(metadata.get("breakout_level"), metadata.get("range_high"), features.donchian_high_20)
        if breakout_level is not None and features.close < breakout_level:
            triggered.append("Close returns inside the previous Donchian range")
        if signal_open is not None and features.close <= signal_open:
            triggered.append("Breakout candle is fully retraced")
        if features.volume_spike < volume_threshold and features.close <= features.open:
            triggered.append("Volume disappears after breakout")
        return triggered

    breakdown_level = _number(metadata.get("breakout_level"), metadata.get("range_low"), features.donchian_low_20)
    if breakdown_level is not None and features.close > breakdown_level:
        triggered.append("Close returns inside the previous Donchian range")
    if signal_open is not None and features.close >= signal_open:
        triggered.append("Breakdown candle is fully retraced")
    if features.volume_spike < volume_threshold and features.close >= features.open:
        triggered.append("Volume disappears after breakdown")
    return triggered


def _liquidity_sweep_conditions(
    side: str,
    snapshot: SignalInvalidationSnapshot,
    features: Features,
) -> list[str]:
    metadata = snapshot.metadata
    triggered: list[str] = []

    if side == "long":
        swept_low = _number(metadata.get("swept_low"), metadata.get("swept_level"), metadata.get("swing_low"), features.swing_low)
        reclaim_level = _number(metadata.get("reclaim_level"), swept_low)
        if swept_low is not None and features.close < swept_low:
            triggered.append("Close returns below swept low")
        if swept_low is not None and features.low < swept_low and reclaim_level is not None and features.close < reclaim_level:
            triggered.append("Sweep low is broken again")
        if reclaim_level is not None and features.close < reclaim_level and features.volume_spike < 1.0:
            triggered.append("Next candles fail to hold reclaim")
        return triggered

    swept_high = _number(metadata.get("swept_high"), metadata.get("swept_level"), metadata.get("swing_high"), features.swing_high)
    rejection_level = _number(metadata.get("rejection_level"), swept_high)
    if swept_high is not None and features.close > swept_high:
        triggered.append("Close returns above swept high")
    if swept_high is not None and features.high > swept_high and rejection_level is not None and features.close > rejection_level:
        triggered.append("Sweep high is broken again")
    if rejection_level is not None and features.close > rejection_level and features.volume_spike < 1.0:
        triggered.append("Next candles fail to hold rejection")
    return triggered


def _fallback_conditions(
    trade: TradeLike,
    snapshot: SignalInvalidationSnapshot,
    features: Features,
) -> list[str]:
    invalidation_price = _number(snapshot.price, snapshot.hard_stop, trade.stop_loss)
    if invalidation_price is None:
        return []
    if trade.side == "long" and features.close <= invalidation_price:
        return ["Signal stop is reached"]
    if trade.side == "short" and features.close >= invalidation_price:
        return ["Signal stop is reached"]
    return []


def _safe_timeframe(value: str) -> str | None:
    return value if value in {"1m", "5m", "15m", "1h", "4h", "1d"} else None


def _number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


trade_invalidation_service = TradeInvalidationService()
