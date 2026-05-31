import asyncio
import unittest

from app.workers.derivative_snapshot_worker import DerivativeSnapshotSyncRunner


class FakeDerivativeSnapshotService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def refresh_bybit_symbols(self, *, symbols: list[str], category: str):
        self.calls.append((category, tuple(symbols)))
        return [object() for _ in symbols]


class DerivativeSnapshotSyncRunnerTest(unittest.TestCase):
    def test_sync_once_refreshes_configured_symbols_and_categories(self) -> None:
        service = FakeDerivativeSnapshotService()
        runner = DerivativeSnapshotSyncRunner(
            service=service,  # type: ignore[arg-type]
            symbols_provider=lambda: ["btcusdt", "ETHUSDT"],
            categories_provider=lambda: ["linear"],
            interval_seconds=30,
        )

        result = asyncio.run(runner.sync_once())

        self.assertEqual(service.calls, [("linear", ("BTCUSDT", "ETHUSDT"))])
        self.assertEqual(result["synced"], 2)
        self.assertEqual(result["errors"], [])

    def test_sync_once_keeps_running_after_category_error(self) -> None:
        class FailingThenWorkingService:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def refresh_bybit_symbols(self, *, symbols: list[str], category: str):
                self.calls.append(category)
                if category == "linear":
                    raise ValueError("ticker unavailable")
                return [object()]

        service = FailingThenWorkingService()
        runner = DerivativeSnapshotSyncRunner(
            service=service,  # type: ignore[arg-type]
            symbols_provider=lambda: ["BTCUSDT"],
            categories_provider=lambda: ["linear", "inverse"],
            interval_seconds=30,
        )

        result = asyncio.run(runner.sync_once())

        self.assertEqual(service.calls, ["linear", "inverse"])
        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["errors"], ["linear: ticker unavailable"])


if __name__ == "__main__":
    unittest.main()
