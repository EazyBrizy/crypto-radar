from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.signal import SignalOutcome, TradingSignal
from app.models.strategy import StrategyVersion
from app.schemas.candle import OHLCVCandle
from app.schemas.signal_outcome import SameCandleResolution

logger = logging.getLogger(__name__)

TARGET_STATUSES = ("tp1", "tp2", "tp3")
SAME_CANDLE_POLICIES = {"stop_first", "target_first", "ignore_ambiguous"}
TIME_STOP_KEYS = ("time_stop", "time_stop_at", "expires_at", "at", "max_holding_seconds")


@dataclass(frozen=True)
class _Target:
    label: str
    price: Decimal
    r_multiple: Decimal


@dataclass(frozen=True)
class _TrackingPlan:
    entry_price: Decimal
    entry_min: Decimal
    entry_max: Decimal
    stop_loss: Decimal
    targets: list[_Target]
    selected_rr: Decimal | None
    metadata: dict[str, Any]


class SignalOutcomeService:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        *,
        tracking_min_score: int | None = None,
        same_candle_resolution: SameCandleResolution | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._tracking_min_score = (
            int(settings.signal_outcome_tracking_min_score)
            if tracking_min_score is None
            else int(tracking_min_score)
        )
        configured_policy = same_candle_resolution or settings.signal_outcome_same_candle_resolution
        self._same_candle_resolution = (
            configured_policy
            if configured_policy in SAME_CANDLE_POLICIES
            else "stop_first"
        )

    def create_tracking_for_signal(
        self,
        signal: TradingSignal,
        *,
        session: Session | None = None,
    ) -> SignalOutcome | None:
        if session is not None:
            return self._create_tracking_for_signal(session, signal)

        with self._session_factory() as local_session:
            record = local_session.scalars(
                _signal_select().where(TradingSignal.id == signal.id)
            ).one_or_none()
            if record is None:
                return None
            outcome = self._create_tracking_for_signal(local_session, record)
            local_session.commit()
            return outcome

    def update_open_outcomes_for_candle(self, candle: OHLCVCandle) -> list[SignalOutcome]:
        if not candle.is_closed:
            return []
        with self._session_factory() as session:
            outcomes = session.scalars(
                select(SignalOutcome)
                .where(
                    SignalOutcome.exchange == candle.exchange,
                    SignalOutcome.symbol == candle.symbol,
                    SignalOutcome.timeframe == candle.timeframe,
                    SignalOutcome.outcome == "open",
                )
                .order_by(SignalOutcome.created_at.asc())
            ).all()
            for outcome in outcomes:
                self.update_with_closed_candle(outcome, candle)
            session.commit()
            return list(outcomes)

    def update_with_closed_candle(self, outcome: SignalOutcome, candle: OHLCVCandle) -> SignalOutcome:
        if outcome.outcome != "open" or not candle.is_closed:
            return outcome

        metadata = dict(outcome.metadata_ or {})
        if metadata.get("last_processed_candle_open_time") == candle.open_time:
            return outcome

        bars_seen = int(metadata.get("bars_seen") or 0) + 1
        metadata["bars_seen"] = bars_seen
        metadata["last_processed_candle_open_time"] = candle.open_time
        metadata["last_processed_candle_close_time"] = candle.close_time

        candle_closed_at = _timestamp_to_datetime(candle.close_time)
        entry_is_touched = _entry_is_touched(outcome, metadata)

        if not entry_is_touched and _expiry_reached(metadata, candle_closed_at):
            return self.close_outcome(
                outcome,
                status="expired",
                result="expired",
                realized_r=Decimal("0"),
                closed_at=candle_closed_at,
                bars_to_outcome=bars_seen,
                metadata=metadata,
            )

        if not entry_is_touched and _invalidation_reached(outcome, candle):
            return self.close_outcome(
                outcome,
                status="invalidated",
                result="invalidated",
                realized_r=Decimal("0"),
                closed_at=candle_closed_at,
                bars_to_outcome=bars_seen,
                metadata=metadata,
            )

        if not entry_is_touched:
            if not _entry_zone_touched(outcome, candle):
                outcome.metadata_ = metadata
                outcome.updated_at = candle_closed_at
                return outcome
            outcome.status = "entry_touched"
            outcome.bars_to_entry = bars_seen
            metadata["entry_touched_at"] = candle_closed_at.isoformat()
            metadata["entry_candle_open_time"] = candle.open_time
            entry_is_touched = True

        if entry_is_touched:
            self._update_excursion(outcome, candle)
            close_decision = self._target_or_stop_decision(outcome, candle, metadata)
            if close_decision is not None:
                status, realized_r = close_decision
                return self.close_outcome(
                    outcome,
                    status=status,
                    result="loss" if status == "stop_loss" else "win",
                    realized_r=realized_r,
                    closed_at=candle_closed_at,
                    bars_to_outcome=bars_seen,
                    metadata=metadata,
                )

            if _invalidation_reached(outcome, candle):
                realized_r = _current_r(outcome, Decimal(str(candle.close)))
                return self.close_outcome(
                    outcome,
                    status="invalidated",
                    result="invalidated",
                    realized_r=realized_r,
                    closed_at=candle_closed_at,
                    bars_to_outcome=bars_seen,
                    metadata=metadata,
                )

            if _time_stop_reached(metadata, candle_closed_at):
                realized_r = _current_r(outcome, Decimal(str(candle.close)))
                return self.close_outcome(
                    outcome,
                    status="time_stop",
                    result=_result_from_realized_r(realized_r),
                    realized_r=realized_r,
                    closed_at=candle_closed_at,
                    bars_to_outcome=bars_seen,
                    metadata=metadata,
                )

        outcome.metadata_ = metadata
        outcome.updated_at = candle_closed_at
        return outcome

    def close_outcome(
        self,
        outcome: SignalOutcome,
        *,
        status: str,
        result: str,
        realized_r: Decimal,
        closed_at: datetime,
        bars_to_outcome: int,
        metadata: dict[str, Any] | None = None,
    ) -> SignalOutcome:
        outcome.status = status
        outcome.outcome = result
        outcome.realized_r = realized_r
        outcome.bars_to_outcome = bars_to_outcome
        outcome.closed_at = closed_at
        outcome.updated_at = closed_at
        if metadata is not None:
            outcome.metadata_ = metadata
        return outcome

    def _create_tracking_for_signal(self, session: Session, signal: TradingSignal) -> SignalOutcome | None:
        existing = session.scalars(
            select(SignalOutcome).where(SignalOutcome.signal_id == signal.id)
        ).one_or_none()
        if existing is not None:
            return existing

        plan = _tracking_plan_from_signal(signal, self._tracking_min_score)
        if plan is None:
            return None

        now = datetime.now(timezone.utc)
        outcome = SignalOutcome(
            signal_id=signal.id,
            exchange=signal.exchange.code,
            symbol=signal.pair.symbol,
            timeframe=signal.timeframe,
            strategy=signal.strategy_version.strategy.code,
            direction=signal.direction,
            signal_score=signal.score,
            entry_price=plan.entry_price,
            entry_min=plan.entry_min,
            entry_max=plan.entry_max,
            stop_loss=plan.stop_loss,
            targets=[_target_payload(target) for target in plan.targets],
            status="tracking",
            outcome="open",
            selected_rr=plan.selected_rr,
            realized_r=Decimal("0"),
            mfe_r=Decimal("0"),
            mae_r=Decimal("0"),
            created_at=now,
            updated_at=now,
            metadata_=plan.metadata,
        )
        session.add(outcome)
        session.flush()
        return outcome

    def _target_or_stop_decision(
        self,
        outcome: SignalOutcome,
        candle: OHLCVCandle,
        metadata: dict[str, Any],
    ) -> tuple[str, Decimal] | None:
        targets = _targets_from_outcome(outcome)
        if not targets:
            return None

        selected_target_index = _selected_target_index(outcome, targets, metadata)
        hit_target_indexes = [
            index
            for index, target in enumerate(targets[: len(TARGET_STATUSES)])
            if _target_hit(outcome, candle, target)
        ]
        stop_hit = _stop_hit(outcome, candle)
        selected_target_hit = selected_target_index in hit_target_indexes

        if stop_hit and selected_target_hit:
            metadata["same_candle_ambiguous"] = {
                "policy": self._same_candle_resolution,
                "candle_open_time": candle.open_time,
                "candle_close_time": candle.close_time,
                "selected_target": targets[selected_target_index].label,
            }
            if self._same_candle_resolution == "ignore_ambiguous":
                return None
            if self._same_candle_resolution == "target_first":
                target = targets[selected_target_index]
                return TARGET_STATUSES[selected_target_index], target.r_multiple
            return "stop_loss", Decimal("-1")

        if stop_hit:
            return "stop_loss", Decimal("-1")

        if not hit_target_indexes:
            return None

        highest_hit_index = max(hit_target_indexes)
        if highest_hit_index >= selected_target_index:
            target = targets[selected_target_index]
            return TARGET_STATUSES[selected_target_index], target.r_multiple

        outcome.status = TARGET_STATUSES[highest_hit_index]
        return None

    @staticmethod
    def _update_excursion(outcome: SignalOutcome, candle: OHLCVCandle) -> None:
        risk = _risk(outcome)
        if risk <= 0:
            return
        entry = _decimal(outcome.entry_price)
        high = Decimal(str(candle.high))
        low = Decimal(str(candle.low))
        if outcome.direction == "long":
            mfe = (high - entry) / risk
            mae = (low - entry) / risk
        else:
            mfe = (entry - low) / risk
            mae = (entry - high) / risk
        outcome.mfe_r = max(_decimal(outcome.mfe_r), mfe)
        outcome.mae_r = min(_decimal(outcome.mae_r), mae)


def _signal_select():
    return select(TradingSignal).options(
        joinedload(TradingSignal.exchange),
        joinedload(TradingSignal.pair),
        joinedload(TradingSignal.strategy_version).joinedload(StrategyVersion.strategy),
    )


def _tracking_plan_from_signal(signal: TradingSignal, tracking_min_score: int) -> _TrackingPlan | None:
    score = _decimal(signal.score)
    if score < Decimal(str(tracking_min_score)):
        return None

    snapshot = signal.features_snapshot or {}
    record_entry = _optional_decimal(signal.entry_price)
    entry_min = _optional_decimal(snapshot.get("entry_min"))
    entry_max = _optional_decimal(snapshot.get("entry_max"))
    if entry_min is None and entry_max is None:
        if record_entry is None:
            return None
        entry_min = record_entry
        entry_max = record_entry
    elif entry_min is None:
        entry_min = entry_max
    elif entry_max is None:
        entry_max = entry_min
    if entry_min is None or entry_max is None:
        return None
    entry_price = record_entry or _midpoint(entry_min, entry_max)
    stop_loss = _decimal(signal.stop_loss)
    if entry_price <= 0 or entry_min <= 0 or entry_max <= 0 or stop_loss <= 0:
        return None

    lower_entry = min(entry_min, entry_max)
    upper_entry = max(entry_min, entry_max)
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        return None
    if signal.direction == "long" and stop_loss >= entry_price:
        return None
    if signal.direction == "short" and stop_loss <= entry_price:
        return None

    targets = _extract_targets(signal, snapshot, entry_price, risk)
    if not targets:
        return None

    metadata = {
        "source": "signal_outcome_v1",
        "signal_key": signal.signal_key,
        "detected_at": _datetime_json(signal.detected_at),
        "expires_at": _datetime_json(signal.expires_at),
        "selected_rr_target": _selected_rr_target(snapshot),
        "bars_seen": 0,
    }
    invalidation_price = _invalidation_price(snapshot)
    if invalidation_price is not None:
        metadata["invalidation_price"] = str(invalidation_price)
    time_stop = _time_stop_metadata(snapshot)
    if time_stop:
        metadata["time_stop"] = time_stop

    return _TrackingPlan(
        entry_price=entry_price,
        entry_min=lower_entry,
        entry_max=upper_entry,
        stop_loss=stop_loss,
        targets=targets,
        selected_rr=_selected_rr(snapshot, targets),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _extract_targets(
    signal: TradingSignal,
    snapshot: dict[str, Any],
    entry_price: Decimal,
    risk: Decimal,
) -> list[_Target]:
    raw_targets: list[dict[str, Any]] = []
    trade_plan = snapshot.get("trade_plan") if isinstance(snapshot.get("trade_plan"), dict) else {}
    trade_plan_targets = trade_plan.get("targets") if isinstance(trade_plan.get("targets"), list) else []
    for index, target in enumerate(trade_plan_targets[:3]):
        if not isinstance(target, dict):
            continue
        raw_targets.append(
            {
                "label": target.get("label") or f"TP{index + 1}",
                "price": target.get("price"),
                "r_multiple": target.get("r_multiple"),
            }
        )
    if not raw_targets:
        for index, price in enumerate((signal.take_profit or [])[:3]):
            raw_targets.append({"label": f"TP{index + 1}", "price": price, "r_multiple": None})

    targets: list[_Target] = []
    for index, raw_target in enumerate(raw_targets):
        price = _optional_decimal(raw_target.get("price"))
        if price is None or price <= 0:
            continue
        r_multiple = _optional_decimal(raw_target.get("r_multiple"))
        if r_multiple is None:
            r_multiple = _target_r(signal.direction, entry_price, price, risk)
        if r_multiple <= 0:
            continue
        if signal.direction == "long" and price <= entry_price:
            continue
        if signal.direction == "short" and price >= entry_price:
            continue
        targets.append(
            _Target(
                label=str(raw_target.get("label") or f"TP{index + 1}"),
                price=price,
                r_multiple=r_multiple,
            )
        )
    return targets


def _target_payload(target: _Target) -> dict[str, float | str]:
    return {
        "label": target.label,
        "price": float(target.price),
        "r_multiple": float(target.r_multiple),
    }


def _entry_zone_touched(outcome: SignalOutcome, candle: OHLCVCandle) -> bool:
    lower = min(_decimal(outcome.entry_min), _decimal(outcome.entry_max))
    upper = max(_decimal(outcome.entry_min), _decimal(outcome.entry_max))
    return Decimal(str(candle.low)) <= upper and Decimal(str(candle.high)) >= lower


def _entry_is_touched(outcome: SignalOutcome, metadata: dict[str, Any]) -> bool:
    return outcome.bars_to_entry is not None or bool(metadata.get("entry_touched_at"))


def _stop_hit(outcome: SignalOutcome, candle: OHLCVCandle) -> bool:
    stop_loss = _decimal(outcome.stop_loss)
    if outcome.direction == "long":
        return Decimal(str(candle.low)) <= stop_loss
    return Decimal(str(candle.high)) >= stop_loss


def _target_hit(outcome: SignalOutcome, candle: OHLCVCandle, target: _Target) -> bool:
    if outcome.direction == "long":
        return Decimal(str(candle.high)) >= target.price
    return Decimal(str(candle.low)) <= target.price


def _targets_from_outcome(outcome: SignalOutcome) -> list[_Target]:
    result: list[_Target] = []
    for index, raw_target in enumerate((outcome.targets or [])[:3]):
        if not isinstance(raw_target, dict):
            continue
        price = _optional_decimal(raw_target.get("price"))
        r_multiple = _optional_decimal(raw_target.get("r_multiple"))
        if price is None or r_multiple is None:
            continue
        result.append(
            _Target(
                label=str(raw_target.get("label") or f"TP{index + 1}"),
                price=price,
                r_multiple=r_multiple,
            )
        )
    return result


def _selected_target_index(
    outcome: SignalOutcome,
    targets: list[_Target],
    metadata: dict[str, Any],
) -> int:
    raw_target = str(metadata.get("selected_rr_target") or "").lower()
    if raw_target in {"nearest", "first", "tp1", "target_1", "target1"}:
        return 0
    if raw_target in {"tp2", "target_2", "target2", "second"}:
        return min(1, len(targets) - 1)
    if raw_target in {"tp3", "target_3", "target3", "third"}:
        return min(2, len(targets) - 1)
    if raw_target in {"final", "last"}:
        return len(targets) - 1

    selected_rr = _optional_decimal(outcome.selected_rr)
    if selected_rr is not None:
        for index, target in enumerate(targets):
            if target.r_multiple >= selected_rr:
                return index
    return len(targets) - 1


def _invalidation_reached(outcome: SignalOutcome, candle: OHLCVCandle) -> bool:
    invalidation_price = _optional_decimal((outcome.metadata_ or {}).get("invalidation_price"))
    if invalidation_price is None:
        return False
    if outcome.direction == "long":
        return Decimal(str(candle.close)) <= invalidation_price
    return Decimal(str(candle.close)) >= invalidation_price


def _expiry_reached(metadata: dict[str, Any], candle_closed_at: datetime) -> bool:
    expires_at = _parse_datetime(metadata.get("expires_at"))
    return expires_at is not None and _as_utc(candle_closed_at) >= _as_utc(expires_at)


def _time_stop_reached(metadata: dict[str, Any], candle_closed_at: datetime) -> bool:
    raw_time_stop = metadata.get("time_stop")
    time_stop = raw_time_stop if isinstance(raw_time_stop, dict) else {}
    explicit_at = _parse_datetime(
        time_stop.get("time_stop_at")
        or time_stop.get("expires_at")
        or time_stop.get("at")
        or (raw_time_stop if isinstance(raw_time_stop, str) else None)
    )
    if explicit_at is not None and _as_utc(candle_closed_at) >= _as_utc(explicit_at):
        return True

    max_holding_seconds = _optional_decimal(time_stop.get("max_holding_seconds"))
    entry_touched_at = _parse_datetime(metadata.get("entry_touched_at"))
    if max_holding_seconds is None or entry_touched_at is None:
        return False
    return _as_utc(candle_closed_at) >= _as_utc(entry_touched_at) + timedelta(
        seconds=float(max_holding_seconds)
    )


def _current_r(outcome: SignalOutcome, price: Decimal) -> Decimal:
    risk = _risk(outcome)
    if risk <= 0:
        return Decimal("0")
    entry = _decimal(outcome.entry_price)
    if outcome.direction == "long":
        return (price - entry) / risk
    return (entry - price) / risk


def _risk(outcome: SignalOutcome) -> Decimal:
    return abs(_decimal(outcome.entry_price) - _decimal(outcome.stop_loss))


def _target_r(direction: str, entry_price: Decimal, target_price: Decimal, risk: Decimal) -> Decimal:
    if direction == "long":
        return (target_price - entry_price) / risk
    return (entry_price - target_price) / risk


def _result_from_realized_r(realized_r: Decimal) -> str:
    if realized_r > 0:
        return "win"
    if realized_r < 0:
        return "loss"
    return "breakeven"


def _selected_rr(snapshot: dict[str, Any], targets: list[_Target]) -> Decimal | None:
    selected = _optional_decimal(snapshot.get("selected_rr"))
    if selected is not None:
        return selected
    trade_plan = snapshot.get("trade_plan") if isinstance(snapshot.get("trade_plan"), dict) else {}
    risk_rules = trade_plan.get("risk_rules") if isinstance(trade_plan.get("risk_rules"), dict) else {}
    selected = _optional_decimal(risk_rules.get("selected_rr"))
    if selected is not None:
        return selected
    return targets[-1].r_multiple if targets else None


def _selected_rr_target(snapshot: dict[str, Any]) -> str | None:
    if isinstance(snapshot.get("selected_rr_target"), str):
        return snapshot["selected_rr_target"]
    trade_plan = snapshot.get("trade_plan") if isinstance(snapshot.get("trade_plan"), dict) else {}
    risk_rules = trade_plan.get("risk_rules") if isinstance(trade_plan.get("risk_rules"), dict) else {}
    target = risk_rules.get("selected_rr_target")
    return target if isinstance(target, str) else None


def _invalidation_price(snapshot: dict[str, Any]) -> Decimal | None:
    invalidation = snapshot.get("invalidation") if isinstance(snapshot.get("invalidation"), dict) else {}
    price = _optional_decimal(invalidation.get("price"), invalidation.get("hard_stop"))
    if price is not None:
        return price
    trade_plan = snapshot.get("trade_plan") if isinstance(snapshot.get("trade_plan"), dict) else {}
    plan_invalidation = trade_plan.get("invalidation") if isinstance(trade_plan.get("invalidation"), dict) else {}
    return _optional_decimal(plan_invalidation.get("price"), plan_invalidation.get("hard_stop"))


def _time_stop_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    trade_plan = snapshot.get("trade_plan") if isinstance(snapshot.get("trade_plan"), dict) else {}
    sources: list[dict[str, Any]] = []
    for key in ("metadata",):
        if isinstance(trade_plan.get(key), dict):
            sources.append(trade_plan[key])
    risk_rules = trade_plan.get("risk_rules") if isinstance(trade_plan.get("risk_rules"), dict) else {}
    invalidation = trade_plan.get("invalidation") if isinstance(trade_plan.get("invalidation"), dict) else {}
    for source in (risk_rules.get("metadata"), invalidation.get("metadata")):
        if isinstance(source, dict):
            sources.append(source)

    result: dict[str, Any] = {}
    for source in sources:
        for key in TIME_STOP_KEYS:
            if source.get(key) is not None:
                result[key] = source[key]
    return result


def _midpoint(entry_min: Decimal, entry_max: Decimal) -> Decimal:
    return (entry_min + entry_max) / Decimal("2")


def _decimal(*values: Any) -> Decimal:
    for value in values:
        parsed = _optional_decimal(value)
        if parsed is not None:
            return parsed
    return Decimal("0")


def _optional_decimal(*values: Any) -> Decimal | None:
    for value in values:
        if value is None:
            continue
        try:
            return Decimal(str(value))
        except Exception:
            continue
    return None


def _timestamp_to_datetime(timestamp: int) -> datetime:
    seconds = timestamp / 1000 if timestamp > 10_000_000_000 else timestamp
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return _timestamp_to_datetime(int(value))
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return _as_utc(parsed)


def _datetime_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


signal_outcome_service = SignalOutcomeService()
