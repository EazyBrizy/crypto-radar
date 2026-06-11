from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeAlias

from app.core.config import settings
from app.domain.signal_status import is_execution_candidate_status, is_terminal_signal_status
from app.schemas.decision import SignalDecisionSnapshot
from app.schemas.signal import (
    NoTradeFilterResult,
    RadarSignal,
    SignalEdgeSnapshot,
    SignalExecutionGateReason,
    SignalExecutionGateSnapshot,
    StrategySignal,
)
from app.schemas.trade_plan import TradePlan
from app.services.signal_snapshot_normalization import normalize_signal_snapshots

SignalLike: TypeAlias = RadarSignal | StrategySignal

EXECUTION_SCORE_THRESHOLD = 70
WATCHLIST_STATUSES = {"watchlist", "ready", "wait_for_pullback", "active", "new"}


class SignalExecutionGateService:
    """Classifies a market idea into feed kind and execution permissions."""

    def evaluate(
        self,
        signal: SignalLike,
        *,
        strict_edge_mode: bool = False,
        execution_score_threshold: int | None = None,
    ) -> SignalExecutionGateSnapshot:
        signal = normalize_signal_snapshots(signal)
        hard_blockers: list[SignalExecutionGateReason] = []
        reasons: list[SignalExecutionGateReason] = []
        warnings: list[SignalExecutionGateReason] = []
        status = str(signal.status).strip().lower()
        score = int(signal.score or 0)
        score_threshold = int(execution_score_threshold or settings.execution_min_score)
        market_idea_score_threshold = int(settings.radar_min_market_idea_score)
        execution_candidate = is_execution_candidate_status(status)

        if status == "expired":
            hard_blockers.append(_reason("expired_signal", "blocker", "lifecycle", "Signal expired."))
        elif is_terminal_signal_status(status):
            hard_blockers.append(
                _reason("terminal_signal", "blocker", "lifecycle", f"Signal is terminal: {status}.")
            )

        if settings.execution_closed_candle_only and signal.candle_state == "open":
            hard_blockers.append(
                _reason(
                    "forming_candle",
                    "blocker",
                    "candle",
                    "Forming candle is not allowed in the execution feed.",
                    {"candle_state": signal.candle_state},
                )
            )

        trigger_reason = _trigger_failed_reason(signal, execution_candidate=execution_candidate)
        if trigger_reason is not None:
            if trigger_reason.severity == "blocker":
                hard_blockers.append(trigger_reason)
            else:
                reasons.append(trigger_reason)

        regime_reason = _regime_compatibility_reason(signal)
        if regime_reason is not None:
            if regime_reason.severity == "blocker":
                hard_blockers.append(regime_reason)
            else:
                warnings.append(regime_reason)

        no_trade = signal.no_trade_filter
        if _no_trade_blocked(no_trade):
            hard_blockers.append(
                _reason(
                    "no_trade_hard_block",
                    "blocker",
                    "no_trade",
                    _joined_reason(no_trade.blockers, "No-trade hard block is active.") if no_trade else "No-trade hard block is active.",
                    _model_metadata(no_trade),
                )
            )

        decision = signal.decision
        if execution_candidate:
            hard_blockers.extend(_decision_blockers(decision))

        rr_reason = _rr_failed_reason(signal)
        if rr_reason is not None:
            hard_blockers.append(rr_reason)

        edge_reasons = _edge_reasons(signal.edge, strict_edge_mode=strict_edge_mode)
        for edge_reason in edge_reasons:
            if edge_reason.severity == "blocker":
                hard_blockers.append(edge_reason)
            else:
                warnings.append(edge_reason)
        eligibility_reason = _strategy_eligibility_reason(signal.edge)
        if eligibility_reason is not None:
            if eligibility_reason.severity == "blocker":
                hard_blockers.append(eligibility_reason)
            else:
                warnings.append(eligibility_reason)
        if settings.execution_edge_gate_enabled and signal.edge is None:
            hard_blockers.append(
                _reason(
                    "edge_missing",
                    "blocker",
                    "edge",
                    "No edge profile is attached; execution requires expectancy calibration.",
                )
            )

        plan_reasons = _trade_plan_reasons(signal, execution_candidate=execution_candidate)
        hard_blockers.extend(reason for reason in plan_reasons if reason.severity == "blocker")
        reasons.extend(reason for reason in plan_reasons if reason.severity != "blocker")

        if score < score_threshold:
            reasons.append(
                _reason(
                    "score_below_execution_threshold",
                    "info",
                    "score",
                    f"Score {score} is below execution threshold {score_threshold}.",
                    {
                        "score": score,
                        "execution_score_threshold": score_threshold,
                        "market_idea_score_threshold": market_idea_score_threshold,
                    },
                )
            )

        if not execution_candidate:
            reasons.append(
                _reason(
                    "status_not_execution_candidate",
                    "info",
                    "status",
                    f"Status {status} is not an execution candidate.",
                    {"status": status},
                )
            )

        execution_ready = (
            execution_candidate
            and score >= score_threshold
            and (signal.candle_state == "closed" or not settings.execution_closed_candle_only)
            and not hard_blockers
            and _edge_allows_execution(signal.edge)
            and _has_valid_execution_plan(signal)
            and not _decision_blocks_virtual(decision)
        )

        feed_kind = (
            "execution_signal"
            if execution_ready
            else _non_execution_feed_kind(
                status,
                score,
                hard_blockers,
                execution_score_threshold=score_threshold,
                market_idea_score_threshold=market_idea_score_threshold,
            )
        )
        gate_status = "blocked" if hard_blockers else "warning" if warnings or reasons else "passed"
        can_show = feed_kind == "execution_signal" and gate_status in {"passed", "warning"}
        return SignalExecutionGateSnapshot(
            status=gate_status,
            feed_kind=feed_kind,
            can_notify=can_show,
            can_enter_now=can_show,
            can_arm_pending=can_show,
            can_show_in_execution_feed=can_show,
            reasons=[*hard_blockers, *reasons],
            warnings=warnings,
            metadata={
                "status": status,
                "score": score,
                "execution_score_threshold": score_threshold,
                "market_idea_score_threshold": market_idea_score_threshold,
                "execution_candidate_status": execution_candidate,
                "strict_edge_mode": strict_edge_mode,
            },
        )


def _non_execution_feed_kind(
    status: str,
    score: int,
    hard_blockers: list[SignalExecutionGateReason],
    *,
    execution_score_threshold: int,
    market_idea_score_threshold: int,
) -> str:
    if hard_blockers:
        return "blocked"
    if score < market_idea_score_threshold:
        return "blocked"
    if status in {"watchlist", "ready", "wait_for_pullback"}:
        return "watchlist"
    if status in WATCHLIST_STATUSES and score >= execution_score_threshold:
        return "watchlist"
    return "market_idea"


def _no_trade_blocked(no_trade: NoTradeFilterResult | None) -> bool:
    return bool(no_trade is not None and (no_trade.blocked or no_trade.hard_block))


def _decision_blockers(decision: SignalDecisionSnapshot | None) -> list[SignalExecutionGateReason]:
    if decision is None:
        return []
    blockers: list[SignalExecutionGateReason] = []
    if decision.signal_actionable is False:
        blockers.append(
            _reason(
                "decision_not_actionable",
                "blocker",
                "decision",
                "Decision snapshot marks the signal as not actionable.",
                decision.model_dump(mode="json"),
            )
        )
    if decision.execution_allowed_virtual is False:
        blockers.append(
            _reason(
                "virtual_execution_blocked",
                "blocker",
                "decision",
                "Decision snapshot blocks virtual execution.",
                decision.model_dump(mode="json"),
            )
        )
    for blocker in decision.blockers:
        if blocker.scope in {"virtual", "discovery"}:
            blockers.append(
                _reason(
                    "virtual_execution_blocked" if blocker.scope == "virtual" else "decision_not_actionable",
                    "blocker",
                    blocker.source,
                    blocker.message,
                    blocker.model_dump(mode="json"),
                )
            )
    return blockers


def _decision_blocks_virtual(decision: SignalDecisionSnapshot | None) -> bool:
    return bool(_decision_blockers(decision))


def _rr_failed_reason(signal: SignalLike) -> SignalExecutionGateReason | None:
    for metadata in _rr_metadata_sources(signal):
        rr_status = metadata.get("rr_status")
        hard_blocked = metadata.get("risk_reward_blocked") is True and metadata.get("risk_reward_guard_mode") == "hard"
        if rr_status == "failed" or hard_blocked:
            return _reason(
                "rr_failed",
                "blocker",
                "rr",
                _metadata_text(
                    metadata,
                    ("risk_reward_block_reason", "risk_reward_warning_reason", "reason"),
                    "Risk/reward gate failed.",
                ),
                dict(metadata),
            )
    return None


def _trigger_failed_reason(
    signal: SignalLike,
    *,
    execution_candidate: bool,
) -> SignalExecutionGateReason | None:
    trigger = getattr(signal, "trigger", None)
    if trigger is not None and getattr(trigger, "passed", False) is True:
        return None
    if trigger is None and not execution_candidate:
        return None
    message = "Execution requires a confirmed trigger."
    metadata: dict[str, Any] = {}
    if trigger is not None:
        message = getattr(trigger, "reason", None) or "Signal trigger is not confirmed."
        metadata = _model_metadata(trigger)
    return _reason(
        "trigger_not_confirmed",
        "blocker" if execution_candidate else "info",
        "trigger",
        message,
        metadata,
    )


def _regime_compatibility_reason(signal: SignalLike) -> SignalExecutionGateReason | None:
    regime = getattr(signal, "regime", None)
    checks = getattr(regime, "checks", None)
    if not checks:
        return None
    for check in checks:
        if getattr(check, "name", None) != "strategy_regime_compatibility":
            continue
        status = str(getattr(check, "status", "") or "").strip().lower()
        if status not in {"failed", "warning"}:
            return None
        metadata = dict(getattr(check, "metadata", {}) or {})
        code = str(
            metadata.get("reason_code")
            or ("strategy_regime_incompatible" if status == "failed" else "strategy_regime_watchlist")
        )
        return _reason(
            code,
            "blocker" if status == "failed" else "warning",
            "market_regime",
            getattr(check, "reason", None) or "Market regime is not compatible with this strategy.",
            metadata,
        )
    return None


def _rr_metadata_sources(signal: SignalLike) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = []
    if signal.confirmation is not None:
        sources.extend(check.metadata for check in signal.confirmation.checks if check.name == "risk_reward_guard")
    if signal.trade_plan is not None:
        sources.append(signal.trade_plan.metadata)
        sources.append(signal.trade_plan.risk_rules.metadata)
    return sources


def _edge_reasons(
    edge: SignalEdgeSnapshot | None,
    *,
    strict_edge_mode: bool,
) -> list[SignalExecutionGateReason]:
    if edge is None or not settings.execution_edge_gate_enabled:
        return []
    if edge.status in {"unknown", "insufficient_sample"} and settings.execution_edge_learning_mode:
        if edge.status == "insufficient_sample" and not settings.execution_edge_allow_insufficient_sample_in_learning_mode:
            return [
                _reason(
                    "edge_insufficient_sample",
                    "blocker",
                    "edge",
                    f"Edge sample size {edge.sample_size} is below required {edge.min_sample_size}.",
                    edge.model_dump(mode="json"),
                )
            ]
        return [
            _reason(
                f"edge_{edge.status}",
                "warning",
                "edge",
                "Edge profile is in learning mode and cannot notify or execute.",
                edge.model_dump(mode="json"),
            )
        ]
    if edge.status == "negative":
        return [
            _reason(
                "edge_negative",
                "blocker",
                "edge",
                "Historical expectancy after costs is negative.",
                edge.model_dump(mode="json"),
            )
        ]
    if edge.status == "insufficient_sample":
        return [
            _reason(
                "edge_insufficient_sample",
                "blocker",
                "edge",
                f"Edge sample size {edge.sample_size} is below required {edge.min_sample_size}.",
                edge.model_dump(mode="json"),
            )
        ]
    if edge.status == "unknown":
        return [
            _reason(
                "edge_unknown",
                "blocker",
                "edge",
                "No historical edge profile is available for this setup.",
                edge.model_dump(mode="json"),
            )
        ]
    reasons: list[SignalExecutionGateReason] = []
    expectancy = edge.expectancy_after_costs_r
    if expectancy is None or expectancy < settings.execution_edge_min_expectancy_after_costs_r:
        reasons.append(
            _reason(
                "edge_expectancy_below_threshold",
                "blocker",
                "edge",
                "Historical expectancy after costs is below the execution threshold.",
                {
                    **edge.model_dump(mode="json"),
                    "min_expectancy_after_costs_r": settings.execution_edge_min_expectancy_after_costs_r,
                },
            )
        )
    if edge.profit_factor is not None and edge.profit_factor < settings.execution_edge_min_profit_factor:
        reasons.append(
            _reason(
                "edge_profit_factor_below_threshold",
                "blocker",
                "edge",
                "Historical profit factor is below the execution threshold.",
                {
                    **edge.model_dump(mode="json"),
                    "min_profit_factor": settings.execution_edge_min_profit_factor,
                },
            )
        )
    entry_touch_rate = _float_metadata(edge.metadata, "entry_touch_rate")
    if entry_touch_rate is not None and entry_touch_rate < settings.execution_edge_min_entry_touch_rate:
        reasons.append(
            _reason(
                "edge_entry_touch_rate_below_threshold",
                "blocker",
                "edge",
                "Historical entry touch rate is below the execution threshold.",
                {
                    **edge.model_dump(mode="json"),
                    "min_entry_touch_rate": settings.execution_edge_min_entry_touch_rate,
                },
            )
        )
    no_entry_rate = _float_metadata(edge.metadata, "no_entry_rate")
    if no_entry_rate is not None and no_entry_rate > settings.execution_edge_max_no_entry_rate:
        reasons.append(
            _reason(
                "edge_no_entry_rate_above_threshold",
                "blocker",
                "edge",
                "Historical no-entry rate is above the execution threshold.",
                {
                    **edge.model_dump(mode="json"),
                    "max_no_entry_rate": settings.execution_edge_max_no_entry_rate,
                },
            )
        )
    return reasons


def _edge_allows_execution(edge: SignalEdgeSnapshot | None) -> bool:
    return not settings.execution_edge_gate_enabled or (edge is not None and edge.status == "positive")


def _strategy_eligibility_reason(edge: SignalEdgeSnapshot | None) -> SignalExecutionGateReason | None:
    strict = settings.execution_require_walk_forward_edge
    if edge is None:
        return (
            _reason(
                "strategy_eligibility_missing",
                "blocker",
                "strategy_eligibility",
                "No strategy eligibility profile is attached.",
            )
            if strict
            else None
        )
    eligibility = edge.metadata.get("strategy_eligibility")
    if not isinstance(eligibility, Mapping):
        if not strict:
            return None
        return _reason(
            "strategy_eligibility_missing",
            "blocker",
            "strategy_eligibility",
            "No strategy eligibility profile is attached.",
            edge.model_dump(mode="json"),
        )
    if eligibility.get("eligible") is True:
        return None
    code = str(eligibility.get("reason_code") or "strategy_eligibility_failed")
    if code not in {"strategy_eligibility_missing", "strategy_eligibility_failed"}:
        code = "strategy_eligibility_failed"
    return _reason(
        code,
        "blocker" if strict else "warning",
        "strategy_eligibility",
        str(eligibility.get("reason") or "Strategy eligibility failed."),
        dict(eligibility),
    )


def _float_metadata(metadata: Mapping[str, Any], key: str) -> float | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_plan_reasons(
    signal: SignalLike,
    *,
    execution_candidate: bool,
) -> list[SignalExecutionGateReason]:
    severity = "blocker" if execution_candidate else "info"
    reasons: list[SignalExecutionGateReason] = []
    if signal.trade_plan is None:
        reasons.append(_reason("trade_plan_incomplete", severity, "trade_plan", "Trade plan is missing."))
        return reasons
    if _trade_plan_execution_blocked(signal.trade_plan):
        reasons.append(
            _reason(
                "trade_plan_incomplete",
                "blocker",
                "trade_plan",
                "Trade plan completeness metadata blocks virtual execution.",
                _trade_plan_metadata(signal.trade_plan),
            )
        )
    if _entry_min(signal) is None or _entry_max(signal) is None:
        reasons.append(_reason("missing_entry_zone", severity, "trade_plan", "Entry zone is incomplete."))
    if _stop_loss(signal) is None:
        reasons.append(_reason("missing_stop_loss", severity, "trade_plan", "Stop loss is missing."))
    if not _targets(signal):
        reasons.append(_reason("missing_target", severity, "trade_plan", "Take-profit target is missing."))
    return reasons


def _trade_plan_execution_blocked(plan: TradePlan) -> bool:
    for metadata in (plan.metadata, plan.risk_rules.metadata):
        completeness = metadata.get("trade_plan_completeness")
        if isinstance(completeness, Mapping):
            if completeness.get("execution_allowed_virtual") is False:
                return True
            if completeness.get("complete") is False and completeness.get("blockers"):
                return True
        if metadata.get("execution_allowed_virtual") is False:
            return True
        if metadata.get("trade_plan_complete") is False and metadata.get("trade_plan_blocks_execution") is True:
            return True
    return False


def _has_valid_execution_plan(signal: SignalLike) -> bool:
    return (
        signal.trade_plan is not None
        and not _trade_plan_execution_blocked(signal.trade_plan)
        and _entry_min(signal) is not None
        and _entry_max(signal) is not None
        and _stop_loss(signal) is not None
        and bool(_targets(signal))
    )


def _entry_min(signal: SignalLike) -> float | None:
    if signal.entry_min is not None:
        return signal.entry_min
    if signal.trade_plan is not None:
        return signal.trade_plan.entry.min_price or signal.trade_plan.entry.price
    return None


def _entry_max(signal: SignalLike) -> float | None:
    if signal.entry_max is not None:
        return signal.entry_max
    if signal.trade_plan is not None:
        return signal.trade_plan.entry.max_price or signal.trade_plan.entry.price
    return None


def _stop_loss(signal: SignalLike) -> float | None:
    if signal.stop_loss is not None:
        return signal.stop_loss
    if signal.trade_plan is not None:
        return signal.trade_plan.stop_loss
    return None


def _targets(signal: SignalLike) -> list[float]:
    result = [value for value in (signal.take_profit_1, signal.take_profit_2) if value is not None]
    if signal.trade_plan is not None:
        result.extend(target.price for target in signal.trade_plan.targets if target.price is not None)
    return result


def _trade_plan_metadata(plan: TradePlan) -> dict[str, Any]:
    return {
        "metadata": dict(plan.metadata),
        "risk_rules_metadata": dict(plan.risk_rules.metadata),
    }


def _model_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _metadata_text(metadata: Mapping[str, Any], keys: tuple[str, ...], fallback: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _joined_reason(values: list[str], fallback: str) -> str:
    return "; ".join(value for value in values if value) or fallback


def _reason(
    code: str,
    severity: str,
    source: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> SignalExecutionGateReason:
    return SignalExecutionGateReason(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        source=source,
        message=message,
        metadata=metadata or {},
    )


signal_execution_gate_service = SignalExecutionGateService()
