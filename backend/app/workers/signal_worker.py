import asyncio
import logging
from typing import Optional

from app.services.market_scanner import MarketScanner
from app.services.radar_config_service import radar_config_service
from app.services.signal_service import SignalService, signal_service

logger = logging.getLogger(__name__)


class ScannerRunner:
    """Запускает MarketScanner в фоне и сохраняет реальные сигналы в SignalService."""

    def __init__(
        self,
        scanner: Optional[MarketScanner] = None,
        store: SignalService = signal_service,
    ) -> None:
        self._scanner = scanner or self._build_configured_scanner()
        self._store = store
        self._task: Optional[asyncio.Task[None]] = None
        self._processed_signals = 0
        self._external_scanner = scanner is not None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def processed_signals(self) -> int:
        return self._processed_signals

    def start(self) -> None:
        if self.is_running:
            return
        self._task = asyncio.create_task(self._run())
        logger.info("Scanner runner started")

    async def reconfigure(self) -> None:
        was_running = self.is_running
        if was_running:
            await self.stop()
        if not self._external_scanner:
            self._scanner = self._build_configured_scanner()
            self._processed_signals = 0
        if was_running:
            self.start()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("Scanner runner stopped")
        finally:
            self._task = None

    async def _run(self) -> None:
        try:
            async for signal in self._scanner.start():
                radar_signal = self._store.add_strategy_signal(
                    signal,
                    explanation=[
                        f"Сигнал получен из realtime-потока {signal.exchange}",
                        f"Стратегия: {signal.strategy}",
                        f"Confidence: {signal.confidence:.2f}",
                    ],
                )
                self._processed_signals += 1
                logger.info(
                    "Radar signal stored: %s %s %s",
                    radar_signal.id,
                    radar_signal.symbol,
                    radar_signal.direction,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Scanner runner failed: %s", exc)

    @staticmethod
    def _build_configured_scanner() -> MarketScanner:
        return MarketScanner(
            symbols=radar_config_service.selected_symbols(),
            exchanges=radar_config_service.selected_exchanges(),
        )
