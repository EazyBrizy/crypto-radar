import asyncio
import unittest

from app.workers.exchange_instrument_worker import ExchangeInstrumentRuleSyncRunner


class FakeInstrumentRuleService:
    def __init__(self) -> None:
        self.categories: list[str] = []

    def sync_bybit_rules(self, *, category: str, symbol=None):
        self.categories.append(category)
        return [object(), object()]


class ExchangeInstrumentRuleSyncRunnerTest(unittest.TestCase):
    def test_sync_once_refreshes_configured_categories(self) -> None:
        service = FakeInstrumentRuleService()
        runner = ExchangeInstrumentRuleSyncRunner(
            service=service,  # type: ignore[arg-type]
            categories_provider=lambda: ["linear", "spot"],
            interval_seconds=60,
        )

        result = asyncio.run(runner.sync_once())

        self.assertEqual(service.categories, ["linear", "spot"])
        self.assertEqual(result["synced"], 4)
        self.assertEqual(result["errors"], [])

    def test_sync_once_keeps_running_after_category_error(self) -> None:
        class FailingThenWorkingService:
            def __init__(self) -> None:
                self.categories: list[str] = []

            def sync_bybit_rules(self, *, category: str, symbol=None):
                self.categories.append(category)
                if category == "linear":
                    raise ValueError("network unavailable")
                return [object()]

        service = FailingThenWorkingService()
        runner = ExchangeInstrumentRuleSyncRunner(
            service=service,  # type: ignore[arg-type]
            categories_provider=lambda: ["linear", "spot"],
            interval_seconds=60,
        )

        result = asyncio.run(runner.sync_once())

        self.assertEqual(service.categories, ["linear", "spot"])
        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["errors"], ["linear: network unavailable"])


if __name__ == "__main__":
    unittest.main()
