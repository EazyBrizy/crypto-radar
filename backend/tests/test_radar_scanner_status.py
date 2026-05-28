import unittest
from types import SimpleNamespace

from app.api.v1.radar import _scanner_status, start_scanner


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


class RadarScannerStatusTest(unittest.IsolatedAsyncioTestCase):
    def test_scanner_status_preserves_disabled_flag(self) -> None:
        status = _scanner_status(DummyRunner(), scanner_enabled=False)

        self.assertFalse(status["scanner_enabled"])
        self.assertFalse(status["scanner_running"])

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


if __name__ == "__main__":
    unittest.main()
