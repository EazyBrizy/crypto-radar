from app.domain.signal_status import (
    EXECUTION_CANDIDATE_STATUSES,
    MARKET_OPPORTUNITY_STATUSES,
    OPEN_SIGNAL_STATUSES,
    TERMINAL_SIGNAL_STATUSES,
    WAITING_ENTRY_STATUSES,
    can_signal_enter_now,
    is_execution_candidate_status,
    is_market_opportunity_status,
    is_terminal_signal_status,
    is_waiting_entry_status,
)


def is_open_market_opportunity_status(status: str) -> bool:
    return is_market_opportunity_status(status)


def is_execution_actionable_status(status: str) -> bool:
    return is_execution_candidate_status(status)


__all__ = [
    "OPEN_SIGNAL_STATUSES",
    "MARKET_OPPORTUNITY_STATUSES",
    "WAITING_ENTRY_STATUSES",
    "EXECUTION_CANDIDATE_STATUSES",
    "TERMINAL_SIGNAL_STATUSES",
    "can_signal_enter_now",
    "is_market_opportunity_status",
    "is_waiting_entry_status",
    "is_execution_candidate_status",
    "is_terminal_signal_status",
    "is_open_market_opportunity_status",
    "is_execution_actionable_status",
]
