from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, cast

from app.domain.signal_status import is_execution_candidate_status, is_terminal_signal_status
from app.schemas.decision import (
    DecisionReason,
    DecisionReasonScope,
    DecisionReasonSeverity,
    DecisionReasonSource,
    SignalDecisionSnapshot,
)
from app.schemas.risk import RiskDecision
from app.schemas.signal import (
    MarketQualitySnapshot,
    MarketRegimeSnapshot,
    NoTradeFilterResult,
    SignalConfirmationSnapshot,
    SignalLayerCheck,
    StrategySignal,
)
from app.schemas.trade_plan import TradePlan, TradePlanCompletenessResult
from app.services.risk_reward_assessment import RiskRewardAssessment, risk_reward_metadata


class SignalDecisionService:
    """Builds the shared signal decision contract from completed service outputs."""

    def from_pipeline_outputs(
        self,
        *,
        signal: StrategySignal,
        quality: MarketQualitySnapshot,
        confirmation: SignalConfirmationSnapshot,
        risk_reward: RiskRewardAssessment,
        no_trade_filter: NoTradeFilterResult,
        completeness: TradePlanCompletenessResult,
        trade_plan: TradePlan,
        candle_state: str,
        production_mode: bool,
        status: str,
        rr_guard_context: str = "discovery",
        regime: MarketRegimeSnapshot | None = None,
    ) -> SignalDecisionSnapshot:
        snapshot = SignalDecisionSnapshot(
            setup_valid=not is_terminal_signal_status(status),
            trade_plan_valid=completeness.complete,
            market_context_score=float(quality.score),
            signal_actionable=is_execution_candidate_status(status),
            execution_allowed_virtual=_metadata_bool(
                trade_plan.metadata,
                "execution_allowed_virtual",
                fallback=completeness.execution_allowed_virtual,
            ),
            execution_allowed_real=False if not completeness.execution_allowed_real else None,
        )
        snapshot = self.merge_market_quality(snapshot, quality)
        snapshot = self.merge_market_regime(snapshot, regime)
        snapshot = self.merge_rr(snapshot, risk_reward, scope=_scope_from_context(rr_guard_context))
        snapshot = self.merge_no_trade(snapshot, no_trade_filter)
        snapshot = self.merge_trade_plan_completeness(
            snapshot,
            completeness,
            production_mode=production_mode,
        )
        snapshot = self.merge_candle_state(
            snapshot,
            candle_state=candle_state,
            confirmation=confirmation,
        )
        snapshot = self.merge_setup_confirmation(snapshot, confirmation)
        return self._finalize_snapshot(snapshot)

    def merge_market_quality(
        self,
        snapshot: SignalDecisionSnapshot,
        quality: MarketQualitySnapshot,
    ) -> SignalDecisionSnapshot:
        blockers: list[DecisionReason] = []
        warnings: list[DecisionReason] = []
        for check in quality.checks:
            if check.status == "failed":
                blockers.append(
                    _reason_from_check(
                        check,
                        source="market_quality",
                        severity="blocker",
                        scope="discovery",
                    )
                )
            elif check.status == "warning":
                warnings.append(
                    _reason_from_check(
                        check,
                        source="market_quality",
                        severity="warning",
                        scope="discovery",
                    )
                )
        if not quality.passed and not blockers:
            blockers.append(
                DecisionReason(
                    code="market_quality_failed",
                    message="Market quality checks did not pass.",
                    source="market_quality",
                    severity="blocker",
                    scope="discovery",
                    metadata=quality.model_dump(mode="json"),
                )
            )
        warning_messages = {reason.message for reason in warnings}
        for warning in quality.warnings:
            if warning in warning_messages:
                continue
            warnings.append(
                DecisionReason(
                    code=_code_from_message(warning, fallback="market_quality_warning"),
                    message=warning,
                    source="market_quality",
                    severity="warning",
                    scope="discovery",
                    metadata={"tier": quality.tier},
                )
            )
        return self._finalize_snapshot(_snapshot_with_reasons(snapshot, blockers=blockers, warnings=warnings))

    def merge_no_trade(
        self,
        snapshot: SignalDecisionSnapshot,
        no_trade: NoTradeFilterResult,
    ) -> SignalDecisionSnapshot:
        blockers = _reasons_from_layer_result(
            messages=no_trade.blockers,
            checks=no_trade.checks,
            status="failed",
            source="no_trade",
            severity="blocker",
            scope="virtual",
            metadata=no_trade.metadata,
            fallback_code="no_trade_blocker",
        )
        warnings = _reasons_from_layer_result(
            messages=no_trade.warnings,
            checks=no_trade.checks,
            status="warning",
            source="no_trade",
            severity="warning",
            scope="virtual",
            metadata=no_trade.metadata,
            fallback_code="no_trade_warning",
        )
        return self._finalize_snapshot(_snapshot_with_reasons(snapshot, blockers=blockers, warnings=warnings))

    def merge_rr(
        self,
        snapshot: SignalDecisionSnapshot,
        risk_reward: RiskRewardAssessment,
        *,
        scope: DecisionReasonScope = "discovery",
    ) -> SignalDecisionSnapshot:
        metadata = risk_reward_metadata(risk_reward)
        if risk_reward.blocked:
            return self._finalize_snapshot(
                _snapshot_with_reasons(
                    snapshot,
                    blockers=[
                        DecisionReason(
                            code="blocked_by_rr",
                            message=risk_reward.block_reason or risk_reward.reason,
                            source="rr",
                            severity="blocker",
                            scope=scope,
                            metadata=metadata,
                        )
                    ],
                )
            )
        if risk_reward.warning:
            return self._finalize_snapshot(
                _snapshot_with_reasons(
                    snapshot,
                    warnings=[
                        DecisionReason(
                            code="risk_reward_guard",
                            message=risk_reward.warning_reason or risk_reward.reason,
                            source="rr",
                            severity="warning",
                            scope=scope,
                            metadata=metadata,
                        )
                    ],
                )
            )
        return snapshot

    def merge_trade_plan_completeness(
        self,
        snapshot: SignalDecisionSnapshot,
        completeness: TradePlanCompletenessResult,
        *,
        production_mode: bool,
    ) -> SignalDecisionSnapshot:
        if completeness.complete and not completeness.warnings and not completeness.blockers:
            return snapshot
        message = (
            f"Trade plan incomplete: {', '.join(completeness.missing_fields or completeness.missing)}."
            if completeness.missing_fields or completeness.missing
            else "Trade plan is incomplete."
        )
        metadata = completeness.model_dump(mode="json")
        blocker_messages = list(completeness.blockers)
        warning_messages = list(completeness.warnings)
        if not blocker_messages and not completeness.complete and production_mode:
            blocker_messages = [message]
        elif not warning_messages and not completeness.complete:
            warning_messages = [message]

        blocker_scope: DecisionReasonScope = "discovery" if production_mode else "virtual"
        blockers = [
            DecisionReason(
                code="trade_plan_completeness",
                message=blocker,
                source="setup",
                severity="blocker",
                scope=blocker_scope,
                metadata=metadata,
            )
            for blocker in blocker_messages
        ]
        warnings = [
            DecisionReason(
                code="trade_plan_completeness",
                message=warning,
                source="setup",
                severity="warning",
                scope="discovery",
                metadata=metadata,
            )
            for warning in warning_messages
        ]
        if blockers:
            return self._finalize_snapshot(
                _snapshot_with_reasons(
                    snapshot,
                    blockers=blockers,
                    warnings=warnings,
                )
            )
        return self._finalize_snapshot(
            _snapshot_with_reasons(
                snapshot,
                warnings=warnings,
            )
        )

    def merge_candle_state(
        self,
        snapshot: SignalDecisionSnapshot,
        *,
        candle_state: str,
        confirmation: SignalConfirmationSnapshot | None = None,
    ) -> SignalDecisionSnapshot:
        if candle_state != "open":
            return snapshot
        candle_check = _find_check(confirmation.checks if confirmation is not None else [], "candle_state_gate")
        metadata = dict(candle_check.metadata) if candle_check is not None else {"candle_state": candle_state}
        blocked = metadata.get("signal_actionable") is False or metadata.get("reason_code") == "forming_candle"
        reason = (
            candle_check.reason
            if candle_check is not None and candle_check.reason
            else "forming_candle: forming candle preview is not actionable until the candle closes"
        )
        severity = "blocker" if blocked else "warning"
        decision_reason = DecisionReason(
            code="forming_candle" if blocked else "open_candle_preview",
            message=reason,
            source="data",
            severity=severity,
            scope="discovery",
            metadata=metadata,
        )
        if blocked:
            return self._finalize_snapshot(_snapshot_with_reasons(snapshot, blockers=[decision_reason]))
        return self._finalize_snapshot(_snapshot_with_reasons(snapshot, warnings=[decision_reason]))

    def merge_setup_confirmation(
        self,
        snapshot: SignalDecisionSnapshot,
        confirmation: SignalConfirmationSnapshot,
    ) -> SignalDecisionSnapshot:
        setup_check_names = {
            "breakout_acceptance_classifier",
            "retest_required_after_large_breakout",
            "trend_structural_zone",
            "trend_continuation_confirmation",
            "trend_exhaustion",
            "trend_crowded_trade",
            "trend_htf_target_room",
        }
        blockers: list[DecisionReason] = []
        warnings: list[DecisionReason] = []
        for check in confirmation.checks:
            if check.name not in setup_check_names or check.status not in {"warning", "failed"}:
                continue
            metadata = dict(check.metadata)
            scope = _scope_from_context(str(metadata.get("scope") or "discovery"))
            source = _source_from_metadata(metadata.get("source"))
            reason = DecisionReason(
                code=str(metadata.get("reason_code") or check.name),
                message=check.reason or check.name.replace("_", " "),
                source=source,
                severity="blocker" if check.status == "failed" else "warning",
                scope=scope,
                metadata=metadata,
            )
            if check.status == "failed":
                blockers.append(reason)
            else:
                warnings.append(reason)
        return self._finalize_snapshot(_snapshot_with_reasons(snapshot, blockers=blockers, warnings=warnings))

    def merge_market_regime(
        self,
        snapshot: SignalDecisionSnapshot,
        regime: MarketRegimeSnapshot | None,
    ) -> SignalDecisionSnapshot:
        if regime is None:
            return snapshot
        blockers: list[DecisionReason] = []
        warnings: list[DecisionReason] = []
        seen_codes: set[str] = set()
        for check in regime.checks:
            code = _market_regime_reason_code(check)
            if code is None or check.status not in {"failed", "warning"}:
                continue
            reason = DecisionReason(
                code=code,
                message=check.reason or code.replace("_", " "),
                source="data",
                severity="blocker" if check.status == "failed" else "warning",
                scope=_market_regime_scope(code, failed=check.status == "failed"),
                metadata={
                    **dict(check.metadata),
                    "primary_label": regime.primary_label,
                    "labels": list(regime.labels),
                    "regime_key": regime.regime_key,
                    "confidence": regime.confidence,
                },
            )
            seen_codes.add(code)
            if check.status == "failed":
                blockers.append(reason)
            else:
                warnings.append(reason)

        label_codes = {
            "liquidity_vacuum": "liquidity_vacuum",
            "news_pump": "news_pump_mode",
            "market_wide_risk_off": "market_wide_risk_off",
            "post_impulse": "post_impulse",
            "chop": "chop_regime",
        }
        for label, code in label_codes.items():
            if label not in regime.labels or code in seen_codes:
                continue
            severity: DecisionReasonSeverity = "warning"
            scope: DecisionReasonScope = "discovery"
            if label in {"liquidity_vacuum", "news_pump"}:
                severity = "blocker"
            reason = DecisionReason(
                code=code,
                message=f"{label.replace('_', ' ')} regime is active",
                source="data",
                severity=severity,
                scope=scope,
                metadata={
                    "primary_label": regime.primary_label,
                    "labels": list(regime.labels),
                    "regime_key": regime.regime_key,
                    "confidence": regime.confidence,
                },
            )
            if severity == "blocker":
                blockers.append(reason)
            else:
                warnings.append(reason)
        return self._finalize_snapshot(_snapshot_with_reasons(snapshot, blockers=blockers, warnings=warnings))

    def merge_risk_decision(
        self,
        snapshot: SignalDecisionSnapshot,
        decision: RiskDecision,
    ) -> SignalDecisionSnapshot:
        scope: DecisionReasonScope = "real" if decision.mode == "real" else "virtual"
        rr_block_reason = decision.risk_check.risk_reward_block_reason
        rr_warning_reason = decision.risk_check.risk_reward_warning_reason
        blockers: list[DecisionReason] = []
        warnings: list[DecisionReason] = []
        for blocker in decision.blockers:
            source: DecisionReasonSource = "rr" if rr_block_reason and blocker in rr_block_reason else "risk"
            blockers.append(
                DecisionReason(
                    code="risk_reward_guard" if source == "rr" else _code_from_message(blocker, fallback="risk_blocker"),
                    message=blocker,
                    source=source,
                    severity="blocker",
                    scope=scope,
                    metadata=decision.risk_check.model_dump(mode="json"),
                )
            )
        for warning in decision.warnings:
            source: DecisionReasonSource = "rr" if rr_warning_reason and warning in rr_warning_reason else "risk"
            warnings.append(
                DecisionReason(
                    code="risk_reward_guard" if source == "rr" else _code_from_message(warning, fallback="risk_warning"),
                    message=warning,
                    source=source,
                    severity="warning",
                    scope=scope,
                    metadata=decision.risk_check.model_dump(mode="json"),
                )
            )
        updates: dict[str, Any] = {}
        if decision.mode == "virtual":
            updates["execution_allowed_virtual"] = decision.can_enter
        else:
            updates["execution_allowed_real"] = decision.can_enter
        return self._finalize_snapshot(
            _snapshot_with_reasons(
                snapshot.model_copy(update=updates),
                blockers=blockers,
                warnings=warnings,
            )
        )

    def merge_execution(
        self,
        snapshot: SignalDecisionSnapshot,
        *,
        blockers: Iterable[str] = (),
        warnings: Iterable[str] = (),
        scope: DecisionReasonScope = "real",
        metadata: Mapping[str, Any] | None = None,
    ) -> SignalDecisionSnapshot:
        blocker_reasons = [
            DecisionReason(
                code=_code_from_message(message, fallback="execution_blocker"),
                message=message,
                source="execution",
                severity="blocker",
                scope=scope,
                metadata=dict(metadata or {}),
            )
            for message in blockers
        ]
        warning_reasons = [
            DecisionReason(
                code=_code_from_message(message, fallback="execution_warning"),
                message=message,
                source="execution",
                severity="warning",
                scope=scope,
                metadata=dict(metadata or {}),
            )
            for message in warnings
        ]
        updates: dict[str, Any] = {}
        if blocker_reasons and scope == "virtual":
            updates["execution_allowed_virtual"] = False
        if blocker_reasons and scope == "real":
            updates["execution_allowed_real"] = False
        return self._finalize_snapshot(
            _snapshot_with_reasons(
                snapshot.model_copy(update=updates),
                blockers=blocker_reasons,
                warnings=warning_reasons,
            )
        )

    def _finalize_snapshot(self, snapshot: SignalDecisionSnapshot) -> SignalDecisionSnapshot:
        blockers = _dedupe_reasons(snapshot.blockers)
        warnings = _dedupe_reasons(snapshot.warnings)
        actionable = snapshot.signal_actionable
        if any(reason.scope == "discovery" for reason in blockers):
            actionable = False
        execution_allowed_virtual = snapshot.execution_allowed_virtual
        if any(reason.scope == "virtual" for reason in blockers):
            execution_allowed_virtual = False
        execution_allowed_real = snapshot.execution_allowed_real
        if any(reason.scope == "real" for reason in blockers):
            execution_allowed_real = False
        return snapshot.model_copy(
            update={
                "signal_actionable": actionable,
                "execution_allowed_virtual": execution_allowed_virtual,
                "execution_allowed_real": execution_allowed_real,
                "blockers": blockers,
                "warnings": warnings,
            }
        )


def from_pipeline_outputs(
    *,
    signal: StrategySignal,
    quality: MarketQualitySnapshot,
    confirmation: SignalConfirmationSnapshot,
    risk_reward: RiskRewardAssessment,
    no_trade_filter: NoTradeFilterResult,
    completeness: TradePlanCompletenessResult,
    trade_plan: TradePlan,
    candle_state: str,
    production_mode: bool,
    status: str,
    rr_guard_context: str = "discovery",
    regime: MarketRegimeSnapshot | None = None,
) -> SignalDecisionSnapshot:
    return SignalDecisionService().from_pipeline_outputs(
        signal=signal,
        quality=quality,
        confirmation=confirmation,
        risk_reward=risk_reward,
        no_trade_filter=no_trade_filter,
        completeness=completeness,
        trade_plan=trade_plan,
        candle_state=candle_state,
        production_mode=production_mode,
        status=status,
        rr_guard_context=rr_guard_context,
        regime=regime,
    )


def merge_market_quality(
    snapshot: SignalDecisionSnapshot,
    quality: MarketQualitySnapshot,
) -> SignalDecisionSnapshot:
    return SignalDecisionService().merge_market_quality(snapshot, quality)


def merge_no_trade(
    snapshot: SignalDecisionSnapshot,
    no_trade: NoTradeFilterResult,
) -> SignalDecisionSnapshot:
    return SignalDecisionService().merge_no_trade(snapshot, no_trade)


def merge_market_regime(
    snapshot: SignalDecisionSnapshot,
    regime: MarketRegimeSnapshot | None,
) -> SignalDecisionSnapshot:
    return SignalDecisionService().merge_market_regime(snapshot, regime)


def merge_rr(
    snapshot: SignalDecisionSnapshot,
    risk_reward: RiskRewardAssessment,
    *,
    scope: DecisionReasonScope = "discovery",
) -> SignalDecisionSnapshot:
    return SignalDecisionService().merge_rr(snapshot, risk_reward, scope=scope)


def merge_trade_plan_completeness(
    snapshot: SignalDecisionSnapshot,
    completeness: TradePlanCompletenessResult,
    *,
    production_mode: bool,
) -> SignalDecisionSnapshot:
    return SignalDecisionService().merge_trade_plan_completeness(
        snapshot,
        completeness,
        production_mode=production_mode,
    )


def merge_candle_state(
    snapshot: SignalDecisionSnapshot,
    *,
    candle_state: str,
    confirmation: SignalConfirmationSnapshot | None = None,
) -> SignalDecisionSnapshot:
    return SignalDecisionService().merge_candle_state(
        snapshot,
        candle_state=candle_state,
        confirmation=confirmation,
    )


def merge_risk_decision(
    snapshot: SignalDecisionSnapshot,
    decision: RiskDecision,
) -> SignalDecisionSnapshot:
    return SignalDecisionService().merge_risk_decision(snapshot, decision)


def _snapshot_with_reasons(
    snapshot: SignalDecisionSnapshot,
    *,
    blockers: Iterable[DecisionReason] = (),
    warnings: Iterable[DecisionReason] = (),
) -> SignalDecisionSnapshot:
    return snapshot.model_copy(
        update={
            "blockers": [*snapshot.blockers, *blockers],
            "warnings": [*snapshot.warnings, *warnings],
        }
    )


def _reasons_from_layer_result(
    *,
    messages: Iterable[str],
    checks: Iterable[SignalLayerCheck],
    status: str,
    source: DecisionReasonSource,
    severity: DecisionReasonSeverity,
    scope: DecisionReasonScope,
    metadata: Mapping[str, Any],
    fallback_code: str,
) -> list[DecisionReason]:
    by_message: dict[str, DecisionReason] = {}
    for check in checks:
        if check.status != status:
            continue
        reason = _reason_from_check(
            check,
            source=source,
            severity=severity,
            scope=scope,
            extra_metadata=metadata,
        )
        by_message[reason.message] = reason
    for message in messages:
        if message in by_message:
            continue
        by_message[message] = DecisionReason(
            code=_code_from_message(message, fallback=fallback_code),
            message=message,
            source=source,
            severity=severity,
            scope=scope,
            metadata=dict(metadata),
        )
    return list(by_message.values())


def _reason_from_check(
    check: SignalLayerCheck,
    *,
    source: DecisionReasonSource,
    severity: DecisionReasonSeverity,
    scope: DecisionReasonScope,
    extra_metadata: Mapping[str, Any] | None = None,
) -> DecisionReason:
    metadata = dict(check.metadata)
    if extra_metadata:
        metadata.update(dict(extra_metadata))
    if check.score is not None:
        metadata["score"] = check.score
    return DecisionReason(
        code=check.name,
        message=check.reason or check.name.replace("_", " "),
        source=source,
        severity=severity,
        scope=scope,
        metadata=metadata,
    )


def _market_regime_reason_code(check: SignalLayerCheck) -> str | None:
    metadata_code = check.metadata.get("reason_code")
    if isinstance(metadata_code, str) and metadata_code in {
        "liquidity_vacuum",
        "news_pump_mode",
        "market_wide_risk_off",
        "post_impulse",
        "chop_regime",
    }:
        return metadata_code
    return {
        "liquidity_vacuum": "liquidity_vacuum",
        "news_pump": "news_pump_mode",
        "news_pump_mode": "news_pump_mode",
        "market_wide_risk_off": "market_wide_risk_off",
        "post_impulse": "post_impulse",
        "post_impulse_entry": "post_impulse",
        "chop": "chop_regime",
        "chop_regime": "chop_regime",
    }.get(check.name)


def _market_regime_scope(code: str, *, failed: bool) -> DecisionReasonScope:
    if not failed:
        return "discovery"
    if code in {"liquidity_vacuum", "news_pump_mode", "market_wide_risk_off"}:
        return "discovery"
    return "virtual"


def _dedupe_reasons(reasons: Iterable[DecisionReason]) -> list[DecisionReason]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[DecisionReason] = []
    for reason in reasons:
        key = (reason.source, reason.severity, reason.scope, reason.code, reason.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(reason)
    return result


def _find_check(checks: Iterable[SignalLayerCheck], name: str) -> SignalLayerCheck | None:
    for check in checks:
        if check.name == name:
            return check
    return None


def _metadata_bool(metadata: Mapping[str, Any], key: str, *, fallback: bool | None = None) -> bool | None:
    value = metadata.get(key)
    if isinstance(value, bool):
        return value
    return fallback


def _source_from_metadata(value: Any) -> DecisionReasonSource:
    normalized = str(value or "setup").strip().lower()
    if normalized in {"setup", "market_quality", "rr", "no_trade", "risk", "execution", "data"}:
        return cast(DecisionReasonSource, normalized)
    return "setup"


def _scope_from_context(context: str | None) -> DecisionReasonScope:
    value = str(context or "").strip().lower()
    if value in {"virtual", "real", "backtest", "discovery"}:
        return cast(DecisionReasonScope, value)
    return "discovery"


def _code_from_message(message: str, *, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", message.strip().lower()).strip("_")
    if not normalized:
        return fallback
    return normalized[:80]


signal_decision_service = SignalDecisionService()
