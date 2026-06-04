from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from app.schemas.risk import AccountRiskSnapshot, LiquidationProjectionResult


_ISOLATED_ENTRY_PRICE_FORMULAS = {
    "linear_isolated_entry_price",
    "linear_usdt_isolated_entry_price",
    "usdt_usdc_linear_isolated_entry_price",
    "bybit_usdt_usdc_isolated_entry_price",
}
_BYBIT_2025_ISOLATED_FORMULAS = {
    "bybit_usdt_usdc_isolated_2025",
    "bybit_uta_isolated_2025",
    "linear_isolated_mark_price_2025",
}
_CROSS_AVAILABLE_BALANCE_FORMULAS = {
    "linear_cross_available_balance",
    "bybit_usdt_cross_available_balance",
}


class LiquidationProjectionService:
    """Projects futures liquidation from already-loaded account/rule context."""

    def project(
        self,
        *,
        entry_price: float,
        side: str,
        quantity: float | None,
        leverage: int,
        margin_mode: str | None,
        account_snapshot: AccountRiskSnapshot | Mapping[str, Any] | None,
        instrument_rules: Mapping[str, Any] | object | None,
        provided_liquidation_price: float | None = None,
        fee_rate: float | None = 0.0,
    ) -> LiquidationProjectionResult:
        if provided_liquidation_price is not None:
            return _provided_projection(
                entry_price=entry_price,
                liquidation_price=provided_liquidation_price,
                margin_mode=margin_mode,
            )

        blockers: list[str] = []
        warnings: list[str] = []
        snapshot = _account_snapshot(account_snapshot)
        normalized_margin_mode = _normalize_margin_mode(
            margin_mode
            or _snapshot_value(snapshot, "margin_mode")
            or _rule_value(instrument_rules, "margin_mode", "marginMode")
        )
        if normalized_margin_mode is None:
            blockers.append("Liquidation projection requires margin_mode from account snapshot or execution profile.")
        elif normalized_margin_mode not in {"isolated", "cross"}:
            blockers.append(
                f"Liquidation projection does not support margin_mode={normalized_margin_mode!r}."
            )

        if quantity is None or quantity <= 0:
            blockers.append("Liquidation projection requires resolved positive position quantity.")
        if entry_price <= 0:
            blockers.append("Liquidation projection requires positive entry price.")
        if leverage < 1:
            blockers.append("Liquidation projection requires leverage greater than or equal to 1.")

        formula = _normalized_formula(
            _rule_value(
                instrument_rules,
                "liquidation_formula",
                "liquidationFormula",
                "formula",
            )
        )
        formula_source = _string_or_none(
            _rule_value(
                instrument_rules,
                "liquidation_formula_source",
                "liquidationFormulaSource",
                "formula_source",
            )
        )
        if formula_source is None:
            formula_source = _string_or_none(
                _container_value(
                    _container_value(instrument_rules, "liquidation")
                    if instrument_rules is not None
                    else {},
                    "source",
                )
            )
        if formula is None:
            blockers.append("Liquidation projection requires liquidation_formula in exchange instrument rules.")
        if formula_source is None:
            blockers.append("Liquidation projection requires liquidation_formula_source in exchange instrument rules.")

        maintenance_margin_rate = _first_number(
            _snapshot_value(snapshot, "maintenance_margin_rate"),
            _rule_value(
                instrument_rules,
                "maintenance_margin_rate",
                "maintenanceMarginRate",
                "mm_rate",
                "mmRate",
                "mmr",
                "MMR",
            ),
        )
        maintenance_margin_deduction = _first_number(
            _rule_value(
                instrument_rules,
                "maintenance_margin_deduction",
                "maintenanceMarginDeduction",
                "maintenance_margin_amount",
                "maintenanceMarginAmount",
                "mm_deduction",
                "mmDeduction",
            ),
            0.0,
        )
        extra_margin = _first_number(
            _rule_value(
                instrument_rules,
                "extra_margin_added",
                "extraMarginAdded",
                "extra_margin",
                "extraMargin",
            ),
            0.0,
        )
        if maintenance_margin_rate is None:
            blockers.append(
                "Liquidation projection requires maintenance_margin_rate "
                "from account snapshot or instrument rules."
            )
        elif maintenance_margin_rate < 0:
            blockers.append("Liquidation projection requires non-negative maintenance_margin_rate.")

        if blockers:
            return LiquidationProjectionResult(
                margin_mode=normalized_margin_mode,
                maintenance_margin_rate=maintenance_margin_rate,
                maintenance_margin_amount=None,
                liquidation_price_source="unavailable",
                formula=formula,
                formula_source=formula_source,
                warnings=warnings,
                blockers=_dedupe(blockers),
            )

        assert quantity is not None
        assert formula is not None
        assert maintenance_margin_rate is not None
        assert maintenance_margin_deduction is not None
        assert extra_margin is not None
        try:
            projected_price, maintenance_margin_amount = _calculate_projection(
                formula=formula,
                margin_mode=normalized_margin_mode,
                entry_price=entry_price,
                side=side,
                quantity=quantity,
                leverage=leverage,
                maintenance_margin_rate=maintenance_margin_rate,
                maintenance_margin_deduction=maintenance_margin_deduction,
                extra_margin=extra_margin,
                fee_rate=fee_rate,
                account_snapshot=snapshot,
            )
        except ValueError as exc:
            return LiquidationProjectionResult(
                margin_mode=normalized_margin_mode,
                maintenance_margin_rate=maintenance_margin_rate,
                maintenance_margin_amount=None,
                liquidation_price_source="unavailable",
                formula=formula,
                formula_source=formula_source,
                warnings=warnings,
                blockers=[str(exc)],
            )

        if projected_price <= 0:
            return LiquidationProjectionResult(
                margin_mode=normalized_margin_mode,
                maintenance_margin_rate=maintenance_margin_rate,
                maintenance_margin_amount=maintenance_margin_amount,
                liquidation_price_source="unavailable",
                formula=formula,
                formula_source=formula_source,
                warnings=warnings,
                blockers=["Liquidation projection produced a non-positive liquidation price."],
            )

        distance, distance_percent = _distance(entry_price, projected_price)
        return LiquidationProjectionResult(
            projected_liquidation_price=projected_price,
            distance_to_liquidation=distance,
            distance_to_liquidation_percent=distance_percent,
            margin_mode=normalized_margin_mode,
            maintenance_margin_rate=maintenance_margin_rate,
            maintenance_margin_amount=maintenance_margin_amount,
            liquidation_price_source="projected",
            formula=formula,
            formula_source=formula_source,
            warnings=warnings,
            blockers=[],
        )


def _provided_projection(
    *,
    entry_price: float,
    liquidation_price: float,
    margin_mode: str | None,
) -> LiquidationProjectionResult:
    distance, distance_percent = _distance(entry_price, liquidation_price)
    return LiquidationProjectionResult(
        projected_liquidation_price=liquidation_price,
        distance_to_liquidation=distance,
        distance_to_liquidation_percent=distance_percent,
        margin_mode=_normalize_margin_mode(margin_mode),
        liquidation_price_source="provided",
        warnings=[],
        blockers=[],
    )


def _calculate_projection(
    *,
    formula: str,
    margin_mode: str | None,
    entry_price: float,
    side: str,
    quantity: float,
    leverage: int,
    maintenance_margin_rate: float,
    maintenance_margin_deduction: float,
    extra_margin: float,
    fee_rate: float | None,
    account_snapshot: AccountRiskSnapshot | None,
) -> tuple[float, float]:
    if formula in _ISOLATED_ENTRY_PRICE_FORMULAS:
        if margin_mode != "isolated":
            raise ValueError("Configured liquidation formula requires isolated margin mode.")
        return _linear_isolated_entry_price(
            entry_price=entry_price,
            side=side,
            quantity=quantity,
            leverage=leverage,
            maintenance_margin_rate=maintenance_margin_rate,
            maintenance_margin_deduction=maintenance_margin_deduction,
            extra_margin=extra_margin,
            fee_rate=fee_rate,
        )
    if formula in _BYBIT_2025_ISOLATED_FORMULAS:
        if margin_mode != "isolated":
            raise ValueError("Configured Bybit 2025 liquidation formula requires isolated margin mode.")
        return _bybit_usdt_usdc_isolated_2025(
            entry_price=entry_price,
            side=side,
            quantity=quantity,
            leverage=leverage,
            maintenance_margin_rate=maintenance_margin_rate,
            maintenance_margin_deduction=maintenance_margin_deduction,
            extra_margin=extra_margin,
            fee_rate=fee_rate,
        )
    if formula in _CROSS_AVAILABLE_BALANCE_FORMULAS:
        if margin_mode != "cross":
            raise ValueError("Configured cross liquidation formula requires cross margin mode.")
        return _linear_cross_available_balance(
            entry_price=entry_price,
            side=side,
            quantity=quantity,
            leverage=leverage,
            maintenance_margin_rate=maintenance_margin_rate,
            maintenance_margin_deduction=maintenance_margin_deduction,
            fee_rate=fee_rate,
            account_snapshot=account_snapshot,
        )
    raise ValueError(f"Unsupported liquidation_formula={formula!r}.")


def _linear_isolated_entry_price(
    *,
    entry_price: float,
    side: str,
    quantity: float,
    leverage: int,
    maintenance_margin_rate: float,
    maintenance_margin_deduction: float,
    extra_margin: float,
    fee_rate: float | None,
) -> tuple[float, float]:
    position_value = entry_price * quantity
    close_fee = _estimated_close_fee(position_value, leverage, side, fee_rate)
    initial_margin = position_value / leverage + close_fee
    maintenance_margin = max(
        0.0,
        position_value * maintenance_margin_rate - maintenance_margin_deduction + close_fee,
    )
    price_delta = (initial_margin - maintenance_margin) / quantity
    extra_margin_delta = extra_margin / quantity
    if side == "long":
        return entry_price - price_delta - extra_margin_delta, maintenance_margin
    return entry_price + price_delta + extra_margin_delta, maintenance_margin


def _bybit_usdt_usdc_isolated_2025(
    *,
    entry_price: float,
    side: str,
    quantity: float,
    leverage: int,
    maintenance_margin_rate: float,
    maintenance_margin_deduction: float,
    extra_margin: float,
    fee_rate: float | None,
) -> tuple[float, float]:
    taker_fee_rate = float(fee_rate or 0.0)
    position_value = entry_price * quantity
    maintenance_margin = max(
        0.0,
        position_value * maintenance_margin_rate - maintenance_margin_deduction,
    )
    if side == "long":
        fee_denominator = 1 - taker_fee_rate
        denominator = quantity - quantity * maintenance_margin_rate
        numerator = (
            position_value
            - position_value / leverage
            - _safe_divide(extra_margin, fee_denominator)
            - maintenance_margin_deduction
        )
    else:
        fee_denominator = 1 + taker_fee_rate
        denominator = quantity + quantity * maintenance_margin_rate
        numerator = (
            position_value
            + position_value / leverage
            + _safe_divide(extra_margin, fee_denominator)
            + maintenance_margin_deduction
        )
    if denominator <= 0:
        raise ValueError("Liquidation projection denominator must be positive.")
    return numerator / denominator, maintenance_margin


def _linear_cross_available_balance(
    *,
    entry_price: float,
    side: str,
    quantity: float,
    leverage: int,
    maintenance_margin_rate: float,
    maintenance_margin_deduction: float,
    fee_rate: float | None,
    account_snapshot: AccountRiskSnapshot | None,
) -> tuple[float, float]:
    if account_snapshot is None or account_snapshot.available_balance is None:
        raise ValueError("Cross liquidation projection requires account available_balance.")
    available_balance = float(account_snapshot.available_balance)
    position_value = entry_price * quantity
    close_fee = _estimated_close_fee(position_value, leverage, side, fee_rate)
    initial_margin = position_value / leverage + close_fee
    maintenance_margin = max(
        0.0,
        position_value * maintenance_margin_rate - maintenance_margin_deduction + close_fee,
    )
    distance = (available_balance + initial_margin - maintenance_margin) / quantity
    if side == "long":
        return entry_price - distance, maintenance_margin
    return entry_price + distance, maintenance_margin


def _estimated_close_fee(
    position_value: float,
    leverage: int,
    side: str,
    fee_rate: float | None,
) -> float:
    rate = max(0.0, float(fee_rate or 0.0))
    multiplier = 1 - 1 / leverage if side == "long" else 1 + 1 / leverage
    return position_value * max(0.0, multiplier) * rate


def _account_snapshot(
    value: AccountRiskSnapshot | Mapping[str, Any] | None,
) -> AccountRiskSnapshot | None:
    if value is None:
        return None
    if isinstance(value, AccountRiskSnapshot):
        return value
    return AccountRiskSnapshot.model_validate(value)


def _snapshot_value(snapshot: AccountRiskSnapshot | None, name: str) -> Any:
    if snapshot is None:
        return None
    return getattr(snapshot, name, None)


def _rule_value(rules: Mapping[str, Any] | object | None, *names: str) -> Any:
    if rules is None:
        return None
    for container in _rule_containers(rules):
        for name in names:
            value = _container_value(container, name)
            if value is not None:
                return value
    return None


def _rule_containers(rules: Mapping[str, Any] | object) -> list[Mapping[str, Any] | object]:
    containers: list[Mapping[str, Any] | object] = [rules]
    raw_payload = _container_value(rules, "raw_payload")
    if raw_payload is not None:
        containers.append(raw_payload)
    for container in list(containers):
        nested = _container_value(container, "liquidation")
        if nested is not None:
            containers.append(nested)
        tier = _container_value(container, "maintenance_margin")
        if tier is not None:
            containers.append(tier)
    return containers


def _container_value(container: Mapping[str, Any] | object, name: str) -> Any:
    if isinstance(container, Mapping):
        if name in container:
            return container[name]
        lowered = name.lower()
        for key, value in container.items():
            if isinstance(key, str) and key.lower() == lowered:
                return value
        return None
    return getattr(container, name, None)


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _number_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _number_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if text.endswith("%"):
                return float(Decimal(text[:-1].strip()) / Decimal("100"))
            return float(Decimal(text))
        except Exception:
            return None
    return None


def _normalized_formula(value: Any) -> str | None:
    text = _string_or_none(value)
    if text is None:
        return None
    return text.strip().lower().replace("-", "_").replace(" ", "_")


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_margin_mode(value: Any) -> str | None:
    text = _string_or_none(value)
    if text is None:
        return None
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    if normalized in {"isolated", "isolated_margin"}:
        return "isolated"
    if normalized in {"cross", "cross_margin"}:
        return "cross"
    if normalized in {"spot", "portfolio", "portfolio_margin", "unknown"}:
        return normalized
    return normalized


def _distance(entry_price: float, liquidation_price: float) -> tuple[float, float]:
    distance = abs(entry_price - liquidation_price)
    return distance, distance / entry_price * 100


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        raise ValueError("Liquidation projection fee denominator must be positive.")
    return numerator / denominator


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


liquidation_projection_service = LiquidationProjectionService()
