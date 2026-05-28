"""Virtual trading service module.

Keep virtual trading separate from real exchange execution. This package is the
future extraction point for a standalone virtual-trading worker/process.
"""

from app.services.virtual_trading.execution_engine import (
    VirtualExecutionEngine,
    VirtualExecutionRejected,
)
from app.services.virtual_trading.service import (
    TradeService,
    VirtualTradingService,
    trade_service,
    virtual_trading_service,
)
from app.services.virtual_trading.simulation_model import get_virtual_simulation_model_info

__all__ = [
    "TradeService",
    "VirtualExecutionEngine",
    "VirtualExecutionRejected",
    "VirtualTradingService",
    "get_virtual_simulation_model_info",
    "trade_service",
    "virtual_trading_service",
]
