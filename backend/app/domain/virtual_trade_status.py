"""Domain status helpers for virtual position lifecycle."""

from __future__ import annotations

ACTIVE_VIRTUAL_TRADE_STATUSES = frozenset({"open", "partially_closed"})
TERMINAL_VIRTUAL_TRADE_STATUSES = frozenset(
    {"closed", "stopped", "invalidated", "expired", "cancelled"}
)
VIRTUAL_TRADE_STATUSES = ACTIVE_VIRTUAL_TRADE_STATUSES | TERMINAL_VIRTUAL_TRADE_STATUSES

STOP_CLOSE_REASONS = frozenset({"stop_loss", "breakeven_stop", "trailing_stop"})


def is_active_virtual_trade_status(status: str | None) -> bool:
    return status in ACTIVE_VIRTUAL_TRADE_STATUSES


def is_terminal_virtual_trade_status(status: str | None) -> bool:
    return status in TERMINAL_VIRTUAL_TRADE_STATUSES


def virtual_trade_status_for_close_reason(reason: str | None) -> str:
    if reason in STOP_CLOSE_REASONS:
        return "stopped"
    if reason == "invalidation":
        return "invalidated"
    if reason == "time_stop":
        return "expired"
    if reason == "cancelled":
        return "cancelled"
    return "closed"
