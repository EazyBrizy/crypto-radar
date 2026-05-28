from time import perf_counter
from typing import Any

import clickhouse_connect

from app.core.config import settings

_clickhouse_client: Any | None = None


def create_clickhouse_client() -> Any:
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
    )


def get_clickhouse_client() -> Any:
    global _clickhouse_client
    if _clickhouse_client is None:
        _clickhouse_client = create_clickhouse_client()
    return _clickhouse_client


def close_clickhouse_client() -> None:
    global _clickhouse_client
    if _clickhouse_client is not None:
        _clickhouse_client.close()
        _clickhouse_client = None


def check_clickhouse_health() -> dict[str, object]:
    started_at = perf_counter()
    client: Any | None = None
    try:
        client = create_clickhouse_client()
        client.command("SELECT 1")
        return {
            "status": "ok",
            "latency_ms": round((perf_counter() - started_at) * 1000, 2),
        }
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": round((perf_counter() - started_at) * 1000, 2),
            "error": exc.__class__.__name__,
        }
    finally:
        if client is not None:
            client.close()
