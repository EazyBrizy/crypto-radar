from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any

from app.schemas.signal import RadarSignal
from app.schemas.trade_plan import TradePlan, build_trade_plan_from_legacy_fields


@dataclass(frozen=True)
class TradePlanFingerprint:
    normalized: dict[str, Any]
    hash: str


def fingerprint_signal_trade_plan(signal: RadarSignal) -> TradePlanFingerprint:
    trade_plan = signal.trade_plan or build_trade_plan_from_legacy_fields(
        entry_min=signal.entry_min,
        entry_max=signal.entry_max,
        stop_loss=signal.stop_loss,
        take_profit_1=signal.take_profit_1,
        take_profit_2=signal.take_profit_2,
        risk_reward=signal.risk_reward,
        first_target_rr=signal.first_target_rr,
        final_target_rr=signal.final_target_rr,
        selected_rr=signal.selected_rr,
        selected_rr_target=signal.selected_rr_target,
        min_rr_ratio=signal.min_rr_ratio,
        source="trade_plan_fingerprint",
    )
    return fingerprint_trade_plan(
        trade_plan=trade_plan,
        exchange=signal.exchange,
        symbol=signal.symbol,
        side=signal.direction,
        entry_min=signal.entry_min,
        entry_max=signal.entry_max,
        stop_loss=signal.stop_loss,
    )


def fingerprint_trade_plan(
    *,
    trade_plan: TradePlan | dict[str, Any],
    exchange: str,
    symbol: str,
    side: str,
    entry_min: Any = None,
    entry_max: Any = None,
    stop_loss: Any = None,
) -> TradePlanFingerprint:
    plan = trade_plan if isinstance(trade_plan, TradePlan) else TradePlan.model_validate(trade_plan)
    normalized = {
        "exchange": _normalize_exchange(exchange),
        "symbol": _normalize_symbol(symbol),
        "side": _normalize_side(side),
        "entry": _normalized_entry(plan, entry_min=entry_min, entry_max=entry_max),
        "stop_loss": _decimal_string(
            _required_positive_decimal(
                _first_present(
                    plan.stop_loss,
                    stop_loss,
                    plan.invalidation.hard_stop if plan.invalidation is not None else None,
                    plan.invalidation.price if plan.invalidation is not None else None,
                ),
                "stop_loss",
            )
        ),
        "targets": _normalized_targets(plan),
    }
    return TradePlanFingerprint(
        normalized=normalized,
        hash=_hash_normalized_payload(normalized),
    )


def trade_plan_hash_from_normalized_payload(payload: dict[str, Any]) -> str:
    return _hash_normalized_payload(payload)


def _normalized_entry(
    plan: TradePlan,
    *,
    entry_min: Any,
    entry_max: Any,
) -> dict[str, str | None]:
    min_price = _required_positive_decimal(
        _first_present(plan.entry.min_price, entry_min, plan.entry.price),
        "entry.min_price",
    )
    max_price = _required_positive_decimal(
        _first_present(plan.entry.max_price, entry_max, plan.entry.price),
        "entry.max_price",
    )
    if max_price < min_price:
        raise ValueError("entry.max_price must be greater than or equal to entry.min_price")
    price = _positive_decimal_or_none(plan.entry.price)
    if price is None:
        price = (min_price + max_price) / Decimal("2")
    return {
        "price": _decimal_string(price),
        "min_price": _decimal_string(min_price),
        "max_price": _decimal_string(max_price),
    }


def _normalized_targets(plan: TradePlan) -> list[dict[str, str | None]]:
    targets: list[dict[str, str | None]] = []
    for target in plan.targets:
        if target.price is None:
            continue
        price = _required_positive_decimal(target.price, "target.price")
        targets.append(
            {
                "label": str(target.label).strip() or "target",
                "price": _decimal_string(price),
                "action": _string_or_none(target.action),
                "close_percent": _normalized_optional_scalar(target.close_percent),
            }
        )
    if not targets:
        raise ValueError("trade plan fingerprint requires at least one target price")
    return targets


def _hash_normalized_payload(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


def _required_positive_decimal(value: Any, field_name: str) -> Decimal:
    number = _positive_decimal_or_none(value)
    if number is None:
        raise ValueError(f"trade plan fingerprint requires {field_name}")
    return number


def _positive_decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("trade plan fingerprint requires numeric prices") from exc
    if number <= 0:
        raise ValueError("trade plan fingerprint requires positive prices")
    return number


def _normalized_optional_scalar(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        text = str(value).strip()
        return text or None
    if number < 0:
        raise ValueError("trade plan fingerprint requires non-negative close_percent")
    return _decimal_string(number)


def _decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_exchange(exchange: str) -> str:
    normalized = exchange.strip().lower()
    if not normalized:
        raise ValueError("trade plan fingerprint requires exchange")
    return normalized


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper().replace("/", "").replace(":PERP", "")
    if not normalized:
        raise ValueError("trade plan fingerprint requires symbol")
    return normalized


def _normalize_side(side: str) -> str:
    normalized = side.strip().lower()
    if normalized not in {"long", "short"}:
        raise ValueError("trade plan fingerprint requires side long or short")
    return normalized


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
