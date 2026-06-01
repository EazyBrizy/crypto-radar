from __future__ import annotations

import asyncio
import logging

from app.models.signal import SignalOutcome
from app.schemas.candle import OHLCVCandle
from app.services.signal_outcome_service import SignalOutcomeService, signal_outcome_service

logger = logging.getLogger(__name__)


class SignalOutcomeWorker:
    def __init__(self, outcomes: SignalOutcomeService | None = None) -> None:
        self._outcomes = outcomes or signal_outcome_service

    async def process_closed_candle(self, candle: OHLCVCandle) -> list[SignalOutcome]:
        if not candle.is_closed:
            return []
        try:
            return await asyncio.to_thread(
                self._outcomes.update_open_outcomes_for_candle,
                candle,
            )
        except Exception as exc:
            logger.warning(
                "Signal outcome update failed for %s:%s:%s: %s",
                candle.exchange,
                candle.symbol,
                candle.timeframe,
                exc,
            )
            return []


signal_outcome_worker = SignalOutcomeWorker()
