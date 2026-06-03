from app.repositories.signal_repository import ACTIONABLE_SIGNAL_STATUSES, OPEN_SIGNAL_STATUSES


def is_open_market_opportunity_status(status: str) -> bool:
    return status in OPEN_SIGNAL_STATUSES


def is_execution_actionable_status(status: str) -> bool:
    return status in ACTIONABLE_SIGNAL_STATUSES
