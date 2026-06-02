from __future__ import annotations

from typing import Any, Iterable

from app.schemas.trade_plan import (
    TradePlan,
    TradePlanCompletenessResult,
    TradePlanInvalidation,
    TradePlanTarget,
)


FALLBACK_TARGET_SOURCES = {
    "fallback_r_multiple",
    "r_multiple_fallback",
    "risk_multiple_fallback",
    "atr_fallback",
    "one_r",
    "two_r",
    "three_r",
}
NON_STRUCTURAL_TARGET_SOURCES = {"legacy_fields", *FALLBACK_TARGET_SOURCES}
FALLBACK_TARGET_THESIS_SOURCES = {"risk_multiple_fallback"}


class TradePlanCompletenessCheck:
    """Evaluates whether a trade plan has enough structure for production action."""

    def evaluate(self, trade_plan: TradePlan | None) -> TradePlanCompletenessResult:
        if trade_plan is None:
            return TradePlanCompletenessResult(
                complete=False,
                has_structural_stop=False,
                has_invalidation_thesis=False,
                has_structural_target=False,
                missing=["trade_plan"],
                warnings=["Trade plan is missing."],
                metadata={"source": "trade_plan_completeness"},
            )

        fallback_stop_used = _fallback_stop_used(trade_plan)
        fallback_targets_used = _fallback_targets_used(trade_plan.targets, trade_plan.metadata)
        fallback_used = (
            _truthy_metadata_value(trade_plan.metadata, "fallback_used")
            or _truthy_metadata_value(trade_plan.risk_rules.metadata, "fallback_used")
            or fallback_stop_used
            or fallback_targets_used
        )
        has_structural_stop = trade_plan.stop_loss is not None and not fallback_stop_used
        has_invalidation_thesis = _has_invalidation_thesis(trade_plan.invalidation)
        has_structural_target = any(_is_structural_target(target) for target in trade_plan.targets)

        missing: list[str] = []
        if not has_structural_stop:
            missing.append("structural_stop")
        if not has_invalidation_thesis:
            missing.append("invalidation_thesis")
        if not has_structural_target:
            missing.append("structural_target")

        warnings: list[str] = []
        if fallback_stop_used:
            warnings.append("Trade plan uses a fallback stop.")
        if fallback_targets_used:
            warnings.append("Trade plan uses fallback targets.")
        if missing:
            warnings.append(f"Trade plan is incomplete: {', '.join(missing)}.")

        target_sources = [
            str(target.source)
            for target in trade_plan.targets
            if target.source is not None
        ]
        return TradePlanCompletenessResult(
            complete=not missing and not fallback_used,
            fallback_used=fallback_used,
            fallback_stop_used=fallback_stop_used,
            fallback_targets_used=fallback_targets_used,
            has_structural_stop=has_structural_stop,
            has_invalidation_thesis=has_invalidation_thesis,
            has_structural_target=has_structural_target,
            missing=missing,
            warnings=warnings,
            metadata={
                "source": "trade_plan_completeness",
                "target_sources": target_sources,
                "invalidation_source": _metadata_string(
                    trade_plan.invalidation.metadata if trade_plan.invalidation else {},
                    "source",
                ),
            },
        )


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
    metadata_sources = (target.metadata,)
    if any(_truthy_metadata_value(metadata, "fallback_target_used") for metadata in metadata_sources):
        return True
    source_values = [
        target.source,
        target.thesis.source if target.thesis is not None else None,
        _metadata_string(target.metadata, "fallback_target_source"),
        _metadata_string(target.metadata, "target_source"),
    ]
    for value in source_values:
        if value is None:
            continue
        normalized = value.lower()
        if "fallback" in normalized or normalized in FALLBACK_TARGET_SOURCES:
            return True
    return False


def _is_structural_target(target: TradePlanTarget) -> bool:
    if target.price is None or _is_fallback_target(target):
        return False
    if target.thesis is not None:
        return target.thesis.source not in FALLBACK_TARGET_THESIS_SOURCES
    source = target.source
    if source is None:
        return False
    return source.lower() not in NON_STRUCTURAL_TARGET_SOURCES


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
