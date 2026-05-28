from time import perf_counter

from redis import Redis

from app.core.config import settings

_redis_client: Redis | None = None


def create_redis_client() -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = create_redis_client()
    return _redis_client


def close_redis_client() -> None:
    global _redis_client
    if _redis_client is not None:
        _redis_client.close()
        _redis_client = None


def check_redis_health() -> dict[str, object]:
    started_at = perf_counter()
    try:
        get_redis_client().ping()
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
