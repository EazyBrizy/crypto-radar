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


@dataclass(frozen=True)
class PendingEntryMaterialChangeEvaluation:
    material: bool
    summary: dict[str, Any]
    current_normalized: dict[str, Any] | None = None
    current_hash: str | None = None
    error: str | None = None


DEFAULT_MATERIAL_CHANGE_TOLERANCE_BPS = Decimal("10")
EXACT_MATCH_TOLERANCE = {"type": "exact"}


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


def default_material_change_policy() -> dict[str, Any]:
    return {
        "version": "v1",
        "tolerances": {
            "entry_zone": {
                "relative_bps": _decimal_string(DEFAULT_MATERIAL_CHANGE_TOLERANCE_BPS),
                "absolute": None,
            },
            "stop_loss": {
                "relative_bps": _decimal_string(DEFAULT_MATERIAL_CHANGE_TOLERANCE_BPS),
                "absolute": None,
            },
            "take_profit_targets": {
                "relative_bps": _decimal_string(DEFAULT_MATERIAL_CHANGE_TOLERANCE_BPS),
                "absolute": None,
            },
        },
    }


def material_change_policy_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return default_material_change_policy()
    raw = snapshot.get("material_change_policy")
    if not isinstance(raw, dict):
        return default_material_change_policy()
    policy = default_material_change_policy()
    tolerances = raw.get("tolerances")
    if isinstance(tolerances, dict):
        merged_tolerances = dict(policy["tolerances"])
        for key in ("entry_zone", "stop_loss", "take_profit_targets"):
            value = tolerances.get(key)
            if isinstance(value, dict):
                merged_tolerances[key] = {
                    **merged_tolerances[key],
                    **value,
                }
        policy["tolerances"] = merged_tolerances
    for key, value in raw.items():
        if key != "tolerances":
            policy[key] = value
    return policy


def normalized_pending_entry_payload(
    *,
    exchange: str,
    symbol: str,
    side: str,
    entry_min: Any,
    entry_max: Any,
    stop_loss: Any,
    targets_snapshot: Any,
) -> dict[str, Any]:
    entry_min_value = _required_positive_decimal(entry_min, "entry.min_price")
    entry_max_value = _required_positive_decimal(entry_max, "entry.max_price")
    if entry_max_value < entry_min_value:
        raise ValueError("entry.max_price must be greater than or equal to entry.min_price")
    return {
        "exchange": _normalize_exchange(exchange),
        "symbol": _normalize_symbol(symbol),
        "side": _normalize_side(side),
        "entry": {
            "price": _decimal_string((entry_min_value + entry_max_value) / Decimal("2")),
            "min_price": _decimal_string(entry_min_value),
            "max_price": _decimal_string(entry_max_value),
        },
        "stop_loss": _decimal_string(
            _required_positive_decimal(stop_loss, "stop_loss")
        ),
        "targets": _normalized_targets_snapshot(targets_snapshot),
    }


def evaluate_pending_entry_material_change(
    *,
    accepted_payload: dict[str, Any],
    current_signal: RadarSignal,
    policy: dict[str, Any] | None = None,
    execution_profile_snapshot: dict[str, Any] | None = None,
    mode: str | None = None,
) -> PendingEntryMaterialChangeEvaluation:
    resolved_policy = policy or default_material_change_policy()
    current_hash: str | None = None
    current_normalized: dict[str, Any] | None = None
    plan_error: str | None = None
    try:
        current_fingerprint = fingerprint_signal_trade_plan(current_signal)
        current_normalized = current_fingerprint.normalized
        current_hash = current_fingerprint.hash
    except ValueError as exc:
        plan_error = str(exc)
        current_normalized = _identity_payload_from_signal(current_signal)

    changes: list[dict[str, Any]] = []
    _append_identity_changes(changes, accepted_payload, current_normalized)
    if plan_error is not None:
        changes.append(
            _change(
                field="trade_plan",
                previous=_compact_payload(accepted_payload),
                current=None,
                tolerance={"type": "valid_current_trade_plan"},
                reason_code="current_trade_plan_invalid",
                detail=plan_error,
            )
        )
    elif current_normalized is not None:
        _append_entry_changes(changes, accepted_payload, current_normalized, resolved_policy)
        _append_stop_loss_changes(changes, accepted_payload, current_normalized, resolved_policy)
        _append_target_changes(changes, accepted_payload, current_normalized, resolved_policy)

    _append_risk_profile_restriction_changes(
        changes,
        execution_profile_snapshot or {},
        accepted_payload=accepted_payload,
        mode=mode,
    )

    summary = {
        "material": bool(changes),
        "changed_fields": [change["field"] for change in changes],
        "changes": changes,
        "policy": resolved_policy,
    }
    if current_hash is not None:
        summary["current_trade_plan_hash"] = current_hash
    if plan_error is not None:
        summary["error"] = plan_error
    return PendingEntryMaterialChangeEvaluation(
        material=bool(changes),
        summary=summary,
        current_normalized=current_normalized,
        current_hash=current_hash,
        error=plan_error,
    )


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
                "price": _decimal_string(price),
            }
        )
    if not targets:
        raise ValueError("trade plan fingerprint requires at least one target price")
    return targets


def _normalized_targets_snapshot(value: Any) -> list[dict[str, str | None]]:
    if isinstance(value, dict):
        raw_targets = value.get("targets")
    else:
        raw_targets = value
    if not isinstance(raw_targets, list):
        raw_targets = []
    targets: list[dict[str, str | None]] = []
    for target in raw_targets:
        raw_price = target.get("price") if isinstance(target, dict) else target
        if raw_price is None:
            continue
        price = _required_positive_decimal(raw_price, "target.price")
        targets.append({"price": _decimal_string(price)})
    if not targets:
        raise ValueError("trade plan fingerprint requires at least one target price")
    return targets


def _identity_payload_from_signal(signal: RadarSignal) -> dict[str, Any]:
    return {
        "exchange": _normalize_exchange(signal.exchange),
        "symbol": _normalize_symbol(signal.symbol),
        "side": _normalize_side(signal.direction),
    }


def _append_identity_changes(
    changes: list[dict[str, Any]],
    previous: dict[str, Any],
    current: dict[str, Any] | None,
) -> None:
    if current is None:
        return
    for field, reason_code in (
        ("exchange", "exchange_changed"),
        ("symbol", "symbol_changed"),
        ("side", "side_changed"),
    ):
        previous_value = _string_or_none(previous.get(field))
        current_value = _string_or_none(current.get(field))
        if previous_value != current_value:
            changes.append(
                _change(
                    field=field,
                    previous=previous_value,
                    current=current_value,
                    tolerance=EXACT_MATCH_TOLERANCE,
                    reason_code=reason_code,
                )
            )


def _append_entry_changes(
    changes: list[dict[str, Any]],
    previous: dict[str, Any],
    current: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    previous_entry = previous.get("entry") if isinstance(previous.get("entry"), dict) else {}
    current_entry = current.get("entry") if isinstance(current.get("entry"), dict) else {}
    tolerance = _tolerance(policy, "entry_zone")
    for key in ("min_price", "max_price", "price"):
        previous_value = _positive_decimal_or_none(previous_entry.get(key))
        current_value = _positive_decimal_or_none(current_entry.get(key))
        if _exceeds_tolerance(previous_value, current_value, tolerance):
            changes.append(
                _change(
                    field=f"entry.{key}",
                    previous=_decimal_string(previous_value) if previous_value is not None else None,
                    current=_decimal_string(current_value) if current_value is not None else None,
                    tolerance=tolerance,
                    reason_code="entry_zone_shifted",
                )
            )


def _append_stop_loss_changes(
    changes: list[dict[str, Any]],
    previous: dict[str, Any],
    current: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    previous_value = _positive_decimal_or_none(previous.get("stop_loss"))
    current_value = _positive_decimal_or_none(current.get("stop_loss"))
    tolerance = _tolerance(policy, "stop_loss")
    if _exceeds_tolerance(previous_value, current_value, tolerance):
        changes.append(
            _change(
                field="stop_loss",
                previous=_decimal_string(previous_value) if previous_value is not None else None,
                current=_decimal_string(current_value) if current_value is not None else None,
                tolerance=tolerance,
                reason_code="stop_loss_shifted",
            )
        )


def _append_target_changes(
    changes: list[dict[str, Any]],
    previous: dict[str, Any],
    current: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    previous_targets = _target_prices(previous.get("targets"))
    current_targets = _target_prices(current.get("targets"))
    tolerance = _tolerance(policy, "take_profit_targets")
    if not any(
        _exceeds_tolerance(previous_value, current_value, tolerance)
        for previous_value, current_value in zip(previous_targets, current_targets)
    ):
        return
    changes.append(
        _change(
            field="targets",
            previous=[_decimal_string(value) for value in previous_targets],
            current=[_decimal_string(value) for value in current_targets],
            tolerance=tolerance,
            reason_code="take_profit_targets_shifted",
        )
    )


def _append_risk_profile_restriction_changes(
    changes: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    accepted_payload: dict[str, Any],
    mode: str | None,
) -> None:
    if not isinstance(profile, dict) or not profile:
        return
    normalized_mode = _string_or_none(mode or profile.get("execution_mode"))
    side = _string_or_none(accepted_payload.get("side"))
    symbol = _string_or_none(accepted_payload.get("symbol"))
    exchange = _string_or_none(accepted_payload.get("exchange"))
    instrument_type = _string_or_none(profile.get("instrument_type"))
    restrictions = (
        ("entries_allowed", True, None, "risk_profile.entries_allowed"),
        (f"{normalized_mode}_entries_allowed" if normalized_mode else "", True, None, "risk_profile.mode"),
        ("allowed_modes", normalized_mode, "allowed", "risk_profile.mode"),
        ("blocked_modes", normalized_mode, "blocked", "risk_profile.mode"),
        ("allowed_sides", side, "allowed", "risk_profile.side"),
        ("blocked_sides", side, "blocked", "risk_profile.side"),
        ("allowed_symbols", symbol, "allowed", "risk_profile.symbol"),
        ("blocked_symbols", symbol, "blocked", "risk_profile.symbol"),
        ("allowed_exchanges", exchange, "allowed", "risk_profile.exchange"),
        ("blocked_exchanges", exchange, "blocked", "risk_profile.exchange"),
        ("allowed_instrument_types", instrument_type, "allowed", "risk_profile.instrument_type"),
        ("blocked_instrument_types", instrument_type, "blocked", "risk_profile.instrument_type"),
    )
    for key, value, mode_type, field in restrictions:
        if not key or value is None:
            continue
        if _profile_restricts(profile, key=key, value=value, mode_type=mode_type):
            changes.append(
                _change(
                    field=field,
                    previous=value,
                    current="restricted",
                    tolerance=EXACT_MATCH_TOLERANCE,
                    reason_code="risk_profile_restricted",
                )
            )


def _profile_restricts(
    profile: dict[str, Any],
    *,
    key: str,
    value: Any,
    mode_type: str | None,
) -> bool:
    raw = profile.get(key)
    if mode_type is None:
        return raw is False
    if not isinstance(raw, list):
        return False
    values = {_normalize_profile_value(item) for item in raw}
    normalized = _normalize_profile_value(value)
    if mode_type == "allowed":
        return normalized not in values
    return normalized in values


def _normalize_profile_value(value: Any) -> str:
    return str(value).strip().lower()


def _target_prices(value: Any) -> list[Decimal]:
    if not isinstance(value, list):
        return []
    prices: list[Decimal] = []
    for target in value:
        raw_price = target.get("price") if isinstance(target, dict) else target
        price = _positive_decimal_or_none(raw_price)
        if price is not None:
            prices.append(price)
    return prices


def _tolerance(policy: dict[str, Any], name: str) -> dict[str, Any]:
    tolerances = policy.get("tolerances")
    if isinstance(tolerances, dict):
        raw = tolerances.get(name)
        if isinstance(raw, dict):
            return {
                "relative_bps": _decimal_string(
                    _non_negative_decimal(raw.get("relative_bps"), DEFAULT_MATERIAL_CHANGE_TOLERANCE_BPS)
                ),
                "absolute": _optional_non_negative_decimal_string(raw.get("absolute")),
            }
    return {
        "relative_bps": _decimal_string(DEFAULT_MATERIAL_CHANGE_TOLERANCE_BPS),
        "absolute": None,
    }


def _exceeds_tolerance(
    previous: Decimal | None,
    current: Decimal | None,
    tolerance: dict[str, Any],
) -> bool:
    if previous is None or current is None:
        return previous != current
    if previous == current:
        return False
    relative_bps = _non_negative_decimal(
        tolerance.get("relative_bps"),
        DEFAULT_MATERIAL_CHANGE_TOLERANCE_BPS,
    )
    absolute = _non_negative_decimal(tolerance.get("absolute"), Decimal("0"))
    relative_limit = abs(previous) * relative_bps / Decimal("10000")
    limit = max(relative_limit, absolute)
    return abs(current - previous) > limit


def _change(
    *,
    field: str,
    previous: Any,
    current: Any,
    tolerance: dict[str, Any],
    reason_code: str,
    detail: str | None = None,
) -> dict[str, Any]:
    payload = {
        "field": field,
        "previous": previous,
        "accepted": previous,
        "current": current,
        "tolerance": tolerance,
        "severity": "blocking",
        "reason_code": reason_code,
    }
    if detail is not None:
        payload["detail"] = detail
    return payload


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "exchange": payload.get("exchange"),
        "symbol": payload.get("symbol"),
        "side": payload.get("side"),
        "entry": payload.get("entry"),
        "stop_loss": payload.get("stop_loss"),
        "targets": payload.get("targets"),
    }


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


def _non_negative_decimal(value: Any, default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default
    if number < 0:
        return default
    return number


def _optional_non_negative_decimal_string(value: Any) -> str | None:
    if value is None:
        return None
    number = _non_negative_decimal(value, Decimal("-1"))
    if number < 0:
        return None
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
