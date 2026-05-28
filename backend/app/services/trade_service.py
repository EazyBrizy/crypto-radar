"""Compatibility facade for the virtual trading service.

New code should import from `app.services.virtual_trading`. This module stays so
older API routes, tests, and integrations keep working while the virtual
trading boundary is prepared for a future worker/process split.
"""

from app.services.virtual_trading.service import (
    TradeService,
    VirtualTradingService,
    trade_service,
    virtual_trading_service,
)

__all__ = [
    "TradeService",
    "VirtualTradingService",
    "trade_service",
    "virtual_trading_service",
]
