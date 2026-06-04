from __future__ import annotations

import logging

from app.schemas.signal import RadarSignal
from app.services.signal_service import SignalService, signal_service

logger = logging.getLogger(__name__)


class SignalAutoEntryService:
    def __init__(self, signals: SignalService | None = None) -> None:
        self._signals = signals or signal_service

    async def execute_if_ready(self, signal: RadarSignal) -> RadarSignal | None:
        logger.debug(
            "Legacy status-only auto-entry ignored for signal %s; pending entries are tick-driven.",
            signal.id,
        )
        return None


auto_entry_service = SignalAutoEntryService()
