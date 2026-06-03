from __future__ import annotations

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


def _normalized(status: str) -> str:
    return status.strip().lower()

