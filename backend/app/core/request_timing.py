from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request

from app.core.config import settings

REQUEST_ID_HEADER = "X-Request-Id"
RESPONSE_TIME_HEADER = "X-Response-Time-Ms"

logger = logging.getLogger("app.request_timing")


def add_request_timing_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_timing_middleware(request: Request, call_next):
        request_id = _request_id(request)
        start_time = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = _duration_ms(start_time)
            _log_request_timing(
                request=request,
                request_id=request_id,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = _duration_ms(start_time)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[RESPONSE_TIME_HEADER] = f"{duration_ms:.2f}"
        _log_request_timing(
            request=request,
            request_id=request_id,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        return response


def _request_id(request: Request) -> str:
    header_value = request.headers.get(REQUEST_ID_HEADER, "").strip()
    if header_value and len(header_value) <= 128:
        return header_value
    return str(uuid4())


def _duration_ms(start_time: float) -> float:
    return (time.perf_counter() - start_time) * 1000


def _log_request_timing(
    *,
    request: Request,
    request_id: str,
    status_code: int,
    duration_ms: float,
) -> None:
    method = request.method
    path = request.url.path
    extra = {
        "duration_ms": duration_ms,
        "method": method,
        "path": path,
        "request_id": request_id,
        "status_code": status_code,
    }
    logger.info(
        "FastAPI request: %s %s status=%s duration_ms=%.2f request_id=%s",
        method,
        path,
        status_code,
        duration_ms,
        request_id,
        extra=extra,
    )
    if duration_ms < settings.fastapi_slow_request_ms:
        return
    logger.warning(
        "Slow FastAPI request: %s %s status=%s duration_ms=%.2f request_id=%s",
        method,
        path,
        status_code,
        duration_ms,
        request_id,
        extra=extra,
    )
