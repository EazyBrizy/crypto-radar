from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.domain.signal_status import is_execution_candidate_status, is_terminal_signal_status
from app.schemas.risk import AccountRiskSnapshot, RiskDecision
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest, RealExecutionPlan
from app.schemas.user import RiskManagementSettings
from app.services.risk_fee_rate import RiskFeeRateSnapshot
from app.services.trade_plan_completeness import (
    MISSING_CONTEXT_POLICY_KEY,
    MISSING_SCORE_POLICY_KEY,
    trade_plan_completeness_service,
)

FALLBACK_STOP_SOURCES = {"atr", "synthetic_atr", "fixed_percent", "risk_settings"}
TERMINAL_ORDER_STATUSES = {"cancelled", "canceled", "rejected", "expired"}


@dataclass(frozen=True)
class RealExecutionReadinessResult:
    ready: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RealExecutionReadinessService:
    """Checks live-order readiness after risk gate and before adapter placement."""

    def evaluate(
        self,
        *,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        risk_decision: RiskDecision,
        execution_plan: RealExecutionPlan,
        risk_settings: RiskManagementSettings,
        reference: Any,
        fee_rate: RiskFeeRateSnapshot | None,
        adapter: Any,
        account_snapshot: AccountRiskSnapshot | None = None,
    ) -> RealExecutionReadinessResult:
        adapter_is_dry_run = bool(getattr(adapter, "is_dry_run", False))
        live_adapter = not adapter_is_dry_run
        blockers: list[str] = []
        warnings: list[str] = []

        blockers.extend(_signal_readiness_blockers(signal))
        blockers.extend(_decision_snapshot_blockers(signal))
        blockers.extend(_trade_plan_blockers(signal))
        blockers.extend(_execution_plan_blockers(execution_plan, risk_decision))
        blockers.extend(_futures_blockers(request, risk_decision))

        live_messages = [
            *_live_feature_flag_blockers(risk_settings, live_adapter=live_adapter),
            *_live_adapter_blockers(adapter),
            *_exchange_rule_blockers(reference, risk_decision),
            *_real_account_blockers(account_snapshot, reference=reference),
            *_fee_rate_blockers(fee_rate, risk_settings),
            *_reconciliation_blockers(reference, adapter),
        ]
        if live_adapter:
            blockers.extend(live_messages)
        else:
            warnings.extend(live_messages)

        metadata = {
            "source": "real_execution_readiness",
            "adapter": getattr(adapter, "name", "unknown"),
            "adapter_is_dry_run": adapter_is_dry_run,
            "live_adapter": live_adapter,
            "real_execution_enabled": risk_settings.real_execution_enabled,
            "signal_status": signal.status,
            "decision_execution_allowed_real": (
                signal.decision.execution_allowed_real if signal.decision is not None else None
            ),
            "exchange_rule_status": risk_decision.risk_check.exchange_rule_status,
            "real_account_snapshot_status": _account_snapshot_status(account_snapshot, reference),
            "real_account_snapshot_source": _account_snapshot_source(account_snapshot, reference),
            "real_account_snapshot_fetched_at": (
                account_snapshot.fetched_at.isoformat()
                if account_snapshot is not None and account_snapshot.fetched_at is not None
                else None
            ),
            "position_reconciliation_enabled": _bool_attr(
                reference,
                "position_reconciliation_enabled",
                "real_position_reconciliation_enabled",
            )
            or _bool_attr(adapter, "position_reconciliation_enabled"),
            "fee_rate_source": fee_rate.source if fee_rate is not None else None,
            "fee_rate_ttl_seconds": risk_settings.real_fee_rate_ttl_seconds,
            "fee_rate_age_seconds": _fee_rate_age_seconds(fee_rate),
            "blockers": list(blockers),
            "warnings": list(warnings),
        }
        return RealExecutionReadinessResult(
            ready=not blockers,
            blockers=_dedupe(blockers),
            warnings=_dedupe(warnings),
            metadata=metadata,
        )


def _signal_readiness_blockers(signal: RadarSignal) -> list[str]:
    if is_terminal_signal_status(signal.status):
        return [f"Signal status {signal.status!r} is not eligible for real execution."]
    if not is_execution_candidate_status(signal.status):
        return ["Signal status must be entry_touched, actionable, or confirmed before real execution."]
    return []


def _decision_snapshot_blockers(signal: RadarSignal) -> list[str]:
    decision = signal.decision
    if decision is None:
        return ["Signal decision snapshot is required for real execution readiness."]
    blockers: list[str] = []
    if not decision.setup_valid:
        blockers.append("Signal setup is not valid in the decision snapshot.")
    if not decision.trade_plan_valid:
        blockers.append("Trade plan is not valid in the decision snapshot.")
    if not decision.signal_actionable:
        blockers.append("Signal decision snapshot is not actionable.")
    if decision.execution_allowed_real is not True:
        blockers.append("Decision snapshot does not allow real execution.")
    return blockers


def _trade_plan_blockers(signal: RadarSignal) -> list[str]:
    completeness = trade_plan_completeness_service.assess_or_restore(
        signal,
        signal.trade_plan,
        settings={
            MISSING_SCORE_POLICY_KEY: "off",
            MISSING_CONTEXT_POLICY_KEY: "off",
        },
        production_mode=True,
    )
    blockers: list[str] = []
    if not completeness.execution_allowed_real:
        blockers.extend(
            f"Trade plan completeness blocks real execution: {blocker}"
            for blocker in (completeness.blockers or ["normalized completeness assessment failed"])
        )
    if not completeness.has_structural_stop:
        blockers.append("Real execution requires a structural stop.")
    if completeness.fallback_stop_used:
        blockers.append("Real execution blocks fallback stop plans.")
    if not completeness.has_invalidation_thesis:
        blockers.append("Real execution requires an invalidation thesis.")
    if not completeness.has_structural_target and not _has_valid_runner_policy(signal.trade_plan):
        blockers.append("Real execution requires a structural target or validated runner exit policy.")
    if completeness.fallback_targets_used:
        blockers.append("Real execution blocks fallback-only take-profit plans.")
    if completeness.fallback_used:
        blockers.append("Real execution blocks fallback-only trade plans.")
    return blockers


def _execution_plan_blockers(
    execution_plan: RealExecutionPlan,
    risk_decision: RiskDecision,
) -> list[str]:
    blockers: list[str] = []
    orders = execution_plan.planned_orders
    entry_orders = [order for order in orders if order.role == "entry"]
    stop_orders = [order for order in orders if order.role == "protective_stop"]
    take_profit_orders = [order for order in orders if order.role == "take_profit"]

    if execution_plan.idempotency_key.strip() == "":
        blockers.append("Real execution plan idempotency key is required.")
    if execution_plan.client_order_id.strip() == "":
        blockers.append("Real execution plan client_order_id is required.")
    if len(entry_orders) != 1:
        blockers.append("Real execution plan must contain exactly one entry order.")
    if not stop_orders:
        blockers.append("Real execution plan must contain a protective stop order.")
    if not take_profit_orders:
        blockers.append("Real execution plan must contain take-profit orders before entry placement.")
    if not risk_decision.risk_check.protective_orders_allowed:
        blockers.append("Risk state does not allow protective orders.")

    seen_client_ids: set[str] = set()
    seen_idempotency_keys: set[str] = set()
    take_profit_quantity = 0.0
    take_profit_close_percent = 0.0
    for order in orders:
        if not order.client_order_id.strip():
            blockers.append(f"{order.role} order client_order_id is required.")
        elif order.client_order_id in seen_client_ids:
            blockers.append(f"Duplicate client_order_id in real execution plan: {order.client_order_id}.")
        seen_client_ids.add(order.client_order_id)

        if not order.idempotency_key.strip():
            blockers.append(f"{order.role} order idempotency_key is required.")
        elif order.idempotency_key in seen_idempotency_keys:
            blockers.append(f"Duplicate idempotency_key in real execution plan: {order.idempotency_key}.")
        seen_idempotency_keys.add(order.idempotency_key)

        if order.role in {"protective_stop", "take_profit"} and not order.reduce_only:
            blockers.append(f"{order.role} order must be reduce-only.")
        if order.role == "protective_stop" and order.stop_price is None:
            blockers.append("Protective stop order must include stop_price.")
        if order.role == "take_profit":
            take_profit_quantity += order.quantity
            take_profit_close_percent += order.close_percent or 0.0
            if order.price is None:
                blockers.append("Take-profit order must include price.")
            if order.close_percent is None or order.close_percent <= 0:
                blockers.append("Take-profit order must include positive close_percent.")

    if take_profit_quantity > execution_plan.quantity + 0.00000001:
        blockers.append("Take-profit quantities exceed planned position quantity.")
    if take_profit_close_percent > 100.00000001:
        blockers.append("Take-profit close_percent exceeds 100%.")
    if _is_fallback_stop_source(risk_decision.stop_loss_plan.source):
        blockers.append("Real execution blocks fallback stop-loss sources.")
    if risk_decision.take_profit_plan.source in {"risk_settings", "trade_plan_invalid"}:
        blockers.append("Real execution requires take-profit targets from a valid trade plan.")
    return blockers


def _futures_blockers(
    request: ManualConfirmRequest,
    risk_decision: RiskDecision,
) -> list[str]:
    if risk_decision.instrument_type != "futures" and request.leverage <= 1:
        return []
    plan = risk_decision.futures_risk_plan
    if plan is None:
        return ["Futures real execution requires liquidation projection."]
    blockers: list[str] = []
    if plan.liquidation_price is None:
        blockers.append("Futures real execution requires liquidation projection.")
    if plan.status != "passed":
        blockers.append(plan.message)
    return blockers


def _live_feature_flag_blockers(
    risk_settings: RiskManagementSettings,
    *,
    live_adapter: bool,
) -> list[str]:
    if live_adapter and not risk_settings.real_execution_enabled:
        return ["Live real execution is disabled by real_execution_enabled=false."]
    return []


def _live_adapter_blockers(adapter: Any) -> list[str]:
    if _bool_attr(adapter, "protective_order_guarantee", "protective_orders_guaranteed"):
        return []
    return ["Live adapter must guarantee protective stop/target order placement before entry."]


def _exchange_rule_blockers(reference: Any, risk_decision: RiskDecision) -> list[str]:
    blockers: list[str] = []
    if risk_decision.risk_check.exchange_rule_status != "fresh":
        blockers.append("Fresh exchange instrument rules are required for live real execution.")
    if reference is None:
        blockers.append("Exchange rule reference snapshot is required for live real execution.")
        return blockers
    if _positive_attr(reference, "exchange_qty_step", "qty_step") is None:
        blockers.append("Exchange qty_step is required for live real execution.")
    if _positive_attr(reference, "exchange_tick_size", "tick_size") is None:
        blockers.append("Exchange tick_size is required for live real execution.")
    if _positive_attr(reference, "exchange_min_notional", "min_notional") is None:
        blockers.append("Exchange min_notional is required for live real execution.")
    return blockers


def _real_account_blockers(
    account_snapshot: AccountRiskSnapshot | None,
    *,
    reference: Any,
) -> list[str]:
    if account_snapshot is None:
        account_snapshot = _legacy_account_snapshot(reference)
    if account_snapshot is None:
        return ["Fresh real account equity/balance snapshot is required for live real execution."]
    blockers: list[str] = []
    if account_snapshot.status != "fresh":
        blockers.append("Fresh real account equity/balance snapshot is required for live real execution.")
    if account_snapshot.source != "exchange":
        blockers.append("Live real execution requires an exchange account snapshot, not request/demo balance.")
    if account_snapshot.account_equity is None or account_snapshot.account_equity <= 0:
        blockers.append("Real account equity is required; request.account_balance cannot authorize live sizing.")
    if account_snapshot.available_balance is None or account_snapshot.available_balance < 0:
        blockers.append("Real available balance is required; virtual equity cannot authorize live sizing.")
    return blockers


def _account_snapshot_status(
    account_snapshot: AccountRiskSnapshot | None,
    reference: Any,
) -> str | None:
    if account_snapshot is not None:
        return account_snapshot.status
    legacy = _legacy_account_snapshot(reference)
    return legacy.status if legacy is not None else None


def _account_snapshot_source(
    account_snapshot: AccountRiskSnapshot | None,
    reference: Any,
) -> str | None:
    if account_snapshot is not None:
        return account_snapshot.source
    legacy = _legacy_account_snapshot(reference)
    return legacy.source if legacy is not None else None


def _legacy_account_snapshot(reference: Any) -> AccountRiskSnapshot | None:
    snapshot = _first_attr(reference, "account_snapshot")
    if isinstance(snapshot, AccountRiskSnapshot):
        return snapshot
    status = _first_attr(reference, "real_account_snapshot_status", "account_snapshot_status", "real_balance_status")
    equity = _positive_attr(reference, "real_account_equity", "account_equity")
    available = _number_attr(reference, "real_available_balance", "available_balance")
    if status is None and equity is None and available is None:
        return None
    normalized_status = str(status or "missing").strip().lower()
    if normalized_status not in {"fresh", "stale", "missing"}:
        normalized_status = "missing"
    return AccountRiskSnapshot(
        status=normalized_status,
        account_equity=equity,
        available_balance=available,
        margin_mode=_first_attr(reference, "real_margin_mode", "margin_mode"),
        source="exchange",
    )


def _fee_rate_blockers(
    fee_rate: RiskFeeRateSnapshot | None,
    risk_settings: RiskManagementSettings,
) -> list[str]:
    if fee_rate is None:
        return ["Fresh exchange fee-rate snapshot is required for live real execution."]
    blockers: list[str] = []
    if fee_rate.source in {"fallback", "conservative_fallback", "manual_request"}:
        blockers.append("Live real execution requires exchange fee rates, not fallback/manual fees.")
    ttl_seconds = risk_settings.real_fee_rate_ttl_seconds
    if ttl_seconds > 0:
        age_seconds = _fee_rate_age_seconds(fee_rate)
        if age_seconds is None:
            blockers.append("Fee-rate fetched_at is required for TTL validation.")
        elif age_seconds > ttl_seconds:
            blockers.append("Fee-rate snapshot is stale for live real execution.")
    return blockers


def _reconciliation_blockers(reference: Any, adapter: Any) -> list[str]:
    enabled = (
        _bool_attr(reference, "position_reconciliation_enabled", "real_position_reconciliation_enabled")
        or _bool_attr(adapter, "position_reconciliation_enabled")
    )
    if enabled:
        return []
    return ["Position reconciliation must be enabled before live real execution."]


def _has_valid_runner_policy(trade_plan: Any) -> bool:
    if trade_plan is None:
        return False
    metadata_sources = [trade_plan.metadata, trade_plan.risk_rules.metadata]
    invalidation = trade_plan.invalidation
    if invalidation is not None:
        metadata_sources.append(invalidation.metadata)
    for metadata in metadata_sources:
        if _truthy(metadata.get("valid_runner_exit_policy")) or _truthy(metadata.get("runner_exit_valid")):
            return True
        if _truthy(metadata.get("trailing_runner_enabled")) and _truthy(metadata.get("runner_invalidation_valid")):
            return True
    for target in trade_plan.targets:
        action = str(target.action or "").strip().lower()
        close_percent = str(target.close_percent or "").strip().lower()
        if "runner" in action or close_percent == "runner":
            if _truthy(target.metadata.get("valid_runner_exit_policy")):
                return True
    return False


def _is_fallback_stop_source(source: str) -> bool:
    normalized = source.strip().lower()
    return normalized in FALLBACK_STOP_SOURCES or "fallback" in normalized


def _fee_rate_age_seconds(fee_rate: RiskFeeRateSnapshot | None) -> float | None:
    if fee_rate is None or fee_rate.fetched_at is None:
        return None
    fetched_at = fee_rate.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - fetched_at.astimezone(timezone.utc)).total_seconds())


def _positive_attr(target: Any, *names: str) -> float | None:
    value = _first_attr(target, *names)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _number_attr(target: Any, *names: str) -> float | None:
    value = _first_attr(target, *names)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_attr(target: Any, *names: str) -> bool:
    value = _first_attr(target, *names)
    return _truthy(value)


def _first_attr(target: Any, *names: str) -> Any:
    if target is None:
        return None
    for name in names:
        if hasattr(target, name):
            return getattr(target, name)
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "fresh", "enabled"}
    return bool(value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


real_execution_readiness_service = RealExecutionReadinessService()
