from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.models.trade_invalidation import TradeInvalidationAction
from app.models.user import AppUser
from app.schemas.candle import OHLCVCandle
from app.schemas.market import Features
from app.schemas.signal import RadarSignal, SignalInvalidationSnapshot
from app.schemas.trade import TradeInvalidationAlert, TradeJournalEntry, TradeInvalidationUserAction, VirtualTrade
from app.services.candle_service import candle_service
from app.services.feature_engine import FeatureEngine
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import trade_invalidation_event
from app.services.signal_service import signal_service
from app.services.virtual_trading import virtual_trading_service

logger = logging.getLogger(__name__)


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


class OpenTradeLookup(Protocol):
    def list_trade_journal(
        self,
        mode: str | None = None,
        status: str | None = None,
        signal_id: str | None = None,
    ) -> list[TradeJournalEntry]:
        ...


@dataclass(frozen=True)
class TradeInvalidationActionRecord:
    action: TradeInvalidationUserAction
    created_at: datetime
    dismissed_at: datetime | None = None


class TradeInvalidationActionStore(Protocol):
    def latest_for_alert(self, alert: TradeInvalidationAlert) -> TradeInvalidationActionRecord | None:
        ...

    def record(
        self,
        alert: TradeInvalidationAlert,
        action: TradeInvalidationUserAction,
        *,
        user_id: str = "demo_user",
    ) -> TradeInvalidationActionRecord:
        ...


class PostgresTradeInvalidationActionStore:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def latest_for_alert(self, alert: TradeInvalidationAlert) -> TradeInvalidationActionRecord | None:
        if not alert.fingerprint:
            return None
        with self._session_factory() as session:
            record = session.scalars(
                select(TradeInvalidationAction)
                .where(
                    TradeInvalidationAction.trade_id == alert.trade_id,
                    TradeInvalidationAction.fingerprint == alert.fingerprint,
                )
                .order_by(TradeInvalidationAction.created_at.desc())
                .limit(1)
            ).first()
            return _action_record(record)

    def record(
        self,
        alert: TradeInvalidationAlert,
        action: TradeInvalidationUserAction,
        *,
        user_id: str = "demo_user",
    ) -> TradeInvalidationActionRecord:
        now = datetime.now(timezone.utc)
        fingerprint = alert.fingerprint or _alert_fingerprint(alert)
        with self._session_factory() as session:
            user = _resolve_user(session, user_id)
            record = TradeInvalidationAction(
                user_id=user.id if user is not None else None,
                trade_id=alert.trade_id,
                signal_id=_uuid_or_none(alert.signal_id),
                mode=alert.metadata.get("trade_mode") if alert.metadata.get("trade_mode") in {"virtual", "real"} else "virtual",
                action=action,
                fingerprint=fingerprint,
                reason=alert.reason,
                alert_snapshot=alert.model_copy(update={"fingerprint": fingerprint}).model_dump(mode="json"),
                dismissed_at=now if _dismisses_alert(action) else None,
                created_at=now,
            )
            session.add(record)
            session.commit()
            return TradeInvalidationActionRecord(
                action=action,
                created_at=record.created_at,
                dismissed_at=record.dismissed_at,
            )


class TradeInvalidationService:
    def __init__(
        self,
        *,
        signals: SignalLookup | None = None,
        candles: CandleLookup | None = None,
        feature_engine: FeatureEngine | None = None,
        actions: TradeInvalidationActionStore | None = None,
    ) -> None:
        self._signals = signals or signal_service
        self._candles = candles or candle_service
        self._feature_engine = feature_engine or FeatureEngine()
        self._actions = actions or PostgresTradeInvalidationActionStore()

    def evaluate_trade(self, trade: TradeLike) -> TradeInvalidationAlert:
        features = self._latest_features(trade)
        return self.evaluate_trade_with_features(trade, features)

    def evaluate_trade_with_features(self, trade: TradeLike, features: Features | None) -> TradeInvalidationAlert:
        detected_at = datetime.now(timezone.utc)
        signal = self._signal_for_trade(trade)
        snapshot = signal.invalidation if signal is not None else None
        current_price = features.close if features is not None else trade.current_price

        if trade.status != "open":
            return self._with_user_action(self._alert(
                trade=trade,
                snapshot=snapshot,
                detected_at=detected_at,
                current_price=current_price,
                status="unavailable",
                reason="Trade is not open",
                metadata={"data_status": "trade_closed"},
            ))

        if snapshot is None:
            return self._with_user_action(self._alert(
                trade=trade,
                snapshot=None,
                detected_at=detected_at,
                current_price=current_price,
                status="unavailable",
                reason="Signal invalidation plan is unavailable",
                metadata={"data_status": "missing_signal_invalidation"},
            ))

        if features is None:
            return self._with_user_action(self._alert(
                trade=trade,
                snapshot=snapshot,
                detected_at=detected_at,
                current_price=current_price,
                status="unavailable",
                reason="Not enough candle data to evaluate logical invalidation",
                metadata={"data_status": "missing_candles", **snapshot.metadata},
            ))

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
            return self._with_user_action(self._alert(
                trade=trade,
                snapshot=snapshot,
                detected_at=detected_at,
                current_price=current_price,
                metadata=latest_metadata,
            ))

        return self._with_user_action(self._alert(
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
        ))

    def record_user_action(
        self,
        trade: TradeLike,
        action: TradeInvalidationUserAction,
        *,
        user_id: str = "demo_user",
        alert: TradeInvalidationAlert | None = None,
    ) -> TradeInvalidationAlert:
        current_alert = alert or self.evaluate_trade(trade)
        fingerprint = current_alert.fingerprint or _alert_fingerprint(current_alert)
        current_alert = current_alert.model_copy(update={"fingerprint": fingerprint})
        record = self._actions.record(current_alert, action, user_id=user_id)
        return current_alert.model_copy(
            update={
                "user_action": record.action,
                "user_action_at": record.created_at,
                "action_dismissed": _dismisses_alert(record.action),
            }
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
        return signal_invalidation_conditions(
            strategy=trade.strategy,
            side=trade.side,
            snapshot=snapshot,
            features=features,
            stop_loss=trade.stop_loss,
        )

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
        metadata = metadata or {}
        alert = TradeInvalidationAlert(
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
            metadata={**metadata, "trade_mode": trade.mode},
        )
        return alert.model_copy(update={"fingerprint": _alert_fingerprint(alert)})

    def _with_user_action(self, alert: TradeInvalidationAlert) -> TradeInvalidationAlert:
        record = self._actions.latest_for_alert(alert)
        if record is None:
            return alert
        return alert.model_copy(
            update={
                "user_action": record.action,
                "user_action_at": record.created_at,
                "action_dismissed": _dismisses_alert(record.action),
            }
        )


class TradeInvalidationMonitor:
    def __init__(
        self,
        *,
        trades: OpenTradeLookup | None = None,
        invalidations: TradeInvalidationService | None = None,
    ) -> None:
        self._trades = trades or virtual_trading_service
        self._invalidations = invalidations or trade_invalidation_service
        self._published_fingerprints: dict[str, str] = {}

    async def process_closed_candle(self, features: Features) -> list[TradeInvalidationAlert]:
        alerts: list[TradeInvalidationAlert] = []
        for trade in self._matching_open_trades(features):
            alert = self._invalidations.evaluate_trade_with_features(trade, features)
            if not alert.invalidated or alert.action_dismissed:
                continue
            if not self._should_publish(alert):
                continue
            alerts.append(alert)
            await realtime_event_broker.publish(trade_invalidation_event(alert))
        if alerts:
            logger.info(
                "Trade invalidation alerts for %s:%s:%s: %s",
                features.exchange,
                features.symbol,
                features.timeframe,
                len(alerts),
            )
        return alerts

    def _matching_open_trades(self, features: Features) -> list[TradeJournalEntry]:
        return [
            trade
            for trade in self._trades.list_trade_journal(status="open")
            if trade.exchange == features.exchange
            and trade.symbol == features.symbol
            and trade.timeframe == features.timeframe
            and trade.status == "open"
        ]

    def _should_publish(self, alert: TradeInvalidationAlert) -> bool:
        fingerprint = alert.fingerprint or _alert_fingerprint(alert)
        previous = self._published_fingerprints.get(alert.trade_id)
        if previous == fingerprint:
            return False
        self._published_fingerprints[alert.trade_id] = fingerprint
        return True


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


def signal_invalidation_conditions(
    *,
    strategy: str,
    side: str,
    snapshot: SignalInvalidationSnapshot,
    features: Features,
    stop_loss: float | None = None,
) -> list[str]:
    if strategy == "trend_pullback_continuation":
        return _trend_pullback_conditions(side, snapshot, features)
    if strategy == "volatility_squeeze_breakout":
        return _squeeze_breakout_conditions(side, snapshot, features)
    if strategy == "liquidity_sweep_reversal":
        return _liquidity_sweep_conditions(side, snapshot, features)
    return _fallback_signal_conditions(side, snapshot, features, stop_loss)


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


def _fallback_signal_conditions(
    side: str,
    snapshot: SignalInvalidationSnapshot,
    features: Features,
    stop_loss: float | None,
) -> list[str]:
    invalidation_price = _number(snapshot.price, snapshot.hard_stop, stop_loss)
    if invalidation_price is None:
        return []
    if side == "long" and features.close <= invalidation_price:
        return ["Signal stop is reached"]
    if side == "short" and features.close >= invalidation_price:
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


def _alert_fingerprint(alert: TradeInvalidationAlert) -> str:
    payload = {
        "trade_id": alert.trade_id,
        "signal_id": alert.signal_id,
        "strategy": alert.strategy,
        "side": alert.side,
        "status": alert.status,
        "triggered_conditions": sorted(alert.triggered_conditions),
        "invalidation_price": alert.invalidation_price,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _dismisses_alert(action: TradeInvalidationUserAction) -> bool:
    return action in {"keep_stop_loss", "dismissed", "close_market"}


def _action_record(record: TradeInvalidationAction | None) -> TradeInvalidationActionRecord | None:
    if record is None:
        return None
    return TradeInvalidationActionRecord(
        action=record.action,
        created_at=record.created_at,
        dismissed_at=record.dismissed_at,
    )


def _resolve_user(session: Session, user_id: str) -> AppUser | None:
    user = session.scalars(
        select(AppUser).where((AppUser.username == user_id) | (AppUser.email == user_id))
    ).first()
    if user is not None:
        return user
    return session.scalars(select(AppUser).where(AppUser.username == "demo")).first()


def _uuid_or_none(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


trade_invalidation_service = TradeInvalidationService()
trade_invalidation_monitor = TradeInvalidationMonitor()
