from __future__ import annotations

from typing import Any

ENTRY_ZONE_NOT_TOUCHED = "entry_zone_not_touched"
PENDING_ENTRY_EXPIRED_BEFORE_TOUCH = "pending_entry_expired_before_touch"
PENDING_ENTRY_SIGNAL_MISSING = "pending_entry_signal_missing"
SIGNAL_TERMINAL = "signal_terminal"
TRADE_PLAN_RECONFIRMATION_REQUIRED = "trade_plan_reconfirmation_required"
RISK_GATE_REJECTED = "riskgate_rejected"
VIRTUAL_EXECUTION_REJECTED = "virtual_execution_rejected"
TEMPORARY_EXECUTION_FAILURE = "temporary_execution_failure"
REAL_PENDING_EXECUTION_NOT_ENABLED = "real_pending_execution_not_enabled"
PENDING_ENTRY_EXECUTION_INVALID = "pending_entry_execution_invalid"
EXECUTION_FAILED = "execution_failed"
CANCELLED = "cancelled"

PENDING_ENTRY_LAST_REASON_KEY = "pending_entry_last_reason_code"
PENDING_ENTRY_TERMINAL_REASON_KEY = "pending_entry_terminal_reason_code"
PENDING_ENTRY_GATE_SNAPSHOT_KEY = "pending_entry_gate_snapshot"


def pending_entry_reason_code_from_snapshot(snapshot: Any, *, terminal: bool = False) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    keys = (
        (PENDING_ENTRY_TERMINAL_REASON_KEY, PENDING_ENTRY_LAST_REASON_KEY)
        if terminal
        else (PENDING_ENTRY_LAST_REASON_KEY, PENDING_ENTRY_TERMINAL_REASON_KEY)
    )
    for key in keys:
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def pending_entry_fallback_reason_code(status: str) -> str | None:
    if status == "expired":
        return PENDING_ENTRY_EXPIRED_BEFORE_TOUCH
    if status == "cancelled":
        return CANCELLED
    if status == "failed":
        return EXECUTION_FAILED
    if status == "requires_reconfirmation":
        return TRADE_PLAN_RECONFIRMATION_REQUIRED
    return None


def pending_entry_terminal_kind(status: str, reason_code: str | None) -> str:
    if reason_code == PENDING_ENTRY_EXPIRED_BEFORE_TOUCH:
        return "expired_before_touch"
    if reason_code == VIRTUAL_EXECUTION_REJECTED:
        return "execution_rejected"
    if status == "expired":
        return "expired_before_touch"
    if status == "cancelled":
        return "cancelled_before_touch"
    if status == "failed":
        return "execution_failed"
    return "terminal"
