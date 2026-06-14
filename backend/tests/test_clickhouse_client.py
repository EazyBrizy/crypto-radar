from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.clickhouse_client import create_clickhouse_client


class _FakePoolManager:
    def __init__(self) -> None:
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


class _FakeClickHouseClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ClickHouseClientTest(unittest.TestCase):
    def test_create_clickhouse_client_owns_and_clears_dedicated_pool(self) -> None:
        pool = _FakePoolManager()
        raw_client = _FakeClickHouseClient()

        with (
            patch("app.core.clickhouse_client.get_pool_manager", return_value=pool, create=True),
            patch("app.core.clickhouse_client.clickhouse_connect.get_client", return_value=raw_client) as get_client,
            patch("app.core.clickhouse_client.all_managers", {pool: 1}, create=True) as pool_registry,
        ):
            client = create_clickhouse_client()

            self.assertIs(get_client.call_args.kwargs["pool_mgr"], pool)
            self.assertIn(pool, pool_registry)

            client.close()

            self.assertTrue(raw_client.closed)
            self.assertTrue(pool.cleared)
            self.assertNotIn(pool, pool_registry)


if __name__ == "__main__":
    unittest.main()
