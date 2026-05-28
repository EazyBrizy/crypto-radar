import unittest
from unittest.mock import patch

from fastapi.routing import APIRoute

from app.api.v1.router import api_router
from app.core.database import get_db_session
from app.core.health import get_storage_health
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork


class DummySession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class DbAccessFoundationTest(unittest.TestCase):
    def test_storage_health_reports_ok_when_all_components_are_ok(self) -> None:
        ok = {"status": "ok", "latency_ms": 1.0}
        with (
            patch("app.core.health.check_postgres_health", return_value=ok),
            patch("app.core.health.check_clickhouse_health", return_value=ok),
            patch("app.core.health.check_redis_health", return_value=ok),
        ):
            health = get_storage_health()

        self.assertEqual(health["status"], "ok")
        self.assertEqual(set(health["components"]), {"postgres", "clickhouse", "redis"})

    def test_storage_health_reports_degraded_when_a_component_fails(self) -> None:
        ok = {"status": "ok", "latency_ms": 1.0}
        error = {"status": "error", "latency_ms": 1.0, "error": "ConnectionError"}
        with (
            patch("app.core.health.check_postgres_health", return_value=ok),
            patch("app.core.health.check_clickhouse_health", return_value=error),
            patch("app.core.health.check_redis_health", return_value=ok),
        ):
            health = get_storage_health()

        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["components"]["clickhouse"]["error"], "ConnectionError")

    def test_api_router_exposes_storage_health_endpoint(self) -> None:
        paths = {
            route.path
            for route in api_router.routes
            if isinstance(route, APIRoute)
        }

        self.assertIn("/api/v1/health", paths)
        self.assertIn("/api/v1/health/storage", paths)

    def test_unit_of_work_commits_and_closes_successful_scope(self) -> None:
        session = DummySession()

        with SqlAlchemyUnitOfWork(lambda: session):
            pass

        self.assertTrue(session.committed)
        self.assertFalse(session.rolled_back)
        self.assertTrue(session.closed)

    def test_unit_of_work_rolls_back_and_closes_failed_scope(self) -> None:
        session = DummySession()

        with self.assertRaises(RuntimeError):
            with SqlAlchemyUnitOfWork(lambda: session):
                raise RuntimeError("boom")

        self.assertFalse(session.committed)
        self.assertTrue(session.rolled_back)
        self.assertTrue(session.closed)

    def test_db_session_dependency_closes_session(self) -> None:
        session = DummySession()
        with patch("app.core.database.SessionLocal", return_value=session):
            dependency = get_db_session()
            self.assertIs(next(dependency), session)
            with self.assertRaises(StopIteration):
                next(dependency)

        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
