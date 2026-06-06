from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from app.domain.signal_status import is_execution_candidate_status
from app.schemas.signal import (
    MarketQualitySnapshot,
    MarketRegimeSnapshot,
    NoTradeFilterResult,
    SignalConfirmationSnapshot,
    SignalLayerCheck,
    SignalTriggerSnapshot,
    StrategySetupSnapshot,
    StrategySignal,
)
from app.schemas.trade_plan import TradePlan, TradePlanCompletenessResult
from app.services.risk_reward_assessment import RiskRewardAssessment
from app.services.trade_plan_enrichment import trade_plan_incomplete_status_reason


@dataclass(frozen=True)
class SignalStatusDecision:
    status: str
    status_reason: str
    confirmation: SignalConfirmationSnapshot
    setup: StrategySetupSnapshot
    trade_plan: TradePlan
    actionability_block_reason: str | None = None
    actionability_block_message: str | None = None
    risks: tuple[str, ...] = ()
    explanation: tuple[str, ...] = ()


class SignalStatusResolver:
    """Resolves final signal status from already calculated pipeline snapshots."""

    def resolve(
        self,
        *,
        signal: StrategySignal,
        params: Mapping[str, Any],
        quality: MarketQualitySnapshot,
        regime: MarketRegimeSnapshot,
        confirmation: SignalConfirmationSnapshot,
        setup: StrategySetupSnapshot,
        risk_reward: RiskRewardAssessment,
        no_trade_filter: NoTradeFilterResult,
        completeness: TradePlanCompletenessResult,
        trade_plan: TradePlan,
        candle_state: str,
        production_mode: bool,
        actionable_score: int,
        trigger: SignalTriggerSnapshot | None = None,
    ) -> SignalStatusDecision:
        status, status_reason = self._base_status(
            signal=signal,
            params=params,
            quality=quality,
            regime=regime,
            confirmation=confirmation,
            risk_reward=risk_reward,
            no_trade_filter=no_trade_filter,
            actionable_score=actionable_score,
        )
        if production_mode and not completeness.complete:
            status = "watchlist"
            status_reason = trade_plan_incomplete_status_reason(completeness)

        return self._apply_actionability_source_rules(
            signal=signal,
            params=params,
            status=status,
            status_reason=status_reason,
            confirmation=confirmation,
            setup=setup,
            trade_plan=trade_plan,
            candle_state=candle_state,
            trigger=trigger,
        )

    def _base_status(
        self,
        *,
        signal: StrategySignal,
        params: Mapping[str, Any],
        quality: MarketQualitySnapshot,
        regime: MarketRegimeSnapshot,
        confirmation: SignalConfirmationSnapshot,
        risk_reward: RiskRewardAssessment,
        no_trade_filter: NoTradeFilterResult,
        actionable_score: int,
    ) -> tuple[str, str]:
        if signal.status == "invalidated":
            return ("invalidated", signal.status_reason or "Strategy idea is invalidated")

        if signal.status == "rejected":
            return ("rejected", signal.status_reason or "Strategy rejected the setup")

        if no_trade_filter.blocked:
            return ("ready", f"No-trade hard block: {'; '.join(no_trade_filter.blockers)}")

        overextension_reason = _overextension_status_reason(confirmation)
        if overextension_reason is not None:
            return ("wait_for_pullback", overextension_reason)

        retest_reason = _retest_required_status_reason(confirmation)
        if retest_reason is not None:
            return ("wait_for_pullback", retest_reason)

        if signal.status == "wait_for_pullback":
            return ("wait_for_pullback", signal.status_reason or "Strategy requires pullback/retest before entry")

        if signal.status == "watchlist":
            return ("watchlist", signal.status_reason or "Strategy conditions are forming")

        if not risk_reward.passed:
            return ("ready", risk_reward.reason)

        if not confirmation.passed:
            return ("watchlist", "Strategy setup exists, but confirmation is incomplete")

        if _has_strong_regime_conflict(regime):
            return ("watchlist", "Higher timeframe is strongly against the signal direction")

        if (
            signal.strategy == "trend_pullback_continuation"
            and _bool_param(params, "require_htf_alignment", False)
            and regime.alignment != "aligned"
        ):
            return ("watchlist", "Trend pullback requires higher-timeframe alignment before actionable entry")

        if signal.strategy == "trend_pullback_continuation" and _has_borderline_ema200_chop(regime):
            return ("watchlist", "EMA200 chop is elevated; trend pullback stays on watchlist")

        if _has_context_obstacle(regime):
            return ("ready", "Higher timeframe support/resistance is too close")

        if signal.status == "ready":
            return ("ready", signal.status_reason or "Strategy setup exists; waiting for confirmation")

        if quality.tier == "low_liquidity" and signal.score < 85:
            return ("ready", "Low-liquidity asset needs a stronger strategy score before actionable classification")

        if signal.score >= actionable_score:
            return ("actionable", "Strategy classification passed; entry still requires risk/reward gate")

        return ("ready", "Setup is valid; waiting for stronger confirmation")

    def _apply_actionability_source_rules(
        self,
        *,
        signal: StrategySignal,
        params: Mapping[str, Any],
        status: str,
        status_reason: str,
        confirmation: SignalConfirmationSnapshot,
        setup: StrategySetupSnapshot,
        trade_plan: TradePlan,
        candle_state: str,
        trigger: SignalTriggerSnapshot | None,
    ) -> SignalStatusDecision:
        allow_open = _bool_param(params, "allow_open_candle_actionable", False)
        lower_timeframe_trigger = _has_lower_timeframe_trigger(signal, trade_plan)
        allow_lower_timeframe = _bool_param(
            params,
            "allow_lower_timeframe_trigger_actionable",
            False,
        )
        blocked_by_open = candle_state == "open" and not allow_open
        blocked_by_lower_timeframe = (
            lower_timeframe_trigger
            and not blocked_by_open
            and _is_actionable_status(status)
            and not allow_lower_timeframe
        )
        blocked_by_trigger = _is_actionable_status(status) and not _trigger_passed(trigger)
        final_status = status
        final_reason = status_reason
        actionability_block_reason: str | None = None
        actionability_block_message: str | None = None
        risks: list[str] = []
        explanation: list[str] = []
        final_setup = setup

        if blocked_by_open:
            final_status = "watchlist"
            final_reason = "forming_candle: forming candle preview is not actionable until the candle closes"
            actionability_block_reason = "forming_candle"
            actionability_block_message = final_reason
            risks.append("forming_candle: forming candle preview is not actionable until the candle closes")
            explanation.append("forming candle preview: open candle is watchlist-only until it closes.")
            final_setup = _setup_with_actionability_source_check(
                setup,
                stage="forming",
                check=SignalLayerCheck(
                    name="candle_state_gate",
                    status="warning",
                    reason=final_reason,
                    metadata={
                        "reason_code": "forming_candle",
                        "candle_state": candle_state,
                        "allow_open_candle_actionable": allow_open,
                    },
                ),
            )
        elif candle_state == "open" and allow_open and _is_actionable_status(status):
            explanation.append("forming candle preview is explicitly allowed to remain actionable by configuration.")

        if blocked_by_trigger and not blocked_by_open:
            final_status = "ready"
            final_reason = _trigger_not_confirmed_reason(trigger)
            actionability_block_reason = "trigger_not_confirmed"
            actionability_block_message = final_reason
            risks.append(final_reason)

        if blocked_by_lower_timeframe and not blocked_by_trigger:
            final_status = "ready"
            final_reason = (
                "lower_timeframe_trigger: actionable classification requires "
                "allow_lower_timeframe_trigger_actionable=true"
            )
            actionability_block_reason = "lower_timeframe_trigger"
            actionability_block_message = final_reason
            risks.append(final_reason)

        confirmation = _confirmation_with_actionability_source_checks(
            confirmation=confirmation,
            candle_state=candle_state,
            allow_open=allow_open,
            blocked_by_open=blocked_by_open,
            lower_timeframe_trigger=lower_timeframe_trigger,
            allow_lower_timeframe=allow_lower_timeframe,
            blocked_by_lower_timeframe=blocked_by_lower_timeframe,
            trigger=trigger,
            blocked_by_trigger=blocked_by_trigger,
            final_status=final_status,
        )
        trade_plan = _trade_plan_with_actionability_source_metadata(
            trade_plan=trade_plan,
            candle_state=candle_state,
            allow_open=allow_open,
            blocked_by_open=blocked_by_open,
            lower_timeframe_trigger=lower_timeframe_trigger,
            allow_lower_timeframe=allow_lower_timeframe,
            blocked_by_lower_timeframe=blocked_by_lower_timeframe,
            trigger=trigger,
            blocked_by_trigger=blocked_by_trigger,
            final_status=final_status,
        )
        return SignalStatusDecision(
            status=final_status,
            status_reason=final_reason,
            confirmation=confirmation,
            setup=final_setup,
            trade_plan=trade_plan,
            actionability_block_reason=actionability_block_reason,
            actionability_block_message=actionability_block_message,
            risks=tuple(risks),
            explanation=tuple(explanation),
        )


def _overextension_status_reason(confirmation: SignalConfirmationSnapshot) -> str | None:
    for check in confirmation.checks:
        if check.name == "overextension_guard" and check.status in {"warning", "failed"}:
            return check.reason or "Entry candle is overextended; wait for pullback"
    return None


def _retest_required_status_reason(confirmation: SignalConfirmationSnapshot) -> str | None:
    for check in confirmation.checks:
        if check.name == "retest_required_after_large_breakout" and check.status in {"warning", "failed"}:
            return check.reason or "Retest required before immediate breakout entry"
    return None


def _setup_with_actionability_source_check(
    setup: StrategySetupSnapshot,
    *,
    stage: Literal["forming", "ready", "confirmed"],
    check: SignalLayerCheck,
) -> StrategySetupSnapshot:
    return setup.model_copy(
        update={
            "stage": stage,
            "checks": [*setup.checks, check],
        }
    )


def _confirmation_with_actionability_source_checks(
    *,
    confirmation: SignalConfirmationSnapshot,
    candle_state: str,
    allow_open: bool,
    blocked_by_open: bool,
    lower_timeframe_trigger: bool,
    allow_lower_timeframe: bool,
    blocked_by_lower_timeframe: bool,
    trigger: SignalTriggerSnapshot | None,
    blocked_by_trigger: bool,
    final_status: str,
) -> SignalConfirmationSnapshot:
    checks = [
        *confirmation.checks,
        SignalLayerCheck(
            name="candle_state_gate",
            status="warning" if blocked_by_open else "passed",
            reason=(
                "forming_candle: forming candle preview is not actionable until the candle closes"
                if blocked_by_open
                else "Open candle actionability is explicitly allowed by configuration"
                if candle_state == "open" and allow_open and _is_actionable_status(final_status)
                else f"Signal evaluated on a {candle_state} candle"
            ),
            metadata={
                "reason_code": "forming_candle" if blocked_by_open else None,
                "candle_state": candle_state,
                "allow_open_candle_actionable": allow_open,
                "open_candle_preview": candle_state == "open",
                "actionable_from_open_candle": candle_state == "open" and allow_open and _is_actionable_status(final_status),
                "signal_actionable": _is_actionable_status(final_status),
            },
        ),
    ]
    if lower_timeframe_trigger:
        checks.append(
            SignalLayerCheck(
                name="lower_timeframe_trigger_gate",
                status="warning" if blocked_by_lower_timeframe else "passed",
                reason=(
                    "lower_timeframe_trigger: actionable classification requires "
                    "allow_lower_timeframe_trigger_actionable=true"
                    if blocked_by_lower_timeframe
                    else "Lower-timeframe trigger actionability is explicitly allowed by configuration"
                ),
                metadata={
                    "reason_code": "lower_timeframe_trigger" if blocked_by_lower_timeframe else None,
                    "lower_timeframe_trigger": True,
                    "allow_lower_timeframe_trigger_actionable": allow_lower_timeframe,
                    "actionable_from_lower_timeframe_trigger": (
                        allow_lower_timeframe and _is_actionable_status(final_status)
                    ),
                    "signal_actionable": _is_actionable_status(final_status),
                },
            )
        )
    if trigger is not None or blocked_by_trigger:
        checks.append(
            SignalLayerCheck(
                name="trigger_confirmation_gate",
                status="warning" if blocked_by_trigger else "passed",
                reason=_trigger_not_confirmed_reason(trigger) if blocked_by_trigger else "Signal trigger is confirmed",
                metadata={
                    "reason_code": "trigger_not_confirmed" if blocked_by_trigger else None,
                    "trigger_passed": _trigger_passed(trigger),
                    "trigger_type": trigger.trigger_type if trigger is not None else "none",
                    "signal_actionable": _is_actionable_status(final_status),
                },
            )
        )
    return confirmation.model_copy(
        update={
            "passed": (
                confirmation.passed
                and not blocked_by_open
                and not blocked_by_lower_timeframe
                and not blocked_by_trigger
            ),
            "checks": checks,
        }
    )


def _trade_plan_with_actionability_source_metadata(
    *,
    trade_plan: TradePlan,
    candle_state: str,
    allow_open: bool,
    blocked_by_open: bool,
    lower_timeframe_trigger: bool,
    allow_lower_timeframe: bool,
    blocked_by_lower_timeframe: bool,
    trigger: SignalTriggerSnapshot | None,
    blocked_by_trigger: bool,
    final_status: str,
) -> TradePlan:
    signal_actionable = _is_actionable_status(final_status)
    source_metadata: dict[str, Any] = {
        "candle_state": candle_state,
        "open_candle_preview": candle_state == "open",
        "allow_open_candle_actionable": allow_open,
        "actionable_from_open_candle": candle_state == "open" and allow_open and signal_actionable,
        "lower_timeframe_trigger": lower_timeframe_trigger,
        "allow_lower_timeframe_trigger_actionable": allow_lower_timeframe,
        "actionable_from_lower_timeframe_trigger": lower_timeframe_trigger and allow_lower_timeframe and signal_actionable,
        "trigger_passed": _trigger_passed(trigger),
        "trigger_type": trigger.trigger_type if trigger is not None else "none",
    }
    if blocked_by_open:
        source_metadata.update(
            {
                "signal_actionable": False,
                "execution_allowed_virtual": False,
                "execution_allowed_real": False,
                "auto_entry_enabled": False,
                "actionability_block_reason": "forming_candle",
            }
        )
    elif blocked_by_lower_timeframe:
        source_metadata.update(
            {
                "signal_actionable": False,
                "execution_allowed_virtual": False,
                "execution_allowed_real": False,
                "auto_entry_enabled": False,
                "actionability_block_reason": "lower_timeframe_trigger",
            }
        )
    elif blocked_by_trigger:
        source_metadata.update(
            {
                "signal_actionable": False,
                "execution_allowed_virtual": False,
                "execution_allowed_real": False,
                "auto_entry_enabled": False,
                "actionability_block_reason": "trigger_not_confirmed",
            }
        )
    elif candle_state == "open" and allow_open and signal_actionable:
        source_metadata["actionability_source"] = "open_candle_explicitly_allowed"
    elif lower_timeframe_trigger and allow_lower_timeframe and signal_actionable:
        source_metadata["actionability_source"] = "lower_timeframe_trigger_explicitly_allowed"

    metadata = dict(trade_plan.metadata)
    metadata.update(source_metadata)
    risk_metadata = dict(trade_plan.risk_rules.metadata)
    risk_metadata.update(source_metadata)
    risk_rules = trade_plan.risk_rules.model_copy(update={"metadata": risk_metadata})
    return trade_plan.model_copy(
        update={
            "metadata": metadata,
            "risk_rules": risk_rules,
        },
        deep=True,
    )


def _has_lower_timeframe_trigger(signal: StrategySignal, trade_plan: TradePlan) -> bool:
    metadata_sources = [
        trade_plan.metadata,
        trade_plan.entry.metadata,
        trade_plan.risk_rules.metadata,
    ]
    if trade_plan.invalidation is not None:
        metadata_sources.append(trade_plan.invalidation.metadata)
    if signal.invalidation is not None:
        metadata_sources.append(signal.invalidation.metadata)
    for metadata in metadata_sources:
        if _bool_param(metadata, "lower_timeframe_trigger", False):
            return True
        trigger_source = str(metadata.get("trigger_source") or "").strip().lower()
        if trigger_source in {"lower_timeframe", "lower_timeframe_trigger", "ltf"}:
            return True
        trigger_timeframe = metadata.get("trigger_timeframe") or metadata.get("lower_timeframe")
        if isinstance(trigger_timeframe, str) and _is_lower_timeframe(trigger_timeframe, signal.timeframe):
            return True
    return False


def _is_lower_timeframe(candidate: str, reference: str) -> bool:
    order = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    candidate_value = order.get(candidate.strip().lower())
    reference_value = order.get(reference.strip().lower())
    return candidate_value is not None and reference_value is not None and candidate_value < reference_value


def _is_actionable_status(status: str) -> bool:
    return is_execution_candidate_status(status)


def _trigger_passed(trigger: SignalTriggerSnapshot | None) -> bool:
    return trigger is not None and trigger.passed is True


def _trigger_not_confirmed_reason(trigger: SignalTriggerSnapshot | None) -> str:
    if trigger is None:
        return "trigger_not_confirmed: execution requires a confirmed trigger"
    return f"trigger_not_confirmed: {trigger.reason or 'signal trigger is not confirmed'}"


def _has_strong_regime_conflict(regime: MarketRegimeSnapshot) -> bool:
    if regime.alignment == "against" and regime.strength == "strong":
        return True
    return any(
        check.name == "macro_regime_alignment"
        and check.status == "warning"
        and check.reason is not None
        and "strong" in check.reason
        for check in regime.checks
    )


def _has_context_obstacle(regime: MarketRegimeSnapshot) -> bool:
    return any(
        check.name in {"context_resistance", "context_support"}
        and check.status == "warning"
        for check in regime.checks
    )


def _has_borderline_ema200_chop(regime: MarketRegimeSnapshot) -> bool:
    return any(check.name == "ema200_chop" and check.status == "warning" for check in regime.checks)


def _bool_param(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


signal_status_resolver = SignalStatusResolver()
