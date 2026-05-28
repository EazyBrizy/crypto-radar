"""Simulation model registry entrypoint for virtual trading."""

from app.services.virtual_simulation_model import get_virtual_simulation_model_info

__all__ = ["get_virtual_simulation_model_info"]
