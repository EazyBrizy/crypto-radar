"""Deprecated compatibility shim for the canonical virtual trading package."""

from app.services.virtual_trading.execution_engine import (
    VirtualExecutionEngine,
    VirtualExecutionRejected,
)

__all__ = ["VirtualExecutionEngine", "VirtualExecutionRejected"]
