from __future__ import annotations

PENDING_ENTRY_INTENT_STATUSES: tuple[str, ...] = (
    "pending",
    "triggered",
    "filling",
    "filled",
    "failed",
    "cancelled",
    "expired",
    "requires_reconfirmation",
)

ACTIVE_PENDING_STATUSES: tuple[str, ...] = (
    "pending",
    "triggered",
    "filling",
    "requires_reconfirmation",
)

TERMINAL_PENDING_STATUSES: tuple[str, ...] = (
    "filled",
    "failed",
    "cancelled",
    "expired",
)

ACTIVE_PENDING_ENTRY_INTENT_STATUSES = ACTIVE_PENDING_STATUSES
TERMINAL_PENDING_ENTRY_INTENT_STATUSES = TERMINAL_PENDING_STATUSES


def is_active_pending_entry_intent_status(status: str) -> bool:
    return _normalized(status) in ACTIVE_PENDING_ENTRY_INTENT_STATUSES


def is_terminal_pending_entry_intent_status(status: str) -> bool:
    return _normalized(status) in TERMINAL_PENDING_ENTRY_INTENT_STATUSES


def _normalized(status: str) -> str:
    return status.strip().lower()
