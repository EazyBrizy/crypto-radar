import asyncio
import contextlib
import hashlib
import logging
import time
from typing import Optional

from app.core.config import settings
from app.services.market_scanner import MarketScanner
from app.services.candle_service import candle_service
from app.services.message_broker import realtime_event_broker
from app.services.notification_service import notification_service
from app.services.radar_config_service import ScannerUniverseLimitError, radar_config_service
from app.services.realtime_events import signal_created_event, signal_updated_event
from app.services.signal_service import SignalService, signal_service

logger = logging.getLogger(__name__)
STOP_TIMEOUT_SEC = 3.0
SIGNAL_UPDATE_EVENT_MIN_INTERVAL_SEC = 3.0


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
        self._stopping = False
        self._last_update_event_monotonic: dict[str, float] = {}
        self._scanner_subscription_hash = self._scanner_subscription_hash_for_current_config()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_stopping(self) -> bool:
        return self._stopping and self.is_running

    @property
    def processed_signals(self) -> int:
        return self._processed_signals

    @property
    def scanner_status(self) -> dict[str, object]:
        return {
            "scanner_running": self.is_running,
            "scanner_stopping": self.is_stopping,
            "processed_signals": self._processed_signals,
            "scanner_subscription_hash": self._scanner_subscription_hash,
            "strategy_config_hash": radar_config_service.strategy_config_hash(),
            **self._scanner.stats,
        }

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run())
        logger.info("Scanner runner started")

    async def reconfigure(self) -> None:
        next_subscription_hash = self._scanner_subscription_hash_for_current_config()
        should_rebuild = next_subscription_hash != self._scanner_subscription_hash
        was_running = self.is_running
        if was_running and should_rebuild:
            await self.stop()
        if not self._external_scanner and should_rebuild:
            self._scanner = self._build_configured_scanner()
            self._scanner_subscription_hash = next_subscription_hash
            self._processed_signals = 0
            self._last_update_event_monotonic.clear()
        elif not should_rebuild:
            logger.info("Scanner subscription config unchanged; runtime strategy cache was refreshed")
        if was_running and should_rebuild:
            self.start()

    async def stop(self) -> None:
        if self._task is None:
            return
        if self._task.done():
            self._task = None
            self._stopping = False
            return
        self._stopping = True
        self._task.cancel()
        try:
            done, pending = await asyncio.wait({self._task}, timeout=STOP_TIMEOUT_SEC)
        except asyncio.CancelledError:
            self._task.cancel()
            raise

        if pending:
            logger.warning(
                "Scanner runner stop timed out after %.1f seconds; cancellation is still pending",
                STOP_TIMEOUT_SEC,
            )
            return

        task = done.pop()
        with contextlib.suppress(asyncio.CancelledError):
            task.result()
        logger.info("Scanner runner stopped")
        if self._task is task:
            self._task = None
            self._stopping = False

    async def _run(self) -> None:
        try:
            async for signal in self._scanner.start():
                radar_signal, created = self._store.upsert_strategy_signal(
                    signal,
                    explanation=[
                        f"Сигнал рассчитан по свечам {signal.exchange} {signal.timeframe}",
                        *signal.explanation,
                    ],
                )
                if radar_signal.status == "expired":
                    logger.debug(
                        "Radar signal skipped after TTL expiry: %s %s %s",
                        radar_signal.id,
                        radar_signal.symbol,
                        radar_signal.direction,
                    )
                    continue
                if created:
                    self._processed_signals += 1
                    await realtime_event_broker.publish(signal_created_event(radar_signal))
                    try:
                        await notification_service.create_signal_notification(radar_signal)
                    except Exception as exc:
                        logger.warning("Signal notification write failed: %s", exc)
                    logger.info(
                        "Radar signal stored: %s %s %s",
                        radar_signal.id,
                        radar_signal.symbol,
                        radar_signal.direction,
                    )
                else:
                    if self._should_publish_update(radar_signal.id):
                        await realtime_event_broker.publish(signal_updated_event(radar_signal))
                        logger.debug(
                            "Radar signal refreshed: %s %s %s",
                            radar_signal.id,
                            radar_signal.symbol,
                            radar_signal.direction,
                        )
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Scanner runner failed: %s", exc)

    def _should_publish_update(self, signal_id: str) -> bool:
        now = time.monotonic()
        previous = self._last_update_event_monotonic.get(signal_id)
        if previous is not None and now - previous < SIGNAL_UPDATE_EVENT_MIN_INTERVAL_SEC:
            return False

        self._last_update_event_monotonic[signal_id] = now
        return True

    @staticmethod
    def _build_configured_scanner() -> MarketScanner:
        timeframes = radar_config_service.selected_timeframes()
        candle_service.configure_timeframes(timeframes)
        try:
            scanner_universe = radar_config_service.scanner_universe()
        except ScannerUniverseLimitError as exc:
            logger.warning("Scanner universe blocked by pair guard: %s", exc)
            return MarketScanner(
                symbols=[],
                exchanges=[],
                scan_pairs=[],
                universe_source="blocked",
                universe_warning=str(exc),
                max_scanner_pairs=settings.max_scanner_pairs,
                estimated_strategy_checks=0,
            )
        return MarketScanner(
            symbols=[symbol for _, symbol in scanner_universe.pairs],
            exchanges=[exchange for exchange, _ in scanner_universe.pairs],
            scan_pairs=scanner_universe.pairs,
            universe_source=scanner_universe.source,
            universe_warning=scanner_universe.warning,
            max_scanner_pairs=scanner_universe.max_pairs,
            estimated_strategy_checks=scanner_universe.estimated_strategy_checks,
        )

    @staticmethod
    def _scanner_subscription_hash_for_current_config() -> str:
        try:
            return radar_config_service.scanner_subscription_hash()
        except ScannerUniverseLimitError as exc:
            digest = hashlib.sha256(str(exc).encode("utf-8")).hexdigest()[:16]
            return f"blocked:{digest}"
