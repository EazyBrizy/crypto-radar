import hashlib
import hmac
import json
import unittest

from app.exchanges.bybit import (
    fetch_bybit_fee_rates,
    fetch_bybit_instrument_rules,
    fetch_bybit_orderbook,
    fetch_bybit_positions,
    fetch_bybit_tickers,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class BybitFeeRateClientTest(unittest.TestCase):
    def test_fetch_fee_rates_signs_v5_request(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout: int):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            {
                                "symbol": "ETHUSDT",
                                "makerFeeRate": "0.0001",
                                "takerFeeRate": "0.0006",
                            }
                        ]
                    },
                }
            )

        rates = fetch_bybit_fee_rates(
            api_key="api_key",
            api_secret="api_secret",
            category="linear",
            symbol="ETHUSDT",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )

        request = captured["request"]
        query = "category=linear&symbol=ETHUSDT"
        expected_signature = hmac.new(
            b"api_secret",
            f"1676360412362api_key5000{query}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(request.full_url, f"https://api.bybit.com/v5/account/fee-rate?{query}")
        self.assertEqual(request.get_header("X-bapi-api-key"), "api_key")
        self.assertEqual(request.get_header("X-bapi-timestamp"), "1676360412362")
        self.assertEqual(request.get_header("X-bapi-recv-window"), "5000")
        self.assertEqual(request.get_header("X-bapi-sign"), expected_signature)
        self.assertEqual(captured["timeout"], 10)
        self.assertEqual(rates[0].symbol, "ETHUSDT")
        self.assertEqual(rates[0].maker_fee_rate, 0.0001)
        self.assertEqual(rates[0].taker_fee_rate, 0.0006)

    def test_fetch_instrument_rules_maps_filters_for_risk_gate(self) -> None:
        def fake_urlopen(url, timeout: int):
            self.assertIn("/v5/market/instruments-info?", url)
            self.assertIn("category=linear", url)
            self.assertEqual(timeout, 10)
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "lotSizeFilter": {
                                    "minOrderQty": "0.001",
                                    "maxOrderQty": "100",
                                    "qtyStep": "0.001",
                                    "minNotionalValue": "5",
                                },
                                "priceFilter": {"tickSize": "0.1"},
                                "leverageFilter": {"maxLeverage": "100.00"},
                                "fundingInterval": "480",
                            }
                        ]
                    },
                }
            )

        rules = fetch_bybit_instrument_rules(
            category="linear",
            symbol="BTCUSDT",
            urlopen=fake_urlopen,
        )

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].symbol, "BTCUSDT")
        self.assertEqual(rules[0].min_order_size, 0.001)
        self.assertEqual(rules[0].max_order_size, 100)
        self.assertEqual(rules[0].min_notional, 5)
        self.assertEqual(rules[0].qty_step, 0.001)
        self.assertEqual(rules[0].tick_size, 0.1)
        self.assertEqual(rules[0].max_leverage, 100)
        self.assertEqual(rules[0].funding_interval_minutes, 480)

    def test_fetch_tickers_maps_bid_ask_mark_and_funding(self) -> None:
        def fake_urlopen(url, timeout: int):
            self.assertIn("/v5/market/tickers?", url)
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "bid1Price": "50000",
                                "ask1Price": "50001",
                                "markPrice": "50000.5",
                                "fundingRate": "0.0001",
                            }
                        ]
                    },
                }
            )

        tickers = fetch_bybit_tickers(symbol="BTCUSDT", urlopen=fake_urlopen)

        self.assertEqual(tickers[0].bid1_price, 50000)
        self.assertEqual(tickers[0].ask1_price, 50001)
        self.assertEqual(tickers[0].mark_price, 50000.5)
        self.assertEqual(tickers[0].funding_rate, 0.0001)

    def test_fetch_orderbook_maps_depth_levels(self) -> None:
        def fake_urlopen(url, timeout: int):
            self.assertIn("/v5/market/orderbook?", url)
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "s": "BTCUSDT",
                        "b": [["50000", "1.2"]],
                        "a": [["50001", "0.8"]],
                    },
                }
            )

        book = fetch_bybit_orderbook(symbol="BTCUSDT", urlopen=fake_urlopen)

        self.assertEqual(book.bids, [(50000, 1.2)])
        self.assertEqual(book.asks, [(50001, 0.8)])

    def test_fetch_positions_signs_v5_request_and_maps_liquidation(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout: int):
            captured["request"] = request
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "side": "Buy",
                                "size": "0.1",
                                "liqPrice": "45000",
                            }
                        ]
                    },
                }
            )

        positions = fetch_bybit_positions(
            api_key="api_key",
            api_secret="api_secret",
            category="linear",
            symbol="BTCUSDT",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )

        self.assertIn("/v5/position/list?category=linear&symbol=BTCUSDT", captured["request"].full_url)
        self.assertEqual(positions[0].liquidation_price, 45000)


if __name__ == "__main__":
    unittest.main()
