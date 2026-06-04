from __future__ import annotations

from typing import Any

OPEN_SIGNAL_STATUSES: tuple[str, ...] = (
    "new",
    "active",
    "watchlist",
    "ready",
    "wait_for_pullback",
    "entry_touched",
    "actionable",
)

MARKET_OPPORTUNITY_STATUSES: tuple[str, ...] = OPEN_SIGNAL_STATUSES

WAITING_ENTRY_STATUSES: tuple[str, ...] = (
    "new",
    "active",
    "watchlist",
    "ready",
    "wait_for_pullback",
)

EXECUTION_CANDIDATE_STATUSES: tuple[str, ...] = (
    "entry_touched",
    "actionable",
    "confirmed",
)

TERMINAL_SIGNAL_STATUSES: tuple[str, ...] = (
    "invalidated",
    "expired",
    "closed",
    "rejected",
)


def is_market_opportunity_status(status: str) -> bool:
    return _normalized(status) in MARKET_OPPORTUNITY_STATUSES


def is_waiting_entry_status(status: str) -> bool:
    return _normalized(status) in WAITING_ENTRY_STATUSES


def is_execution_candidate_status(status: str) -> bool:
    return _normalized(status) in EXECUTION_CANDIDATE_STATUSES


def is_terminal_signal_status(status: str) -> bool:
    return _normalized(status) in TERMINAL_SIGNAL_STATUSES


def can_signal_enter_now(
    status: str,
    *,
    decision: Any | None = None,
    can_enter: bool | None = None,
    mode: str = "virtual",
) -> bool:
    if not is_execution_candidate_status(status):
        return False

    normalized_mode = mode.strip().lower()
    if normalized_mode != "real":
        if can_enter is False:
            return False
        if can_enter is True:
            return True

    if decision is None:
        return True
    if _decision_field(decision, "signal_actionable") is not True:
        return False

    execution_allowed = (
        _decision_field(decision, "execution_allowed_real")
        if normalized_mode == "real"
        else _decision_field(decision, "execution_allowed_virtual")
    )
    if execution_allowed is False:
        return False

    blocked_scopes = {"discovery", "real"} if normalized_mode == "real" else {"discovery", "virtual"}
    blockers = _decision_field(decision, "blockers") or ()
    return not any(_decision_field(reason, "scope") in blocked_scopes for reason in blockers)


def _normalized(status: str) -> str:
    return status.strip().lower()


def _decision_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)
