from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from app.domain.signal_status import (
    is_execution_candidate_status,
    is_market_opportunity_status,
    is_terminal_signal_status,
    is_waiting_entry_status,
)
from app.schemas.pending_entry import PendingEntryIntentRead, PendingEntryView
from app.schemas.signal import (
    RadarSignal,
    RadarSummary,
    SignalBadgeView,
    SignalCardView,
    SignalDetailsBlockerView,
    SignalDetailsExecutionSummaryView,
    SignalDetailsRiskSummaryView,
    SignalDetailsView,
    SignalTargetView,
    SignalTradePlanView,
    ViewTone,
)
from app.schemas.signal_action import SignalActionBlocker, SignalActionState
from app.schemas.trade import PnLView, TradeJournalEntry, TradeView
from app.services.reason_codes import normalize_reason_code
from app.services.signal_snapshot_normalization import normalize_signal_snapshots


def annotate_signal_views(
    signal: RadarSignal,
    *,
    action_state: SignalActionState | None = None,
) -> RadarSignal:
    signal = normalize_signal_snapshots(signal)
    return signal.model_copy(
        update={
            "auto_entry": None,
            "card_view": build_signal_card_view(signal, action_state=action_state),
            "details_view": build_signal_details_view(signal, action_state=action_state),
        }
    )


def build_signal_card_view(
    signal: RadarSignal,
    *,
    action_state: SignalActionState | None = None,
) -> SignalCardView:
    signal = normalize_signal_snapshots(signal)
    trade_plan = build_trade_plan_view(signal)
    rr_state = _rr_state(signal)
    badges = [
        SignalBadgeView(code="opportunity", label=_opportunity_label(signal, action_state), tone=_opportunity_tone(signal, action_state)),
        SignalBadgeView(code="edge", label=_edge_label(signal), tone=_edge_tone(signal)),
    ]
    if signal.execution_gate is not None:
        badges.append(
            SignalBadgeView(
                code=f"feed_{signal.execution_gate.feed_kind}",
                label=_feed_kind_label(signal.execution_gate.feed_kind, signal),
                tone=_feed_kind_tone(signal.execution_gate.feed_kind),
            )
        )
    if signal.risk_gate_status is not None:
        badges.append(SignalBadgeView(code="risk_gate", label=f"RiskGate {signal.risk_gate_status}", tone=_risk_gate_tone(signal.risk_gate_status)))
    if action_state is not None and action_state.disabled_reason_code:
        badges.append(SignalBadgeView(code=action_state.disabled_reason_code, label=_disabled_label(action_state), tone="red"))
    if rr_state == "blocked":
        badges.append(SignalBadgeView(code="rr_blocked", label="RR blocked", tone="red"))
    elif rr_state == "warning":
        badges.append(SignalBadgeView(code="rr_warning", label="RR warning", tone="yellow"))
    if trade_plan.fallback_used:
        badges.append(SignalBadgeView(code="fallback_plan", label="Fallback plan", tone="yellow"))

    return SignalCardView(
        status_label=_status_label(signal, action_state),
        status_tone=_status_tone(signal, action_state),
        opportunity_label=_opportunity_label(signal, action_state),
        opportunity_tone=_opportunity_tone(signal, action_state),
        risk_label=_risk_label(signal),
        risk_meta=f"Risk: {_risk_label(signal)} | score {signal.score} | urgency {signal.urgency}",
        badges=_dedupe_badges(badges),
        entry_label=trade_plan.entry_type,
        entry_value=trade_plan.entry_zone,
        stop_loss=trade_plan.stop_loss,
        targets=trade_plan.targets[:3],
        selected_rr=trade_plan.selected_rr,
        reason=_first_text(_execution_blocked_reason(signal), signal.display_reason, signal.status_reason, *(signal.explanation or []), fallback="Waiting for backend decision context."),
    )


def build_signal_details_view(
    signal: RadarSignal,
    *,
    action_state: SignalActionState | None = None,
) -> SignalDetailsView:
    signal = normalize_signal_snapshots(signal)
    trade_plan = build_trade_plan_view(signal)
    blockers, warnings = _details_blockers(signal, action_state)
    primary_status = _primary_status(signal, action_state, blockers)
    can_enter_now = action_state.can_enter_now if action_state is not None else _gate_can_enter(signal)
    return SignalDetailsView(
        title=f"{signal.symbol} {signal.direction.upper()} Signal",
        side=signal.direction,
        primary_status=primary_status,
        primary_status_label=primary_status.replace("_", " "),
        primary_status_tone=_primary_status_tone(primary_status),
        primary_action_label=_primary_action_label(signal, action_state, primary_status),
        recommended_action_text=_first_text(
            _disabled_label(action_state) if action_state is not None and action_state.disabled_reason_code else None,
            blockers[0].user_message if blockers else None,
            warnings[0].user_message if warnings else None,
            signal.status_reason,
            fallback="Backend returned no action recommendation.",
        ),
        can_enter_now=can_enter_now,
        trade_plan=trade_plan,
        risk_summary=SignalDetailsRiskSummaryView(
            label=_risk_label(signal),
            risk_failed=bool(action_state and action_state.disabled_reason_code in {"risk_gate_blocked", "risk_profile_unavailable"}),
            risk_reward_blocked=_rr_state(signal) == "blocked",
            risk_reward_warning=_rr_reason(signal) if _rr_state(signal) == "warning" else None,
            forming_candle=signal.candle_state == "open",
            open_candle_allowed=bool(can_enter_now),
            forming_reason=_forming_reason(signal, action_state),
            status_allows_trade=bool(can_enter_now),
            trade_plan_complete=bool(trade_plan.trade_plan_complete),
            risk_reward_ok=trade_plan.selected_rr is not None,
            is_market_opportunity=is_market_opportunity_status(signal.status),
        ),
        execution_summary=SignalDetailsExecutionSummaryView(
            preview_available=_execution_preview_available(signal, trade_plan, action_state),
            risk_check_status=signal.risk_gate_status,
            risk_decision_status=signal.risk_gate_status,
            can_enter=can_enter_now,
            quality_gate_status=None,
            impact_risk=None,
            status_allows_trade=bool(can_enter_now),
        ),
        top_reasons=_dedupe_strings([
            _forming_reason(signal, action_state),
            *(signal.explanation or []),
            signal.display_reason,
        ]) or ["Backend did not return signal reasons."],
        top_blockers=blockers[:6],
        warnings=warnings[:6],
    )


def build_trade_plan_view(signal: RadarSignal) -> SignalTradePlanView:
    signal = normalize_signal_snapshots(signal)
    plan = signal.trade_plan
    targets = [
        SignalTargetView(
            label=target.label,
            price=target.price,
            r_multiple=target.r_multiple,
            action=target.action,
        )
        for target in (plan.targets if plan is not None else [])
    ]
    if not targets:
        targets = [
            SignalTargetView(label="TP1", price=signal.take_profit_1, r_multiple=signal.first_target_rr),
            SignalTargetView(label="TP2", price=signal.take_profit_2, r_multiple=signal.final_target_rr),
        ]
        targets = [target for target in targets if target.price is not None]

    metadata = plan.metadata if plan is not None else {}
    completeness = _record_metadata(metadata, "trade_plan_completeness")
    entry = plan.entry if plan is not None else None
    risk_rules = plan.risk_rules if plan is not None else None
    invalidation = plan.invalidation if plan is not None else signal.invalidation
    invalidation_value = None
    if invalidation is not None:
        invalidation_value = getattr(invalidation, "hard_stop", None) or getattr(invalidation, "price", None)

    return SignalTradePlanView(
        has_trade_plan=plan is not None,
        entry_type=_entry_type(signal),
        entry_zone=_entry_zone(signal),
        entry_price=(entry.price if entry is not None and entry.price is not None else _midpoint(signal.entry_min, signal.entry_max)),
        stop_loss=plan.stop_loss if plan is not None and plan.stop_loss is not None else signal.stop_loss,
        targets=targets,
        selected_rr=(
            risk_rules.selected_rr
            if risk_rules is not None and risk_rules.selected_rr is not None
            else signal.selected_rr or signal.risk_reward
        ),
        selected_rr_target=(
            risk_rules.selected_rr_target
            if risk_rules is not None and risk_rules.selected_rr_target is not None
            else signal.selected_rr_target
        ),
        min_rr=(
            risk_rules.min_rr_ratio
            if risk_rules is not None and risk_rules.min_rr_ratio is not None
            else signal.min_rr_ratio
        ),
        trade_plan_complete=_bool_metadata(metadata, "trade_plan_complete") or _bool_metadata(completeness, "complete"),
        fallback_used=bool(_bool_metadata(metadata, "fallback_used") or _bool_metadata(completeness, "fallback_used")),
        missing=_string_list_metadata(metadata, "missing_fields") or _string_list_metadata(completeness, "missing_fields") or [],
        invalidation=_format_price(invalidation_value),
    )


def build_radar_summary(signals: list[RadarSignal]) -> RadarSummary:
    signals = [normalize_signal_snapshots(signal) for signal in signals]
    return RadarSummary(
        total_signals=len(signals),
        execution_ready_signals=sum(1 for signal in signals if _signal_can_enter(signal)),
        watchlist_signals=sum(1 for signal in signals if _gate_feed_kind(signal) == "watchlist"),
        market_ideas=sum(1 for signal in signals if _gate_feed_kind(signal) == "market_idea"),
        high_confidence_signals=sum(1 for signal in signals if signal.score >= 80),
        positive_edge_signals=sum(1 for signal in signals if signal.edge is not None and signal.edge.status == "positive"),
        blocked_ideas=sum(1 for signal in signals if _signal_blocked(signal)),
    )


def annotate_pending_entry_view(intent: PendingEntryIntentRead) -> PendingEntryIntentRead:
    return intent.model_copy(update={"view": build_pending_entry_view(intent)})


def build_pending_entry_view(intent: PendingEntryIntentRead) -> PendingEntryView:
    reason_code = _pending_entry_reason_code(intent)
    technical_message = _first_text(
        intent.failure_reason,
        _snapshot_string(intent.request_snapshot, "technical_message"),
        _snapshot_string(intent.request_snapshot, "reason"),
        fallback=None,
    )
    return PendingEntryView(
        status_label=_pending_status_label(intent.status),
        status_tone=_pending_status_tone(intent.status),
        reason_code=reason_code,
        reason=reason_code or "no_backend_reason",
        technical_message=technical_message,
        entry_zone=f"{_format_decimal(intent.entry_min)} - {_format_decimal(intent.entry_max)}",
        current_price=_snapshot_decimal(intent.request_snapshot, "current_price"),
    )


def annotate_trade_view(trade: TradeJournalEntry) -> TradeJournalEntry:
    return trade.model_copy(update={"view": build_trade_view(trade)})


def annotate_virtual_trade_view(trade: Any) -> Any:
    return trade.model_copy(update={"view": build_trade_view(trade)})


def build_trade_view(trade: Any) -> TradeView:
    total_pnl = getattr(trade, "pnl", None)
    realized = float(getattr(trade, "realized_pnl", 0.0) or 0.0)
    unrealized = float(getattr(trade, "unrealized_pnl", 0.0) or 0.0)
    if total_pnl is None:
        total_pnl = realized + unrealized
    tone: ViewTone = "neutral"
    if total_pnl is not None and total_pnl > 0:
        tone = "green"
    elif total_pnl is not None and total_pnl < 0:
        tone = "red"
    return TradeView(
        status_label=str(getattr(trade, "status", "unknown")).replace("_", " "),
        status_tone=_trade_status_tone(str(getattr(trade, "status", "unknown"))),
        source_label=str(getattr(trade, "source", getattr(trade, "mode", "virtual"))).replace("_", " "),
        pnl=PnLView(
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            total_pnl=total_pnl,
            pnl_percent=getattr(trade, "pnl_percent", None),
            tone=tone,
        ),
    )


def _details_blockers(
    signal: RadarSignal,
    action_state: SignalActionState | None,
) -> tuple[list[SignalDetailsBlockerView], list[SignalDetailsBlockerView]]:
    blockers: list[SignalDetailsBlockerView] = []
    warnings: list[SignalDetailsBlockerView] = []
    if action_state is not None:
        blockers.extend(_action_blocker_view(item) for item in action_state.blockers)
        warnings.extend(_action_blocker_view(item) for item in action_state.warnings)
    for reason in signal.decision.blockers if signal.decision is not None else []:
        blockers.append(SignalDetailsBlockerView(
            code=reason.code,
            severity=reason.severity,
            category=_category_from_source(reason.source),
            user_message=reason.message,
            debug_messages=[f"decision.{reason.scope}.{reason.source}.{reason.code}"],
        ))
    for reason in signal.decision.warnings if signal.decision is not None else []:
        warnings.append(SignalDetailsBlockerView(
            code=reason.code,
            severity=reason.severity,
            category=_category_from_source(reason.source),
            user_message=reason.message,
            debug_messages=[f"decision.{reason.scope}.{reason.source}.{reason.code}"],
        ))
    if signal.execution_gate is not None:
        blockers.extend(
            SignalDetailsBlockerView(
                code=reason.code,
                severity=reason.severity,
                category=_category_from_source(reason.source),
                user_message=reason.message,
                debug_messages=[f"execution_gate.{reason.source}.{reason.code}"],
            )
            for reason in signal.execution_gate.reasons
            if reason.severity == "blocker"
        )
        warnings.extend(
            SignalDetailsBlockerView(
                code=reason.code,
                severity=reason.severity,
                category=_category_from_source(reason.source),
                user_message=reason.message,
                debug_messages=[f"execution_gate.{reason.source}.{reason.code}"],
            )
            for reason in [*signal.execution_gate.warnings, *signal.execution_gate.reasons]
            if reason.severity != "blocker"
        )
    return _dedupe_detail_blockers(blockers), _dedupe_detail_blockers(warnings)


def _action_blocker_view(blocker: SignalActionBlocker) -> SignalDetailsBlockerView:
    return SignalDetailsBlockerView(
        code=blocker.code,
        severity=blocker.severity,
        category=_category_from_code(blocker.code),
        user_message=_first_text(blocker.display_label, blocker.message, blocker.code, fallback="Action unavailable"),
        debug_messages=[blocker.code],
    )


def _primary_status(
    signal: RadarSignal,
    action_state: SignalActionState | None,
    blockers: list[SignalDetailsBlockerView],
) -> str:
    if signal.status == "expired":
        return "expired"
    if is_terminal_signal_status(signal.status):
        return "cancelled"
    if signal.execution_gate is not None:
        if signal.execution_gate.feed_kind == "blocked":
            return "blocked"
        if signal.execution_gate.feed_kind == "execution_signal" and signal.execution_gate.can_enter_now:
            return "execution_ready"
        if signal.execution_gate.feed_kind in {"watchlist", "market_idea"}:
            return "watchlist"
    if action_state is not None:
        if action_state.can_reconfirm:
            return "requires_reconfirmation"
        if action_state.can_cancel:
            return "waiting_entry"
        if action_state.can_enter_now:
            return "execution_ready"
        if blockers:
            return "blocked"
        if action_state.can_arm_pending:
            return "waiting_entry"
    if action_state is None and signal.can_enter is True and is_execution_candidate_status(signal.status):
        return "execution_ready"
    if signal.status == "watchlist":
        return "watchlist"
    if is_waiting_entry_status(signal.status):
        return "waiting_entry"
    if blockers:
        return "blocked"
    return "unknown"


def _primary_status_tone(status: str) -> ViewTone:
    if status == "execution_ready":
        return "green"
    if status in {"blocked", "cancelled", "expired"}:
        return "red"
    if status == "requires_reconfirmation":
        return "yellow"
    if status == "waiting_entry":
        return "blue"
    if status == "watchlist":
        return "purple"
    return "neutral"


def _primary_action_label(
    signal: RadarSignal,
    action_state: SignalActionState | None,
    primary_status: str,
) -> str:
    if action_state is not None:
        label = action_state.display_labels.get("primary_action")
        if label:
            return label
    if primary_status == "execution_ready":
        return f"Execution-ready inside {_entry_zone(signal)}"
    if primary_status == "blocked":
        return _disabled_label(action_state) if action_state is not None else "Entry is blocked"
    if primary_status == "waiting_entry":
        return "Market setup exists, wait for backend trigger"
    return primary_status.replace("_", " ")


def _status_label(signal: RadarSignal, action_state: SignalActionState | None) -> str:
    if signal.execution_gate is not None:
        if signal.execution_gate.feed_kind == "execution_signal" and signal.execution_gate.can_enter_now:
            return "Execution-ready"
        if signal.execution_gate.feed_kind == "blocked":
            return _blocked_status_label(signal)
        if signal.execution_gate.feed_kind == "market_idea":
            return "Market idea"
        if signal.execution_gate.feed_kind == "watchlist":
            return "Watchlist"
    if action_state is not None and action_state.can_enter_now:
        return "Execution-ready"
    if action_state is None and signal.can_enter is True and is_execution_candidate_status(signal.status):
        return "Execution-ready"
    if signal.status == "entry_touched":
        return "Entry touched"
    if is_waiting_entry_status(signal.status):
        return "Waiting entry"
    return signal.status.replace("_", " ")


def _status_tone(signal: RadarSignal, action_state: SignalActionState | None) -> ViewTone:
    if signal.execution_gate is not None:
        return _feed_kind_tone(signal.execution_gate.feed_kind)
    if action_state is not None and action_state.can_enter_now:
        return "green"
    if action_state is None and signal.can_enter is True and is_execution_candidate_status(signal.status):
        return "green"
    if action_state is not None and action_state.disabled_reason_code:
        return "red"
    if signal.status == "entry_touched":
        return "purple"
    if is_waiting_entry_status(signal.status):
        return "blue" if signal.status != "watchlist" else "yellow"
    if is_terminal_signal_status(signal.status):
        return "red"
    return "neutral"


def _opportunity_label(signal: RadarSignal, action_state: SignalActionState | None) -> str:
    if signal.execution_gate is not None:
        if signal.execution_gate.feed_kind == "execution_signal":
            return "Execution-ready"
        if signal.execution_gate.feed_kind == "blocked":
            return _blocked_status_label(signal)
        if signal.execution_gate.feed_kind == "watchlist":
            return "Watchlist"
        return "Market idea"
    if action_state is not None and action_state.can_enter_now:
        return "Execution-ready"
    if action_state is None and signal.can_enter is True and is_execution_candidate_status(signal.status):
        return "Execution-ready"
    if action_state is not None and action_state.disabled_reason_code:
        return "Risk blocked"
    if signal.status == "entry_touched":
        return "Entry touched"
    if is_waiting_entry_status(signal.status):
        return "Waiting entry"
    if is_market_opportunity_status(signal.status):
        return "Market opportunity"
    return signal.status.replace("_", " ")


def _opportunity_tone(signal: RadarSignal, action_state: SignalActionState | None) -> ViewTone:
    if signal.execution_gate is not None:
        return _feed_kind_tone(signal.execution_gate.feed_kind)
    if action_state is not None and action_state.can_enter_now:
        return "green"
    if action_state is None and signal.can_enter is True and is_execution_candidate_status(signal.status):
        return "green"
    if action_state is not None and action_state.disabled_reason_code:
        return "red"
    if signal.status == "entry_touched":
        return "purple"
    if is_waiting_entry_status(signal.status):
        return "blue"
    return "yellow" if is_market_opportunity_status(signal.status) else "neutral"


def _signal_can_enter(signal: RadarSignal) -> bool:
    if signal.execution_gate is not None:
        return signal.execution_gate.can_enter_now
    return bool(signal.details_view and signal.details_view.can_enter_now)


def _gate_can_enter(signal: RadarSignal) -> bool | None:
    if signal.execution_gate is not None:
        return signal.execution_gate.can_enter_now
    return signal.can_enter


def _signal_blocked(signal: RadarSignal) -> bool:
    if signal.execution_gate is not None:
        return signal.execution_gate.feed_kind == "blocked"
    if signal.details_view is not None:
        return signal.details_view.primary_status == "blocked"
    return signal.risk_gate_status == "failed" or signal.can_enter is False or _rr_state(signal) == "blocked"


def _execution_preview_available(
    signal: RadarSignal,
    trade_plan: SignalTradePlanView,
    action_state: SignalActionState | None,
) -> bool:
    if signal.execution_gate is not None and not (
        signal.execution_gate.can_enter_now or signal.execution_gate.can_arm_pending
    ):
        return False
    if is_terminal_signal_status(signal.status):
        return False
    if action_state is not None and action_state.can_cancel:
        return False
    if trade_plan.has_trade_plan:
        return True
    return signal.entry_min is not None and signal.entry_max is not None and signal.stop_loss is not None


def _risk_label(signal: RadarSignal) -> str:
    if signal.urgency == "low" and signal.score >= 70:
        return "Low"
    if signal.urgency == "high" and signal.score < 75:
        return "High"
    if signal.score < 65:
        return "Speculative"
    return "Medium"


def _rr_state(signal: RadarSignal) -> str:
    if signal.rr_status == "failed":
        return "blocked"
    if signal.rr_status == "warning":
        return "warning"
    for metadata in _rr_metadata_sources(signal):
        if metadata.get("risk_reward_guard_mode") == "hard" and metadata.get("risk_reward_blocked") is True:
            return "blocked"
        if metadata.get("risk_reward_warning") is True or metadata.get("risk_reward_blocked") is True:
            return "warning"
    return "passed"


def _rr_reason(signal: RadarSignal) -> str | None:
    for metadata in _rr_metadata_sources(signal):
        for key in ("risk_reward_block_reason", "risk_reward_warning_reason"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _rr_metadata_sources(signal: RadarSignal) -> list[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = []
    if signal.confirmation is not None:
        sources.extend(check.metadata for check in signal.confirmation.checks if check.name == "risk_reward_guard")
    if signal.trade_plan is not None:
        sources.append(signal.trade_plan.metadata)
        sources.append(signal.trade_plan.risk_rules.metadata)
    return sources


def _forming_reason(signal: RadarSignal, action_state: SignalActionState | None) -> str | None:
    if signal.candle_state != "open":
        return None
    blocker = next((item for item in (action_state.blockers if action_state else []) if item.code == "forming_candle"), None)
    if blocker is not None:
        return _first_text(blocker.display_label, blocker.message, fallback=None)
    check = next((item for item in (signal.confirmation.checks if signal.confirmation else []) if item.name == "candle_state_gate"), None)
    return check.reason if check is not None else signal.status_reason


def _entry_type(signal: RadarSignal) -> str:
    if signal.trade_plan is None:
        return "Legacy entry"
    metadata = signal.trade_plan.entry.metadata
    value = metadata.get("entry_type") or metadata.get("entry_model") or signal.trade_plan.entry.source
    return str(value).replace("_", " ") if value else "trade plan"


def _entry_zone(signal: RadarSignal) -> str:
    entry = signal.trade_plan.entry if signal.trade_plan is not None else None
    left = entry.min_price if entry is not None and entry.min_price is not None else signal.entry_min
    right = entry.max_price if entry is not None and entry.max_price is not None else signal.entry_max
    price = entry.price if entry is not None and entry.price is not None else _midpoint(signal.entry_min, signal.entry_max)
    if left is not None or right is not None:
        return f"{_format_price(left)}-{_format_price(right)}"
    return _format_price(price)


def _edge_label(signal: RadarSignal) -> str:
    edge = signal.edge
    if edge is None or edge.status == "unknown":
        return "Edge unknown"
    if edge.status == "positive":
        return f"Edge + {edge.sample_size} sample"
    if edge.status == "negative":
        return f"Edge - {edge.sample_size} sample"
    return f"Edge low {edge.sample_size}/{edge.min_sample_size}"


def _edge_tone(signal: RadarSignal) -> ViewTone:
    if signal.edge is None:
        return "neutral"
    if signal.edge.status == "positive":
        return "green"
    if signal.edge.status == "negative":
        return "red"
    if signal.edge.status == "insufficient_sample":
        return "yellow"
    return "neutral"


def _risk_gate_tone(status: str | None) -> ViewTone:
    if status == "passed":
        return "green"
    if status == "failed":
        return "red"
    if status == "warning":
        return "yellow"
    return "neutral"


def _feed_kind_tone(feed_kind: str) -> ViewTone:
    if feed_kind == "execution_signal":
        return "green"
    if feed_kind == "blocked":
        return "red"
    if feed_kind == "watchlist":
        return "blue"
    if feed_kind == "market_idea":
        return "yellow"
    return "neutral"


def _feed_kind_label(feed_kind: str, signal: RadarSignal) -> str:
    if feed_kind == "execution_signal":
        return "execution signal"
    if feed_kind == "blocked":
        return _blocked_status_label(signal)
    return feed_kind.replace("_", " ")


def _gate_feed_kind(signal: RadarSignal) -> str | None:
    return signal.execution_gate.feed_kind if signal.execution_gate is not None else None


def _blocked_status_label(signal: RadarSignal) -> str:
    gate = signal.execution_gate
    if gate is None:
        return "Execution blocked"
    if any(reason.severity == "blocker" for reason in gate.reasons):
        return "Execution blocked"
    return "Blocked diagnostic"


def _execution_blocked_reason(signal: RadarSignal) -> str | None:
    gate = signal.execution_gate
    if gate is None or gate.feed_kind != "blocked":
        return None
    reason = next((reason for reason in gate.reasons if reason.severity == "blocker"), None)
    if reason is None:
        reason = gate.reasons[0] if gate.reasons else None
    if reason is None:
        return _blocked_status_label(signal)
    return f"{_blocked_status_label(signal)}: {reason.message}"


def _disabled_label(action_state: SignalActionState | None) -> str | None:
    if action_state is None or not action_state.disabled_reason_code:
        return None
    blocker = next((item for item in action_state.blockers if item.code == action_state.disabled_reason_code), None)
    return _first_text(
        action_state.display_labels.get("disabled_reason"),
        blocker.display_label if blocker else None,
        blocker.message if blocker else None,
        action_state.disabled_reason_code,
        fallback=None,
    )


def _category_from_source(source: str) -> str:
    if source in {"rr", "risk"}:
        return "risk"
    if source == "execution":
        return "execution"
    if source in {"market_quality", "data"}:
        return "market_data"
    if source == "setup":
        return "entry"
    return "technical"


def _category_from_code(code: str) -> str:
    normalized = code.lower()
    if "liquidity" in normalized or "spread" in normalized:
        return "liquidity"
    if "risk" in normalized or "rr" in normalized:
        return "risk"
    if "execution" in normalized or "order" in normalized or "fill" in normalized:
        return "execution"
    if "market" in normalized or "price" in normalized or "candle" in normalized:
        return "market_data"
    if "entry" in normalized or "signal" in normalized:
        return "entry"
    return "technical"


def _pending_status_label(status: str) -> str:
    if status == "pending":
        return "Waiting entry"
    if status == "requires_reconfirmation":
        return "Requires reconfirmation"
    return status.replace("_", " ")


def _pending_status_tone(status: str) -> ViewTone:
    if status == "pending":
        return "blue"
    if status == "requires_reconfirmation":
        return "yellow"
    if status in {"triggered", "filling", "filled"}:
        return "green"
    if status in {"failed", "cancelled", "expired"}:
        return "red"
    return "neutral"


def _pending_entry_reason_code(intent: PendingEntryIntentRead) -> str | None:
    for key in ("reason_code", "code"):
        value = _snapshot_string(intent.request_snapshot, key)
        if value:
            return normalize_reason_code(value) or value
    return normalize_reason_code(intent.failure_reason)


def _trade_status_tone(status: str) -> ViewTone:
    if status in {"open", "partially_closed"}:
        return "green"
    if status in {"closed"}:
        return "blue"
    if status in {"stopped", "invalidated", "expired", "cancelled"}:
        return "red"
    return "neutral"


def _snapshot_string(snapshot: Mapping[str, Any], key: str) -> str | None:
    value = snapshot.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _snapshot_decimal(snapshot: Mapping[str, Any], key: str) -> Decimal | None:
    value = snapshot.get(key)
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _format_decimal(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _format_price(value: float | int | Decimal | None) -> str:
    if value is None:
        return "-"
    number = float(value)
    if abs(number) >= 1000:
        return f"{number:,.2f}"
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _midpoint(left: float | None, right: float | None) -> float | None:
    if left is not None and right is not None:
        return (left + right) / 2
    return left if left is not None else right


def _record_metadata(metadata: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = metadata.get(key)
    return value if isinstance(value, Mapping) else {}


def _bool_metadata(metadata: Mapping[str, Any], key: str) -> bool | None:
    value = metadata.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _string_list_metadata(metadata: Mapping[str, Any], key: str) -> list[str] | None:
    value = metadata.get(key)
    if not isinstance(value, list):
        return None
    result = [item for item in value if isinstance(item, str) and item]
    return result or None


def _first_text(*values: str | None, fallback: str | None = "") -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback or ""


def _dedupe_strings(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dedupe_badges(values: list[SignalBadgeView]) -> list[SignalBadgeView]:
    seen: set[str] = set()
    result: list[SignalBadgeView] = []
    for value in values:
        key = f"{value.code}:{value.label}"
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _dedupe_detail_blockers(values: list[SignalDetailsBlockerView]) -> list[SignalDetailsBlockerView]:
    seen: set[tuple[str, str]] = set()
    result: list[SignalDetailsBlockerView] = []
    for value in values:
        key = (value.code, value.user_message)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
