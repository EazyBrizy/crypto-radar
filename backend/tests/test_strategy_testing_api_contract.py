from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.router import api_router
from app.main import app
from app.services.strategy_testing.schemas import StrategyTestPair, StrategyTestRunRequest


class StrategyTestingApiContractTest(unittest.TestCase):
    def test_run_request_accepts_matrix_inputs(self) -> None:
        request = _request()

        self.assertEqual(
            request.strategies,
            [
                "trend_pullback_continuation",
                "volatility_squeeze_breakout",
                "liquidity_sweep_reversal",
            ],
        )
        self.assertEqual(len(request.pairs), 2)
        self.assertEqual(request.pairs[0].exchange, "bybit")
        self.assertEqual(request.pairs[0].symbol, "BTCUSDT")
        self.assertEqual(request.timeframes, ["1h", "4h"])

    def test_end_at_must_be_after_start_at(self) -> None:
        request = _request()

        with self.assertRaises(ValidationError):
            StrategyTestRunRequest(
                **request.model_dump(exclude={"end_at"}),
                end_at=request.start_at,
            )

    def test_duplicate_strategies_and_timeframes_are_deduped(self) -> None:
        now = _now()

        request = StrategyTestRunRequest(
            strategies=[" breakout ", "breakout", " trend_pullback_continuation "],
            pairs=[StrategyTestPair(exchange="bybit", symbol="btcusdt")],
            timeframes=[" 1h ", "1h", "4h"],
            start_at=now,
            end_at=now + timedelta(days=1),
        )

        self.assertEqual(request.strategies, ["breakout", "trend_pullback_continuation"])
        self.assertEqual(request.timeframes, ["1h", "4h"])

    def test_tags_always_include_backtest(self) -> None:
        request = _request(tags=["research"])

        self.assertEqual(request.tags, ["research", "backtest"])

    def test_post_runs_accepts_matrix_request(self) -> None:
        client = TestClient(app)

        response = client.post("/api/v1/strategy-tests/runs", json=_payload())

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "queued")
        self.assertIn("run_id", data)
        self.assertEqual(
            data["requested_matrix"]["strategies"],
            [
                "trend_pullback_continuation",
                "volatility_squeeze_breakout",
                "liquidity_sweep_reversal",
            ],
        )
        self.assertEqual(
            data["requested_matrix"]["pairs"],
            [
                {"exchange": "bybit", "symbol": "BTCUSDT"},
                {"exchange": "binance", "symbol": "ETHUSDT"},
            ],
        )
        self.assertEqual(data["requested_matrix"]["timeframes"], ["1h", "4h"])
        self.assertEqual(data["requested_matrix"]["scenario_count"], 12)

    def test_existing_backtests_route_remains_registered(self) -> None:
        route_paths = {route.path for route in api_router.routes}

        self.assertIn("/api/v1/backtests/run", route_paths)
        self.assertIn("/api/v1/backtests/results", route_paths)


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _request(tags: list[str] | None = None) -> StrategyTestRunRequest:
    now = _now()
    request_kwargs = {
        "strategies": [
            "trend_pullback_continuation",
            "volatility_squeeze_breakout",
            "liquidity_sweep_reversal",
        ],
        "pairs": [
            StrategyTestPair(exchange=" BYBIT ", symbol=" btcusdt "),
            StrategyTestPair(exchange="BINANCE", symbol="ethusdt"),
        ],
        "timeframes": ["1h", "4h"],
        "start_at": now,
        "end_at": now + timedelta(days=30),
        "initial_capital": Decimal("1000"),
    }
    if tags is not None:
        request_kwargs["tags"] = tags
    return StrategyTestRunRequest(**request_kwargs)


def _payload() -> dict[str, object]:
    now = _now()
    return {
        "strategies": [
            "trend_pullback_continuation",
            "volatility_squeeze_breakout",
            "liquidity_sweep_reversal",
        ],
        "pairs": [
            {"exchange": " BYBIT ", "symbol": " btcusdt "},
            {"exchange": "binance", "symbol": "ETHUSDT"},
        ],
        "timeframes": ["1h", "4h"],
        "start_at": now.isoformat(),
        "end_at": (now + timedelta(days=30)).isoformat(),
        "mode": "research_virtual",
        "initial_capital": "1000",
        "fee_rate": "0.001",
        "slippage_bps": "0",
        "params": {"risk": "standard"},
    }


if __name__ == "__main__":
    unittest.main()
