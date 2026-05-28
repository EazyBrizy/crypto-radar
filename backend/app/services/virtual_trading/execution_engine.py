"""Compatibility entrypoint for virtual execution simulation.

The implementation still lives in `app.services.virtual_execution_engine` to
avoid a large-risk move. Import through this package in new code so the whole
virtual trading module can be extracted later without changing route code.
"""

from app.services.virtual_execution_engine import (
    VirtualExecutionEngine,
    VirtualExecutionRejected,
)

__all__ = ["VirtualExecutionEngine", "VirtualExecutionRejected"]
