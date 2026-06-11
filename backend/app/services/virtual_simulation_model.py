"""Deprecated compatibility shim for the canonical virtual trading package."""

from app.services.virtual_trading.simulation_model import (
    capability_codes_for_report,
    get_virtual_simulation_model_info,
    planned_capability_codes_for_report,
    simulation_tier_for_report,
)

__all__ = [
    "capability_codes_for_report",
    "get_virtual_simulation_model_info",
    "planned_capability_codes_for_report",
    "simulation_tier_for_report",
]
