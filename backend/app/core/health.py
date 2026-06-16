from app.core.clickhouse_client import check_clickhouse_health
from app.core.database import check_postgres_health
from app.core.redis_client import check_redis_health
from app.schemas.health import StrategyTestWorkerLeaseState
from app.services.strategy_testing.stores import PostgresStrategyTestRunStore


def get_storage_health() -> dict[str, object]:
    components = {
        "postgres": check_postgres_health(),
        "clickhouse": check_clickhouse_health(),
        "redis": check_redis_health(),
    }
    status = "ok" if all(item["status"] == "ok" for item in components.values()) else "degraded"
    return {
        "status": status,
        "components": components,
    }


def get_strategy_test_worker_lease_state() -> StrategyTestWorkerLeaseState:
    try:
        return PostgresStrategyTestRunStore().get_worker_lease_state()
    except Exception as exc:
        return StrategyTestWorkerLeaseState(status="unavailable", error=str(exc))
