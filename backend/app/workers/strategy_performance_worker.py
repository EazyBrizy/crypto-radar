from __future__ import annotations

import asyncio
import logging
from datetime import date

from app.schemas.strategy_performance import StrategyPerformanceDaily
from app.services.strategy_performance_service import (
    StrategyPerformanceService,
    strategy_performance_service,
)

logger = logging.getLogger(__name__)


class StrategyPerformanceWorker:
    def __init__(self, performance: StrategyPerformanceService | None = None) -> None:
        self._performance = performance or strategy_performance_service

    async def aggregate_daily(self, *, day: date) -> list[StrategyPerformanceDaily]:
        try:
            return await asyncio.to_thread(self._performance.aggregate_daily, day=day)
        except Exception as exc:
            logger.warning("Strategy performance aggregation failed for %s: %s", day.isoformat(), exc)
            return []


strategy_performance_worker = StrategyPerformanceWorker()
