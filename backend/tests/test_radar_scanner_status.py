import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api.v1.radar import _scanner_config_status, _scanner_status, start_scanner
from app.services.radar_config_service import ScannerUniverse
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
        with patch("app.api.v1.radar.radar_config_service", FakeRadarConfigService()):
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

        with patch("app.api.v1.radar.radar_config_service", FakeRadarConfigService()):
            status = await start_scanner(request)

        self.assertTrue(runner.started)
        self.assertTrue(status["scanner_enabled"])
        self.assertTrue(status["scanner_running"])
        self.assertEqual(status["market_data_status"], "waiting")

    def test_runner_status_before_tick_is_waiting_not_online(self) -> None:
        status = self._running_status({
            "stage": "warming_up",
            "last_tick_age_seconds": None,
        })

        self.assertTrue(status["scanner_running"])
        self.assertEqual(status["market_data_status"], "waiting")

    def test_runner_status_after_recent_tick_is_online(self) -> None:
        status = self._running_status({
            "stage": "listening",
            "last_tick_age_seconds": 1.0,
        })

        self.assertEqual(status["market_data_status"], "online")

    def test_runner_status_after_stale_tick_is_stale(self) -> None:
        status = self._running_status({
            "stage": "listening",
            "last_tick_age_seconds": 60.0,
        })

        self.assertEqual(status["market_data_status"], "stale")

    def test_runner_builds_full_universe_when_truncation_is_disabled(self) -> None:
        config = FakeRadarConfigService()

        with patch("app.workers.signal_worker.radar_config_service", config):
            runner = ScannerRunner()

        status = runner.scanner_status
        self.assertEqual(status["scanner_pairs_count"], 3)
        self.assertEqual(
            status["scan_pairs"],
            ["bybit:BTCUSDT", "bybit:ETHUSDT", "bybit:HYPEUSDT"],
        )
        self.assertEqual(status["scanner_universe_source"], "explicit pairs")
        self.assertIsNone(status["scanner_universe_warning"])
        self.assertFalse(config.truncate_requested)

    def test_status_summary_uses_full_universe_when_truncation_is_disabled(self) -> None:
        config = FakeRadarConfigService()

        with patch("app.api.v1.radar.radar_config_service", config):
            status = _scanner_config_status()

        self.assertEqual(status["scanner_pairs_count"], 3)
        self.assertEqual(
            status["scan_pairs"],
            ["bybit:BTCUSDT", "bybit:ETHUSDT", "bybit:HYPEUSDT"],
        )
        self.assertIsNone(status["scanner_universe_warning"])
        self.assertFalse(config.truncate_requested)

    def _running_status(self, stats: dict[str, object]) -> dict[str, object]:
        with patch("app.workers.signal_worker.radar_config_service", FakeRadarConfigService()):
            runner = ScannerRunner(scanner=FakeScanner(stats))  # type: ignore[arg-type]
            runner._task = FakeRunningTask()  # type: ignore[assignment]
            return runner.scanner_status


class MainForwardStrategyTestWorkerWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_lifespan_does_not_start_forward_worker_when_scanner_autostart_is_disabled(self) -> None:
        from app import main as app_main

        events: list[str] = []
        fake_app = SimpleNamespace(state=SimpleNamespace())
        FakeScannerRunner.instances = []

        with (
            patch("app.main.ScannerRunner", FakeScannerRunner),
            patch("app.main.ExchangeInstrumentRuleSyncRunner", _worker_factory("instrument", events)),
            patch("app.main.DerivativeSnapshotSyncRunner", _worker_factory("derivative", events)),
            patch("app.main.OrderbookSnapshotWorker", _worker_factory("orderbook", events)),
            patch("app.main.SignalExpiryWorker", _worker_factory("expiry", events)),
            patch("app.main.RealPositionSyncWorker", _worker_factory("positions", events)),
            patch("app.main.BybitRealPositionSyncClient", object),
            patch("app.main._scanner_enabled", return_value=False),
            patch("app.main._instrument_rule_sync_enabled", return_value=False),
            patch("app.main._derivative_snapshot_sync_enabled", return_value=False),
            patch("app.main._orderbook_snapshot_sync_enabled", return_value=False),
            patch("app.main._real_position_sync_enabled", return_value=False),
            patch("app.main.warn_if_migrations_outdated", return_value=None),
            patch("app.main.realtime_gateway", FakeRealtimeGateway(events)),
            patch("app.main.close_clickhouse_client", return_value=None),
            patch("app.main.close_redis_client", return_value=None),
            patch("app.main.dispose_database_engine", return_value=None),
        ):
            async with app_main.lifespan(fake_app):  # type: ignore[arg-type]
                self.assertIsNone(fake_app.state.forward_strategy_test_worker)
                self.assertIsNone(FakeScannerRunner.instances[0].forward_strategy_tests)
                self.assertFalse(FakeScannerRunner.instances[0].started)

            self.assertLess(
                events.index("scanner.stop"),
                events.index("realtime.stop"),
            )

    async def test_health_reports_no_in_app_forward_strategy_test_worker(self) -> None:
        from app import main as app_main

        app_main.app.state.forward_strategy_test_worker = None

        try:
            with patch("app.main.get_storage_health", return_value={"status": "ok"}):
                status = await app_main.health()
        finally:
            app_main.app.state._state.pop("forward_strategy_test_worker", None)

        self.assertFalse(status["forward_strategy_test_running"])
        self.assertFalse(status["forward_strategy_test_stopping"])
        self.assertEqual(status["forward_strategy_test_last_result"], {})


class FakeScannerRunner:
    instances: list["FakeScannerRunner"] = []

    def __init__(self, *, forward_strategy_tests: object | None = None) -> None:
        self.forward_strategy_tests = forward_strategy_tests
        self.started = False
        self.instances.append(self)

    @property
    def is_running(self) -> bool:
        return self.started

    @property
    def is_stopping(self) -> bool:
        return False

    @property
    def scanner_status(self) -> dict[str, object]:
        return {}

    @property
    def processed_signals(self) -> int:
        return 0

    def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        _wiring_events().append("scanner.stop")


class FakeRealtimeGateway:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        _set_wiring_events(events)

    def start_broker_bridge(self) -> None:
        self._events.append("realtime.start")

    async def stop_broker_bridge(self) -> None:
        self._events.append("realtime.stop")


class _NoopWorker:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events
        self.started = False
        self.last_result: dict[str, object] = {}

    @property
    def is_running(self) -> bool:
        return self.started

    def start(self) -> None:
        self.started = True
        self._events.append(f"{self._name}.start")

    async def stop(self) -> None:
        self._events.append(f"{self._name}.stop")


def _worker_factory(name: str, events: list[str]) -> type[_NoopWorker]:
    class Worker(_NoopWorker):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(name, events)

    return Worker


_WIRING_EVENTS: list[str] = []


def _set_wiring_events(events: list[str]) -> None:
    global _WIRING_EVENTS
    _WIRING_EVENTS = events


def _wiring_events() -> list[str]:
    return _WIRING_EVENTS


class FakeRadarConfigService:
    def __init__(self) -> None:
        self.truncate_requested = False

    def selected_timeframes(self) -> list[str]:
        return ["1m"]

    def scanner_universe(self, *, truncate_over_limit: bool = False) -> ScannerUniverse:
        self.truncate_requested = truncate_over_limit
        if not truncate_over_limit:
            return ScannerUniverse(
                pairs=(("bybit", "BTCUSDT"), ("bybit", "ETHUSDT"), ("bybit", "HYPEUSDT")),
                source="explicit pairs",
                max_pairs=2,
                truncated=False,
                warning=None,
                estimated_strategy_checks=6,
            )
        return ScannerUniverse(
            pairs=(("bybit", "BTCUSDT"), ("bybit", "ETHUSDT")),
            source="explicit pairs",
            max_pairs=2,
            truncated=True,
            warning="Scanner universe has 100 pairs, max_scanner_pairs=2. Universe was truncated to 2 pairs.",
            estimated_strategy_checks=4,
        )

    def scanner_subscription_hash(self, universe: ScannerUniverse | None = None) -> str:
        return "hash-truncated"

    def strategy_config_hash(self) -> str:
        return "strategy-hash"


if __name__ == "__main__":
    unittest.main()
