from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.tools import api_request
from app.tools import strategy_smoke


NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


class StrategySmokeHelperTest(unittest.TestCase):
    def test_historical_payload_uses_small_backend_owned_matrix(self) -> None:
        payload = strategy_smoke.build_historical_run_payload(
            start_at=NOW,
            end_at=NOW + timedelta(hours=2),
            warmup_candles=3,
        )

        self.assertEqual(payload["test_type"], "historical_backtest")
        self.assertEqual(payload["pairs"], [{"exchange": "bybit", "symbol": "BTCUSDT"}])
        self.assertEqual(payload["timeframes"], ["5m", "15m"])
        self.assertEqual(payload["params"]["warmup_candles"], 3)
        self.assertEqual(payload["params"]["rolling_window_candles"], 3)
        self.assertIn("docker_smoke", payload["tags"])

    def test_candle_seed_plan_includes_duplicate_timestamp_per_timeframe(self) -> None:
        plan = strategy_smoke.build_candle_seed_plan(
            start_at=NOW,
            candles_per_timeframe=8,
            warmup_candles=3,
        )

        self.assertEqual(plan.rows_total, 34)
        self.assertEqual(plan.deduped_candles_total, 32)
        self.assertEqual(plan.expected_bars_total, 26)
        self.assertEqual(plan.duplicate_rows_total, 2)
        self.assertEqual(plan.deduped_candles_by_timeframe, {"5m": 24, "15m": 8})
        self.assertEqual({candle.timeframe for candle in plan.candles}, {"5m", "15m"})
        for timeframe, expected_count in (("5m", 24), ("15m", 8)):
            candles = [candle for candle in plan.candles if candle.timeframe == timeframe]
            self.assertEqual(len(candles), expected_count + 1)
            self.assertEqual(len({candle.open_time for candle in candles}), expected_count)
            self.assertTrue(all(candle.is_closed for candle in candles))

    def test_forward_pending_signal_matches_smoke_matrix(self) -> None:
        signal = strategy_smoke.build_forward_pending_signal()

        self.assertEqual(signal.exchange, "bybit")
        self.assertEqual(signal.symbol, "BTCUSDT")
        self.assertEqual(signal.strategy, "trend_pullback_continuation")
        self.assertEqual(signal.timeframe, "15m")
        self.assertIsNotNone(signal.execution_gate)
        assert signal.execution_gate is not None
        self.assertTrue(signal.execution_gate.can_arm_pending)
        self.assertFalse(signal.execution_gate.can_enter_now)

    def test_api_request_uses_backend_container_loopback_and_dev_user(self) -> None:
        response = _UrlopenResponse(b'{"ok":true}')
        with patch.object(api_request.urllib.request, "urlopen", return_value=response) as urlopen:
            result = api_request.request_backend_api(
                method="post",
                path="/api/v1/strategy-tests/runs",
                body='{"test_type":"historical_backtest"}',
                base_url="http://127.0.0.1:8000/",
                user_id="usr_demo",
            )

        self.assertEqual(result, '{"ok":true}')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8000/api/v1/strategy-tests/runs")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, b'{"test_type":"historical_backtest"}')
        self.assertEqual(request.get_header("X-dev-user"), "usr_demo")
        self.assertEqual(request.get_header("Content-type"), "application/json")


class _UrlopenResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_UrlopenResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


if __name__ == "__main__":
    unittest.main()
