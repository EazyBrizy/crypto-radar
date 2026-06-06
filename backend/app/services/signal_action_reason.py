from __future__ import annotations

from typing import Any, Literal

from app.domain.signal_status import is_terminal_signal_status
from app.schemas.signal import RadarSignal, SignalExecutionGateReason

SignalActionReasonSeverity = Literal["blocker", "warning", "info"]
SignalActionReason = dict[str, str]


_PRIORITY_CODES = (
    "forming_candle",
    "trigger_not_confirmed",
    "edge_unknown",
    "edge_missing",
    "trade_plan_incomplete",
    "no_trade_hard_block",
    "rr_failed",
    "decision_not_actionable",
    "virtual_execution_blocked",
    "terminal_signal",
)

_DEFAULT_MESSAGES: dict[str, tuple[str, str]] = {
    "forming_candle": ("Candle is still forming.", "market_data"),
    "trigger_not_confirmed": ("Trigger is not confirmed yet.", "trigger"),
    "edge_unknown": ("Execution edge is unknown.", "edge"),
    "edge_missing": ("Execution edge data is missing.", "edge"),
    "trade_plan_incomplete": ("Trade plan is incomplete.", "trade_plan"),
    "no_trade_hard_block": ("No-trade filter blocks execution.", "no_trade_filter"),
    "rr_failed": ("Risk/reward guard failed.", "risk_reward"),
    "decision_not_actionable": ("Backend decision is not actionable.", "decision"),
    "virtual_execution_blocked": ("Virtual execution is blocked.", "virtual_execution"),
    "terminal_signal": ("Signal is terminal.", "signal"),
    "execution_gate_blocked": ("Execution gate blocks this action.", "execution_gate"),
}


def main_execution_blocker(signal: RadarSignal) -> SignalActionReason:
    gate_reason = _execution_gate_reason(signal)
    if gate_reason is not None:
        return _from_gate_reason(gate_reason)

    inferred_code = _infer_reason_code(signal)
    return _default_reason(inferred_code or "execution_gate_blocked")


def pending_entry_disabled_reason(signal: RadarSignal) -> SignalActionReason:
    return main_execution_blocker(signal)


def enter_now_disabled_reason(signal: RadarSignal) -> SignalActionReason:
    return main_execution_blocker(signal)


def _execution_gate_reason(signal: RadarSignal) -> SignalExecutionGateReason | None:
    gate = signal.execution_gate
    if gate is None:
        return None
    blocker = next((reason for reason in gate.reasons if reason.severity == "blocker"), None)
    if blocker is not None:
        return blocker
    for code in _PRIORITY_CODES:
        reason = next((item for item in gate.reasons if item.code == code), None)
        if reason is not None:
            return reason
    return gate.reasons[0] if gate.reasons else None


def _infer_reason_code(signal: RadarSignal) -> str | None:
    if is_terminal_signal_status(signal.status):
        return "terminal_signal"
    if signal.candle_state != "closed":
        return "forming_candle"
    if signal.trigger is not None and not signal.trigger.passed:
        return "trigger_not_confirmed"
    if signal.edge is None:
        return "edge_missing"
    if signal.edge.status == "unknown":
        return "edge_unknown"
    if signal.trade_plan is None:
        return "trade_plan_incomplete"
    if signal.no_trade_filter is not None and signal.no_trade_filter.blocked:
        return "no_trade_hard_block"
    if signal.can_enter is False:
        return "decision_not_actionable"
    return None


def _from_gate_reason(reason: SignalExecutionGateReason) -> SignalActionReason:
    return {
        "code": reason.code,
        "message": reason.message,
        "source": reason.source,
        "severity": reason.severity,
    }


def _default_reason(code: str) -> SignalActionReason:
    message, source = _DEFAULT_MESSAGES.get(code, _DEFAULT_MESSAGES["execution_gate_blocked"])
    return {
        "code": code,
        "message": message,
        "source": source,
        "severity": "blocker",
    }
