import unittest
from types import SimpleNamespace

from app.api.v1.radar import _scanner_status, start_scanner
from app.workers.signal_worker import ScannerRunner


class DummyRunner:
    def __init__(self) -> None:
        self.started = False

    @property
    def scanner_status(self) -> dict[str, object]:
        return {
            "scanner_running": self.started,
            "processed_signals": 0,
        }

    def start(self) -> None:
        self.started = True


class FakeRunningTask:
    def done(self) -> bool:
        return False


class FakeScanner:
    def __init__(self, stats: dict[str, object]) -> None:
        self._stats = stats

    @property
    def stats(self) -> dict[str, object]:
        return self._stats

    def record_error(self, exc: BaseException | str) -> None:
        self._stats["stage"] = "error"
        self._stats["last_error"] = str(exc)


class RadarScannerStatusTest(unittest.IsolatedAsyncioTestCase):
    def test_scanner_status_preserves_disabled_flag(self) -> None:
        status = _scanner_status(DummyRunner(), scanner_enabled=False)

        self.assertFalse(status["scanner_enabled"])
        self.assertFalse(status["scanner_running"])
        self.assertEqual(status["market_data_status"], "offline")

    async def test_start_scanner_can_start_when_autostart_is_disabled(self) -> None:
        runner = DummyRunner()
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    scanner_runner=runner,
                    scanner_autostart_enabled=False,
                )
            )
        )

        status = await start_scanner(request)

        self.assertTrue(runner.started)
        self.assertTrue(status["scanner_enabled"])
        self.assertTrue(status["scanner_running"])
        self.assertEqual(status["market_data_status"], "waiting")

    def test_runner_status_before_tick_is_waiting_not_online(self) -> None:
        runner = self._running_runner({
            "stage": "warming_up",
            "last_tick_age_seconds": None,
        })

        status = runner.scanner_status

        self.assertTrue(status["scanner_running"])
        self.assertEqual(status["market_data_status"], "waiting")

    def test_runner_status_after_recent_tick_is_online(self) -> None:
        runner = self._running_runner({
            "stage": "listening",
            "last_tick_age_seconds": 1.0,
        })

        status = runner.scanner_status

        self.assertEqual(status["market_data_status"], "online")

    def test_runner_status_after_stale_tick_is_stale(self) -> None:
        runner = self._running_runner({
            "stage": "listening",
            "last_tick_age_seconds": 60.0,
        })

        status = runner.scanner_status

        self.assertEqual(status["market_data_status"], "stale")

    def _running_runner(self, stats: dict[str, object]) -> ScannerRunner:
        runner = ScannerRunner(scanner=FakeScanner(stats))  # type: ignore[arg-type]
        runner._task = FakeRunningTask()  # type: ignore[assignment]
        return runner


if __name__ == "__main__":
    unittest.main()
