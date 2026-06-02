from __future__ import annotations

from typing import Any

from app.schemas.signal import (
    SignalConfirmationSnapshot,
    SignalExitPlanSnapshot,
    SignalInvalidationSnapshot,
    SignalLayerCheck,
    StrategySignal,
)
from app.schemas.trade_plan import (
    TargetThesis,
    TradePlan,
    TradePlanCompletenessResult,
    TradePlanInvalidation,
    TradePlanTarget,
    build_trade_plan_from_legacy_fields,
)
from app.services.risk_reward_assessment import RiskRewardAssessment


class TradePlanEnrichmentService:
    """Normalizes and enriches trade plans without deciding execution eligibility."""

    def ensure_trade_plan(self, signal: StrategySignal) -> StrategySignal:
        if signal.trade_plan is not None:
            return signal
        return signal.model_copy(update={"trade_plan": trade_plan_from_signal(signal)})

    def enrich(
        self,
        *,
        signal: StrategySignal,
        exit_plan: SignalExitPlanSnapshot,
        invalidation: SignalInvalidationSnapshot,
        risk_reward: RiskRewardAssessment,
    ) -> TradePlan:
        trade_plan = signal.trade_plan or trade_plan_from_signal(signal)
        targets = [_trade_plan_target_from_exit_target(target) for target in exit_plan.targets]
        risk_metadata = dict(trade_plan.risk_rules.metadata)
        for key in ("time_stop_bars", "time_stop"):
            value = invalidation.metadata.get(key)
            if value is not None:
                risk_metadata[key] = value
        risk_rules = trade_plan.risk_rules.model_copy(
            update={
                "risk_reward": signal.risk_reward,
                "first_target_rr": risk_reward.first_target_rr,
                "final_target_rr": risk_reward.final_target_rr,
                "selected_rr": risk_reward.rr,
                "selected_rr_target": risk_reward.target_key,
                "min_rr_ratio": risk_reward.min_rr,
                "metadata": risk_metadata,
            }
        )
        enriched_invalidation = TradePlanInvalidation.model_validate(
            invalidation.model_dump(mode="json")
        )
        if trade_plan.invalidation is not None:
            enriched_invalidation = enriched_invalidation.model_copy(
                update={
                    "metadata": {
                        **trade_plan.invalidation.metadata,
                        **enriched_invalidation.metadata,
                    }
                }
            )
        return trade_plan.model_copy(
            update={
                "targets": targets or trade_plan.targets,
                "invalidation": enriched_invalidation,
                "risk_rules": risk_rules,
            },
            deep=True,
        )

    def attach_completeness_metadata(
        self,
        *,
        trade_plan: TradePlan,
        completeness: TradePlanCompletenessResult,
        production_mode: bool,
    ) -> TradePlan:
        completeness_metadata = trade_plan_completeness_metadata(completeness, production_mode)
        metadata = dict(trade_plan.metadata)
        metadata.update(completeness_metadata)
        metadata["trade_plan_completeness"] = completeness.model_dump(mode="json")
        risk_metadata = dict(trade_plan.risk_rules.metadata)
        risk_metadata.update(completeness_metadata)
        risk_rules = trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata})
        return trade_plan.model_copy(
            update={
                "metadata": metadata,
                "risk_rules": risk_rules,
            },
            deep=True,
        )

    def annotate_confirmation_completeness(
        self,
        *,
        confirmation: SignalConfirmationSnapshot,
        completeness: TradePlanCompletenessResult,
        production_mode: bool,
    ) -> SignalConfirmationSnapshot:
        if completeness.complete:
            status = "passed"
        elif production_mode:
            status = "failed"
        else:
            status = "warning"
        check = SignalLayerCheck(
            name="trade_plan_completeness",
            status=status,
            reason=trade_plan_completeness_reason(completeness, production_mode),
            metadata=trade_plan_completeness_metadata(completeness, production_mode),
        )
        return confirmation.model_copy(
            update={
                "passed": confirmation.passed and status != "failed",
                "checks": [*confirmation.checks, check],
            }
        )


def trade_plan_from_signal(signal: StrategySignal) -> TradePlan:
    return build_trade_plan_from_legacy_fields(
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
    )


def trade_plan_completeness_metadata(
    completeness: TradePlanCompletenessResult,
    production_mode: bool,
) -> dict[str, Any]:
    return {
        "trade_plan_complete": completeness.complete,
        "fallback_used": completeness.fallback_used,
        "fallback_stop_used": completeness.fallback_stop_used,
        "fallback_targets_used": completeness.fallback_targets_used,
        "has_structural_stop": completeness.has_structural_stop,
        "has_invalidation_thesis": completeness.has_invalidation_thesis,
        "has_structural_target": completeness.has_structural_target,
        "missing": list(completeness.missing),
        "research_mode": not production_mode,
        "production_mode": production_mode,
        "signal_actionable": completeness.complete or not production_mode,
        "execution_allowed_virtual": completeness.complete or not production_mode,
        "execution_allowed_real": completeness.complete and production_mode,
        "decision_scope": "production" if production_mode else "research",
    }


def trade_plan_completeness_reason(
    completeness: TradePlanCompletenessResult,
    production_mode: bool,
) -> str:
    if completeness.complete:
        return "Trade plan has structural stop, invalidation and target thesis."
    if production_mode:
        return trade_plan_incomplete_status_reason(completeness)
    return "Trade plan is research-compatible but incomplete for production actionability."


def trade_plan_incomplete_status_reason(completeness: TradePlanCompletenessResult) -> str:
    missing = ", ".join(completeness.missing) if completeness.missing else "structural trade plan"
    return f"Trade plan incomplete: {missing}; production actionability is blocked."


def _trade_plan_target_from_exit_target(target: dict[str, Any]) -> TradePlanTarget:
    metadata = {
        key: value
        for key, value in target.items()
        if key not in {"label", "price", "r_multiple", "action", "close_percent", "source", "thesis"}
    }
    existing_metadata = target.get("metadata")
    if isinstance(existing_metadata, dict):
        metadata.update(existing_metadata)
    thesis = _target_thesis_or_none(target.get("thesis"))
    return TradePlanTarget(
        label=str(target.get("label") or "target"),
        price=_number_or_none(target.get("price")),
        r_multiple=_number_or_none(target.get("r_multiple")),
        action=str(target["action"]) if target.get("action") is not None else None,
        close_percent=target.get("close_percent"),
        source=str(target["source"]) if target.get("source") is not None else None,
        thesis=thesis,
        metadata=metadata,
    )


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _target_thesis_or_none(value: Any) -> TargetThesis | None:
    if value is None:
        return None
    if isinstance(value, TargetThesis):
        return value
    if isinstance(value, dict):
        return TargetThesis.model_validate(value)
    return None


trade_plan_enrichment_service = TradePlanEnrichmentService()
