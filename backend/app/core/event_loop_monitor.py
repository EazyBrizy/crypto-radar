from __future__ import annotations

import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger("app.event_loop")


def event_loop_lag_ms(*, expected_at: float, observed_at: float) -> float:
    return max(0.0, (observed_at - expected_at) * 1000)


def should_warn_event_loop_lag(*, lag_ms: float, threshold_seconds: float) -> bool:
    return lag_ms >= max(0.0, threshold_seconds * 1000)


async def monitor_event_loop_lag(
    *,
    interval_seconds: float | None = None,
    warning_seconds: float | None = None,
) -> None:
    interval = max(0.05, float(interval_seconds or settings.event_loop_lag_interval_seconds))
    threshold = max(0.0, float(warning_seconds or settings.event_loop_lag_warning_seconds))
    loop = asyncio.get_running_loop()
    expected_at = loop.time() + interval
    while True:
        await asyncio.sleep(interval)
        observed_at = loop.time()
        lag_ms = event_loop_lag_ms(expected_at=expected_at, observed_at=observed_at)
        if should_warn_event_loop_lag(lag_ms=lag_ms, threshold_seconds=threshold):
            logger.warning(
                "Event loop lag detected: lag_ms=%.2f threshold_ms=%.2f",
                lag_ms,
                threshold * 1000,
                extra={"lag_ms": lag_ms, "threshold_ms": threshold * 1000},
            )
        expected_at = observed_at + interval
