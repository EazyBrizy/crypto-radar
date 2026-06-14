from time import perf_counter
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.httputil import all_managers, get_pool_manager

from app.core.config import settings

_clickhouse_client: Any | None = None


class _OwnedPoolClickHouseClient:
    def __init__(self, client: Any, pool_mgr: Any) -> None:
        self._client = client
        self._pool_mgr = pool_mgr

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
        clear = getattr(self._pool_mgr, "clear", None)
        if callable(clear):
            clear()
        all_managers.pop(self._pool_mgr, None)


def create_clickhouse_client() -> Any:
    pool_mgr = get_pool_manager()
    try:
        client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
            pool_mgr=pool_mgr,
        )
    except Exception:
        pool_mgr.clear()
        raise
    return _OwnedPoolClickHouseClient(client, pool_mgr)


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
