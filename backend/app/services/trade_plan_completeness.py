from __future__ import annotations

from typing import Any, Iterable, Literal, Mapping

from app.schemas.signal import RadarSignal, StrategySignal
from app.schemas.trade_plan import (
    TradePlan,
    TradePlanCompletenessResult,
    TradePlanInvalidation,
    TradePlanTarget,
)


CompletenessPolicy = Literal["off", "warning", "block"]
CompletenessAssessment = TradePlanCompletenessResult

FALLBACK_TARGET_SOURCES = {
    "fallback_r_multiple",
    "r_multiple_fallback",
    "risk_multiple_fallback",
    "atr_fallback",
    "one_r",
    "two_r",
    "three_r",
}
NON_STRUCTURAL_TARGET_SOURCES = set(FALLBACK_TARGET_SOURCES)
FALLBACK_TARGET_THESIS_SOURCES = {"risk_multiple_fallback"}

MISSING_SCORE_POLICY_KEY = "trade_plan_missing_score_policy"
MISSING_CONTEXT_POLICY_KEY = "trade_plan_missing_context_policy"
DEFAULT_MISSING_SCORE_POLICY: CompletenessPolicy = "warning"
DEFAULT_MISSING_CONTEXT_POLICY: CompletenessPolicy = "warning"

STRUCTURAL_FIELD_LABELS = {
    "entry": "entry",
    "structural_stop": "stop",
    "invalidation_thesis": "invalidation",
    "structural_target": "target",
}


class TradePlanCompletenessService:
    """Builds the normalized trade-plan quality assessment used by pipeline/RiskGate."""

    def assess(
        self,
        signal: StrategySignal | RadarSignal | None,
        trade_plan: TradePlan | None,
        *,
        settings: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        production_mode: bool = False,
    ) -> CompletenessAssessment:
        score_policy = _completeness_policy(
            settings,
            MISSING_SCORE_POLICY_KEY,
            DEFAULT_MISSING_SCORE_POLICY,
        )
        context_policy = _completeness_policy(
            settings,
            MISSING_CONTEXT_POLICY_KEY,
            DEFAULT_MISSING_CONTEXT_POLICY,
        )
        if trade_plan is None:
            return _assessment_for_missing_trade_plan(
                score_policy=score_policy,
                context_policy=context_policy,
                production_mode=production_mode,
            )

        fallback_stop_used = _fallback_stop_used(trade_plan)
        fallback_targets_used = _fallback_targets_used(trade_plan.targets, trade_plan.metadata)
        fallback_used = (
            _truthy_metadata_value(trade_plan.metadata, "fallback_used")
            or _truthy_metadata_value(trade_plan.risk_rules.metadata, "fallback_used")
            or fallback_stop_used
            or fallback_targets_used
        )
        has_entry = _has_entry(trade_plan)
        has_structural_stop = _positive_number(trade_plan.stop_loss) and not fallback_stop_used
        has_invalidation_thesis = _has_invalidation_thesis(trade_plan.invalidation)
        has_structural_target = any(_is_structural_target(target) for target in trade_plan.targets)
        has_score = _has_signal_score(signal)
        has_context = _has_context(signal=signal, trade_plan=trade_plan, context=context)

        missing: list[str] = []
        missing_fields: list[str] = []
        if not has_entry:
            missing.append("entry")
            missing_fields.append("entry")
        if not has_structural_stop:
            missing.append("structural_stop")
            missing_fields.append("stop")
        if not has_invalidation_thesis:
            missing.append("invalidation_thesis")
            missing_fields.append("invalidation")
        if not has_structural_target:
            missing.append("structural_target")
            missing_fields.append("target")

        warnings: list[str] = []
        blockers: list[str] = []
        if fallback_stop_used:
            warnings.append("Trade plan uses a fallback stop.")
        if fallback_targets_used:
            warnings.append("Trade plan uses fallback targets.")
        if fallback_used and not fallback_stop_used and not fallback_targets_used:
            warnings.append("Trade plan has fallback provenance metadata.")
        if missing:
            blockers.append(_execution_blocker_message(missing))

        score_warning_or_blocker = _quality_gap_reason(
            field="score",
            present=has_score,
            policy=score_policy,
            missing_fields=missing_fields,
        )
        context_warning_or_blocker = _quality_gap_reason(
            field="context",
            present=has_context,
            policy=context_policy,
            missing_fields=missing_fields,
        )
        _apply_quality_gap(
            score_warning_or_blocker,
            policy=score_policy,
            warnings=warnings,
            blockers=blockers,
        )
        _apply_quality_gap(
            context_warning_or_blocker,
            policy=context_policy,
            warnings=warnings,
            blockers=blockers,
        )

        target_sources = [
            str(target.source)
            for target in trade_plan.targets
            if target.source is not None
        ]
        structural_complete = not missing and not fallback_stop_used
        complete = structural_complete and not blockers
        execution_allowed = not blockers
        warning_fields = [
            field
            for field in ("score", "context")
            if field in missing_fields and field not in _blocker_fields(missing_fields, blockers)
        ]
        return TradePlanCompletenessResult(
            complete=complete,
            fallback_used=fallback_used,
            fallback_stop_used=fallback_stop_used,
            fallback_targets_used=fallback_targets_used,
            has_entry=has_entry,
            has_structural_stop=has_structural_stop,
            has_invalidation_thesis=has_invalidation_thesis,
            has_structural_target=has_structural_target,
            has_score=has_score,
            has_context=has_context,
            missing=missing,
            missing_fields=_dedupe(missing_fields),
            warnings=_dedupe(warnings),
            blockers=_dedupe(blockers),
            execution_allowed_virtual=execution_allowed,
            execution_allowed_real=execution_allowed,
            metadata={
                "source": "trade_plan_completeness",
                "structural_complete": structural_complete,
                "production_mode": production_mode,
                "target_sources": target_sources,
                "invalidation_source": _metadata_string(
                    trade_plan.invalidation.metadata if trade_plan.invalidation else {},
                    "source",
                ),
                "score_policy": score_policy,
                "context_policy": context_policy,
                "warning_fields": warning_fields,
                "blocker_fields": _blocker_fields(missing_fields, blockers),
            },
        )

    def from_trade_plan_metadata(self, trade_plan: TradePlan | None) -> CompletenessAssessment | None:
        if trade_plan is None:
            return None
        for metadata in (trade_plan.metadata, trade_plan.risk_rules.metadata):
            raw = metadata.get("trade_plan_completeness")
            if isinstance(raw, TradePlanCompletenessResult):
                return raw
            if isinstance(raw, dict):
                return TradePlanCompletenessResult.model_validate(raw)
        return None

    def assess_or_restore(
        self,
        signal: StrategySignal | RadarSignal | None,
        trade_plan: TradePlan | None,
        *,
        settings: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        production_mode: bool = False,
    ) -> CompletenessAssessment:
        restored = self.from_trade_plan_metadata(trade_plan)
        if restored is not None:
            return restored
        return self.assess(
            signal,
            trade_plan,
            settings=settings,
            context=context,
            production_mode=production_mode,
        )


class TradePlanCompletenessCheck:
    """Backward-compatible structural facade over TradePlanCompletenessService."""

    def evaluate(self, trade_plan: TradePlan | None) -> TradePlanCompletenessResult:
        return trade_plan_completeness_service.assess(
            None,
            trade_plan,
            settings={
                MISSING_SCORE_POLICY_KEY: "off",
                MISSING_CONTEXT_POLICY_KEY: "off",
            },
        )


def _assessment_for_missing_trade_plan(
    *,
    score_policy: CompletenessPolicy,
    context_policy: CompletenessPolicy,
    production_mode: bool,
) -> CompletenessAssessment:
    missing_fields = ["trade_plan", "entry", "stop", "target", "invalidation"]
    blockers = ["Trade plan is missing; execution is blocked."]
    warnings: list[str] = ["Trade plan is missing."]
    for field, policy in (("score", score_policy), ("context", context_policy)):
        reason = _quality_gap_reason(
            field=field,
            present=False,
            policy=policy,
            missing_fields=missing_fields,
        )
        _apply_quality_gap(reason, policy=policy, warnings=warnings, blockers=blockers)
    return TradePlanCompletenessResult(
        complete=False,
        has_entry=False,
        has_structural_stop=False,
        has_invalidation_thesis=False,
        has_structural_target=False,
        has_score=False,
        has_context=False,
        missing=["trade_plan", "entry", "structural_stop", "invalidation_thesis", "structural_target"],
        missing_fields=_dedupe(missing_fields),
        warnings=_dedupe(warnings),
        blockers=_dedupe(blockers),
        execution_allowed_virtual=False,
        execution_allowed_real=False,
        metadata={
            "source": "trade_plan_completeness",
            "structural_complete": False,
            "production_mode": production_mode,
            "score_policy": score_policy,
            "context_policy": context_policy,
            "blocker_fields": ["trade_plan", "entry", "stop", "target", "invalidation"],
        },
    )


def _execution_blocker_message(missing: Iterable[str]) -> str:
    labels = [
        STRUCTURAL_FIELD_LABELS.get(field, field)
        for field in missing
    ]
    return f"Trade plan incomplete: {', '.join(labels)}; execution is blocked."


def _quality_gap_reason(
    *,
    field: Literal["score", "context"],
    present: bool,
    policy: CompletenessPolicy,
    missing_fields: list[str],
) -> str | None:
    if present or policy == "off":
        return None
    if field not in missing_fields:
        missing_fields.append(field)
    if field == "score":
        return "Trade plan score is missing."
    return "Trade plan context is missing."


def _apply_quality_gap(
    reason: str | None,
    *,
    policy: CompletenessPolicy,
    warnings: list[str],
    blockers: list[str],
) -> None:
    if reason is None:
        return
    if policy == "block":
        blockers.append(f"{reason} Execution is blocked by completeness policy.")
    elif policy == "warning":
        warnings.append(f"{reason} Completeness policy recorded a warning.")


def _blocker_fields(missing_fields: Iterable[str], blockers: Iterable[str]) -> list[str]:
    if not list(blockers):
        return []
    fields = [field for field in missing_fields if field not in {"score", "context"}]
    blocker_text = " ".join(blockers).lower()
    for field in ("score", "context"):
        if field in missing_fields and field in blocker_text:
            fields.append(field)
    return _dedupe(fields)


def _fallback_stop_used(trade_plan: TradePlan) -> bool:
    metadata_sources = (
        trade_plan.metadata,
        trade_plan.risk_rules.metadata,
        trade_plan.invalidation.metadata if trade_plan.invalidation is not None else {},
    )
    if any(_truthy_metadata_value(metadata, "fallback_stop_used") for metadata in metadata_sources):
        return True
    source = _first_metadata_string(metadata_sources, ("fallback_stop_source", "stop_source", "source"))
    if source is None:
        return False
    normalized = source.lower()
    return "fallback" in normalized or normalized in {"atr", "synthetic_atr"}


def _fallback_targets_used(
    targets: Iterable[TradePlanTarget],
    trade_plan_metadata: dict[str, Any],
) -> bool:
    if _truthy_metadata_value(trade_plan_metadata, "fallback_targets_used"):
        return True
    return any(_is_fallback_target(target) for target in targets)


def _is_fallback_target(target: TradePlanTarget) -> bool:
    source_values = [
        target.source,
        target.thesis.source if target.thesis is not None else None,
        _metadata_string(target.metadata, "fallback_target_source"),
        _metadata_string(target.metadata, "target_source"),
    ]
    if _truthy_metadata_value(target.metadata, "fallback_target_used"):
        return True
    for value in source_values:
        if value is None:
            continue
        normalized = value.lower()
        if "fallback" in normalized or normalized in FALLBACK_TARGET_SOURCES:
            return True
    return False


def _is_structural_target(target: TradePlanTarget) -> bool:
    if target.price is None or not _positive_number(target.price) or _is_fallback_target(target):
        return False
    if target.thesis is not None:
        return target.thesis.source not in FALLBACK_TARGET_THESIS_SOURCES
    source = target.source
    if source is None:
        return False
    return source.lower() not in NON_STRUCTURAL_TARGET_SOURCES


def _has_entry(trade_plan: TradePlan) -> bool:
    entry = trade_plan.entry
    return any(
        _positive_number(value)
        for value in (entry.price, entry.min_price, entry.max_price)
    )


def _has_invalidation_thesis(invalidation: TradePlanInvalidation | None) -> bool:
    if invalidation is None:
        return False
    if invalidation.conditions:
        return True
    source = _metadata_string(invalidation.metadata, "source")
    if source is None:
        return False
    normalized = source.lower()
    if "fallback" in normalized:
        return False
    return normalized not in {"legacy_fields", "atr", "synthetic_atr"}


def _has_signal_score(signal: StrategySignal | RadarSignal | None) -> bool:
    if signal is None:
        return False
    if getattr(signal, "score", 0) > 0:
        return True
    breakdown = getattr(signal, "score_breakdown", None)
    return getattr(breakdown, "total", 0) > 0


def _has_context(
    *,
    signal: StrategySignal | RadarSignal | None,
    trade_plan: TradePlan,
    context: Mapping[str, Any] | None,
) -> bool:
    if _mapping_has_context(context):
        return True
    if signal is not None:
        for attribute in ("quality", "regime", "setup", "confirmation", "no_trade_filter"):
            if getattr(signal, attribute, None) is not None:
                return True
    metadata_sources = [trade_plan.metadata, trade_plan.entry.metadata, trade_plan.risk_rules.metadata]
    if trade_plan.invalidation is not None:
        metadata_sources.append(trade_plan.invalidation.metadata)
    context_keys = {
        "alpha_context_used",
        "context_timeframe",
        "market_context_source",
        "nearest_htf_target_source",
        "target_source",
        "structural_zone_source",
    }
    for metadata in metadata_sources:
        if any(key in metadata and metadata.get(key) is not None for key in context_keys):
            return True
    return False


def _mapping_has_context(context: Mapping[str, Any] | None) -> bool:
    if not context:
        return False
    for key in (
        "quality",
        "regime",
        "setup",
        "confirmation",
        "market_quality",
        "alpha_context",
        "context_features",
        "context_features_by_timeframe",
        "support_resistance_by_timeframe",
    ):
        value = context.get(key)
        if value is None:
            continue
        if isinstance(value, Mapping) and not value:
            continue
        return True
    return False


def _completeness_policy(
    settings: Mapping[str, Any] | None,
    key: str,
    default: CompletenessPolicy,
) -> CompletenessPolicy:
    value = str((settings or {}).get(key, default)).strip().lower()
    if value in {"off", "disabled", "ignore"}:
        return "off"
    if value in {"block", "blocked", "hard"}:
        return "block"
    return "warning"


def _positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _truthy_metadata_value(metadata: dict[str, Any], key: str) -> bool:
    value = metadata.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _first_metadata_string(
    metadata_sources: Iterable[dict[str, Any]],
    keys: Iterable[str],
) -> str | None:
    for metadata in metadata_sources:
        for key in keys:
            value = _metadata_string(metadata, key)
            if value is not None:
                return value
    return None


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


trade_plan_completeness_service = TradePlanCompletenessService()
