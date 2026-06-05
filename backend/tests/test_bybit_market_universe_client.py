import json
import unittest
import urllib.parse
from decimal import Decimal

from app.exchanges.bybit import fetch_bybit_instruments_info, fetch_bybit_market_universe


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class BybitMarketUniverseClientTest(unittest.TestCase):
    def test_fetch_instruments_info_paginates_linear_instruments(self) -> None:
        captured_queries: list[dict[str, list[str]]] = []

        def fake_urlopen(url, timeout: int):
            self.assertEqual(timeout, 4.0)
            parsed = urllib.parse.urlparse(url)
            self.assertEqual(parsed.path, "/v5/market/instruments-info")
            query = urllib.parse.parse_qs(parsed.query)
            captured_queries.append(query)
            self.assertEqual(query["category"], ["linear"])
            self.assertEqual(query["limit"], ["1000"])
            if "cursor" not in query:
                return _Response(
                    {
                        "retCode": 0,
                        "retMsg": "OK",
                        "result": {
                            "nextPageCursor": "page-2",
                            "list": [
                                _instrument("BTCUSDT"),
                                _instrument("ETHUSDT"),
                            ],
                        },
                    }
                )
            self.assertEqual(query["cursor"], ["page-2"])
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "nextPageCursor": "",
                        "list": [_instrument("SOLUSDT")],
                    },
                }
            )

        instruments = fetch_bybit_instruments_info(urlopen=fake_urlopen)

        self.assertEqual([instrument.symbol for instrument in instruments], ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        self.assertEqual(len(captured_queries), 2)
        self.assertNotIn("cursor", captured_queries[0])
        self.assertEqual(captured_queries[1]["cursor"], ["page-2"])

    def test_fetch_instruments_info_filters_quote_and_status(self) -> None:
        def fake_urlopen(url, timeout: int):
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            _instrument("BTCUSDT", quote_coin="USDT", status="Trading"),
                            _instrument("ETHUSDT", quote_coin="USDT", status="PreLaunch"),
                            _instrument("XRPUSDC", quote_coin="USDC", status="Trading"),
                        ]
                    },
                }
            )

        instruments = fetch_bybit_instruments_info(
            quote_coin="USDT",
            status="Trading",
            urlopen=fake_urlopen,
        )
        all_instruments = fetch_bybit_instruments_info(
            quote_coin=None,
            status=None,
            urlopen=fake_urlopen,
        )

        self.assertEqual([instrument.symbol for instrument in instruments], ["BTCUSDT"])
        self.assertEqual([instrument.symbol for instrument in all_instruments], ["BTCUSDT", "ETHUSDT", "XRPUSDC"])
        self.assertEqual(instruments[0].price_filter, {"tickSize": "0.1"})
        self.assertEqual(instruments[0].raw_payload["symbol"], "BTCUSDT")

    def test_fetch_market_universe_merges_tickers_and_calculates_spread(self) -> None:
        def fake_urlopen(url, timeout: int):
            parsed = urllib.parse.urlparse(url)
            if parsed.path == "/v5/market/instruments-info":
                return _Response(
                    {
                        "retCode": 0,
                        "retMsg": "OK",
                        "result": {
                            "list": [
                                _instrument("BTCUSDT", base_coin="BTC"),
                                _instrument("ETHUSDT", base_coin="ETH"),
                            ]
                        },
                    }
                )
            if parsed.path == "/v5/market/tickers":
                return _Response(
                    {
                        "retCode": 0,
                        "retMsg": "OK",
                        "result": {
                            "list": [
                                _ticker(
                                    "ETHUSDT",
                                    bid="1999",
                                    ask="2001",
                                    turnover="250000",
                                    volume="125",
                                    last="2000",
                                    mark="2000.5",
                                    funding="0.0002",
                                ),
                                _ticker(
                                    "BTCUSDT",
                                    bid="99",
                                    ask="101",
                                    turnover="1000000",
                                    volume="10000",
                                    last="100.5",
                                    mark="100.25",
                                    funding="0.0001",
                                ),
                            ]
                        },
                    }
                )
            raise AssertionError(f"unexpected URL: {url}")

        universe = fetch_bybit_market_universe(urlopen=fake_urlopen)

        self.assertEqual([instrument.symbol for instrument in universe], ["BTCUSDT", "ETHUSDT"])
        btc = universe[0]
        self.assertEqual(btc.turnover_rank, 1)
        self.assertEqual(btc.base_coin, "BTC")
        self.assertEqual(btc.turnover_24h, Decimal("1000000"))
        self.assertEqual(btc.volume_24h, Decimal("10000"))
        self.assertEqual(btc.last_price, Decimal("100.5"))
        self.assertEqual(btc.mark_price, Decimal("100.25"))
        self.assertEqual(btc.bid1_price, Decimal("99"))
        self.assertEqual(btc.ask1_price, Decimal("101"))
        self.assertEqual(btc.spread_bps, Decimal("200"))
        self.assertEqual(btc.funding_rate, Decimal("0.0001"))
        self.assertIsNotNone(btc.ticker)

    def test_fetch_market_universe_keeps_instrument_without_ticker(self) -> None:
        def fake_urlopen(url, timeout: int):
            parsed = urllib.parse.urlparse(url)
            if parsed.path == "/v5/market/instruments-info":
                return _Response(
                    {
                        "retCode": 0,
                        "retMsg": "OK",
                        "result": {
                            "list": [
                                _instrument("BTCUSDT", base_coin="BTC"),
                                _instrument("DOGEUSDT", base_coin="DOGE"),
                            ]
                        },
                    }
                )
            if parsed.path == "/v5/market/tickers":
                return _Response(
                    {
                        "retCode": 0,
                        "retMsg": "OK",
                        "result": {"list": [_ticker("BTCUSDT", turnover="1000")]},
                    }
                )
            raise AssertionError(f"unexpected URL: {url}")

        universe = fetch_bybit_market_universe(urlopen=fake_urlopen)
        doge = next(instrument for instrument in universe if instrument.symbol == "DOGEUSDT")

        self.assertEqual(len(universe), 2)
        self.assertIsNone(doge.ticker)
        self.assertIsNone(doge.turnover_24h)
        self.assertIsNone(doge.bid1_price)
        self.assertIsNone(doge.ask1_price)
        self.assertIsNone(doge.spread_bps)
        self.assertIsNone(doge.turnover_rank)


def _instrument(
    symbol: str,
    *,
    base_coin: str | None = None,
    quote_coin: str = "USDT",
    status: str = "Trading",
) -> dict:
    return {
        "symbol": symbol,
        "status": status,
        "baseCoin": base_coin or symbol.removesuffix(quote_coin),
        "quoteCoin": quote_coin,
        "contractType": "LinearPerpetual",
        "launchTime": "1670601600000",
        "deliveryTime": "0",
        "priceFilter": {"tickSize": "0.1"},
        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"},
        "leverageFilter": {"maxLeverage": "100"},
    }


def _ticker(
    symbol: str,
    *,
    bid: str = "99",
    ask: str = "101",
    turnover: str = "1000",
    volume: str = "10",
    last: str = "100",
    mark: str = "100",
    funding: str = "0.0001",
) -> dict:
    return {
        "symbol": symbol,
        "bid1Price": bid,
        "ask1Price": ask,
        "turnover24h": turnover,
        "volume24h": volume,
        "lastPrice": last,
        "markPrice": mark,
        "fundingRate": funding,
    }


if __name__ == "__main__":
    unittest.main()
