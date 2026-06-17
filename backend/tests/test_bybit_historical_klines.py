from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.exchanges.bybit import fetch_bybit_klines_range


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class BybitHistoricalKlinesTest(unittest.TestCase):
    def test_fetch_range_requests_bybit_window_and_filters_open_candle(self) -> None:
        captured_urls: list[str] = []

        def fake_urlopen(url: str, timeout: float) -> _Response:
            captured_urls.append(url)
            self.assertEqual(timeout, 4.0)
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            ["1780316100000", "101", "106", "96", "102", "11"],
                            ["1780316100000", "101", "106", "96", "102", "11"],
                            ["1780315200000", "100", "105", "95", "101", "10"],
                            ["1780317000000", "102", "107", "97", "103", "12"],
                        ]
                    },
                }
            )

        candles = fetch_bybit_klines_range(
            symbol="PEPEUSDT",
            timeframe="15m",
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 12, 45, tzinfo=timezone.utc),
            limit=1000,
            urlopen=fake_urlopen,
            now=datetime(2026, 6, 1, 12, 44, tzinfo=timezone.utc),
        )

        request = urlparse(captured_urls[0])
        params = parse_qs(request.query)
        self.assertEqual(request.path, "/v5/market/kline")
        self.assertEqual(params["category"], ["linear"])
        self.assertEqual(params["symbol"], ["1000PEPEUSDT"])
        self.assertEqual(params["interval"], ["15"])
        self.assertEqual(params["start"], ["1780315200000"])
        self.assertEqual(params["end"], ["1780316999999"])
        self.assertEqual(params["limit"], ["1000"])
        self.assertEqual([candle.open_time for candle in candles], [1780315200000, 1780316100000])
        self.assertTrue(all(candle.is_closed for candle in candles))
        self.assertTrue(all(candle.symbol == "1000PEPEUSDT" for candle in candles))

    def test_fetch_range_pages_by_limit_sized_chunks(self) -> None:
        captured_params: list[dict[str, list[str]]] = []

        def fake_urlopen(url: str, timeout: float) -> _Response:
            _ = timeout
            captured_params.append(parse_qs(urlparse(url).query))
            start = int(captured_params[-1]["start"][0])
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {"list": [[str(start), "100", "105", "95", "101", "10"]]},
                }
            )

        candles = fetch_bybit_klines_range(
            symbol="BTCUSDT",
            timeframe="15m",
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 12, 45, tzinfo=timezone.utc),
            limit=1,
            urlopen=fake_urlopen,
            now=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(captured_params), 3)
        self.assertEqual([params["start"][0] for params in captured_params], [
            "1780315200000",
            "1780316100000",
            "1780317000000",
        ])
        self.assertEqual([candle.open_time for candle in candles], [
            1780315200000,
            1780316100000,
            1780317000000,
        ])


if __name__ == "__main__":
    unittest.main()
