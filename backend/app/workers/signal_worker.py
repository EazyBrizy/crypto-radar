import asyncio
import contextlib
import hashlib
import logging
import time
from typing import Optional

from app.core.config import settings
from app.domain.signal_status import is_execution_candidate_status
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
SIGNAL_EXPIRY_MAINTENANCE_INTERVAL_SEC = 30
SIGNAL_EXPIRY_MAINTENANCE_LIMIT = 500


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
        scanner_stats = dict(self._scanner.stats)
        if not self.is_running and scanner_stats.get("stage") not in {"error", "idle"}:
            scanner_stats["stage"] = "stopped"
        return {
            "scanner_running": self.is_running,
            "scanner_stopping": self.is_stopping,
            "processed_signals": self._processed_signals,
            "scanner_subscription_hash": self._scanner_subscription_hash,
            "strategy_config_hash": radar_config_service.strategy_config_hash(),
            **scanner_stats,
            "market_data_status": _derive_market_data_status(
                scanner_stats,
                scanner_running=self.is_running,
            ),
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
            notified_execution_keys = _existing_execution_notification_keys(self._store)
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
                    if not _should_publish_created_signal(radar_signal):
                        logger.debug(
                            "Radar signal created event suppressed by dedup: %s %s %s",
                            radar_signal.id,
                            radar_signal.symbol,
                            radar_signal.direction,
                        )
                        continue
                    self._processed_signals += 1
                    await realtime_event_broker.publish(signal_created_event(radar_signal))
                    if _should_notify_signal(radar_signal, notified_execution_keys=notified_execution_keys):
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
            self._scanner.record_error(exc)
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
            universe = radar_config_service.scanner_universe()
            return radar_config_service.scanner_subscription_hash(universe)
        except ScannerUniverseLimitError as exc:
            digest = hashlib.sha256(str(exc).encode("utf-8")).hexdigest()[:16]
            return f"blocked:{digest}"


class SignalExpiryWorker:
    """Expires stale open signals outside request/read paths."""

    def __init__(
        self,
        *,
        store: SignalService = signal_service,
        interval_seconds: int = SIGNAL_EXPIRY_MAINTENANCE_INTERVAL_SEC,
        limit: int = SIGNAL_EXPIRY_MAINTENANCE_LIMIT,
    ) -> None:
        self._store = store
        self._interval_seconds = max(1, int(interval_seconds))
        self._limit = max(1, int(limit))
        self._task: Optional[asyncio.Task[None]] = None
        self._stopping = False
        self._last_result: dict[str, object] = {}

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_result(self) -> dict[str, object]:
        return dict(self._last_result)

    def start(self) -> None:
        if self.is_running:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run())
        logger.info("Signal expiry worker started")

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
            logger.warning("Signal expiry worker stop timed out after %.1f seconds", STOP_TIMEOUT_SEC)
            return
        task = done.pop()
        with contextlib.suppress(asyncio.CancelledError):
            task.result()
        logger.info("Signal expiry worker stopped")
        if self._task is task:
            self._task = None
            self._stopping = False

    async def expire_once(self) -> dict[str, object]:
        expired = await asyncio.to_thread(
            self._store.expire_open_signals,
            limit=self._limit,
        )
        self._last_result = {"expired": expired, "limit": self._limit}
        return self.last_result

    async def _run(self) -> None:
        while True:
            try:
                result = await self.expire_once()
                if result["expired"]:
                    logger.info("Expired stale open signals: %s", result["expired"])
            except Exception as exc:
                logger.warning("Signal expiry maintenance failed: %s", exc)
            await asyncio.sleep(self._interval_seconds)


def _derive_market_data_status(
    scanner_stats: dict[str, object],
    *,
    scanner_running: bool,
) -> str:
    stage = str(scanner_stats.get("stage") or "")
    if stage == "error":
        return "error"
    if not scanner_running:
        return "offline"
    if stage == "stale":
        return "stale"
    last_tick_age_seconds = _float_or_none(scanner_stats.get("last_tick_age_seconds"))
    if last_tick_age_seconds is None:
        return "waiting"
    if last_tick_age_seconds > settings.scanner_market_data_stale_seconds:
        return "stale"
    return "online"


def _existing_execution_notification_keys(store: object) -> set[tuple[str, str, str]]:
    list_open = getattr(store, "list_open_signals", None)
    if not callable(list_open):
        return set()
    try:
        signals = list_open()
    except Exception as exc:
        logger.warning("Signal notification dedupe preload failed: %s", exc)
        return set()
    return {
        key
        for key in (_execution_notification_key(signal) for signal in signals)
        if key is not None
    }


def _should_notify_signal(
    signal: object,
    *,
    notified_execution_keys: set[tuple[str, str, str]] | None = None,
) -> bool:
    if _is_suppressed_duplicate_signal(signal):
        return False
    gate = getattr(signal, "execution_gate", None)
    if gate is None:
        return _legacy_signal_is_notification_eligible(signal)
    status = getattr(signal, "status", None)
    if not isinstance(status, str) or not is_execution_candidate_status(status):
        return False
    if not bool(gate.can_notify and gate.can_show_in_execution_feed and gate.feed_kind == "execution_signal"):
        return False
    if notified_execution_keys is None:
        return True
    key = _execution_notification_key(signal)
    if key is None:
        return True
    if key in notified_execution_keys:
        return False
    notified_execution_keys.add(key)
    return True


def _should_publish_created_signal(signal: object) -> bool:
    return not _is_suppressed_duplicate_signal(signal)


def _is_suppressed_duplicate_signal(signal: object) -> bool:
    gate = getattr(signal, "execution_gate", None)
    metadata = getattr(gate, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    dedup = metadata.get("dedup")
    return isinstance(dedup, dict) and dedup.get("action") == "suppress"


def _legacy_signal_is_notification_eligible(signal: object) -> bool:
    status = getattr(signal, "status", None)
    candle_state = getattr(signal, "candle_state", None)
    score = _float_or_none(getattr(signal, "score", None))
    if not isinstance(status, str) or not is_execution_candidate_status(status):
        return False
    if candle_state != "closed":
        return False
    return score is not None and score >= settings.execution_min_score


def _execution_notification_key(signal: object) -> tuple[str, str, str] | None:
    exchange = getattr(signal, "exchange", None)
    symbol = getattr(signal, "symbol", None)
    direction = getattr(signal, "direction", None)
    if not isinstance(exchange, str) or not isinstance(symbol, str) or not isinstance(direction, str):
        return None
    return (exchange.strip().lower(), _normalize_signal_symbol(symbol), direction.strip().lower())


def _normalize_signal_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace(":PERP", "").upper()


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
