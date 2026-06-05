import hashlib
import hmac
import json
import unittest
import urllib.parse
from decimal import Decimal

from app.exchanges.bybit import BybitApiError, fetch_bybit_wallet_balance


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class BybitWalletBalanceClientTest(unittest.TestCase):
    def test_fetch_wallet_balance_signs_request_and_parses_totals(self) -> None:
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
                                "accountType": "UNIFIED",
                                "totalEquity": "100.25",
                                "totalWalletBalance": "99.75",
                                "totalMarginBalance": "100.00",
                                "totalAvailableBalance": "80.5",
                                "totalInitialMargin": "10.25",
                                "totalMaintenanceMargin": "5.125",
                                "totalPerpUPL": "0.5",
                                "coin": [
                                    {
                                        "coin": "USDT",
                                        "equity": "100.25",
                                        "usdValue": "100.25",
                                        "walletBalance": "99.75",
                                        "availableToWithdraw": "80.5",
                                        "locked": "1.25",
                                        "borrowAmount": "0",
                                        "accruedInterest": "0.01",
                                        "totalOrderIM": "2",
                                        "totalPositionIM": "8.25",
                                        "totalPositionMM": "3.5",
                                        "unrealisedPnl": "0.5",
                                    }
                                ],
                            }
                        ]
                    },
                }
            )

        balance = fetch_bybit_wallet_balance(
            api_key="api_key",
            api_secret="api_secret",
            account_type="UNIFIED",
            coin="USDT",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )

        request = captured["request"]
        query = "accountType=UNIFIED&coin=USDT"
        expected_signature = hmac.new(
            b"api_secret",
            f"1676360412362api_key5000{query}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(
            request.full_url,
            f"https://api.bybit.com/v5/account/wallet-balance?{query}",
        )
        self.assertEqual(request.get_header("X-bapi-api-key"), "api_key")
        self.assertEqual(request.get_header("X-bapi-timestamp"), "1676360412362")
        self.assertEqual(request.get_header("X-bapi-recv-window"), "5000")
        self.assertEqual(request.get_header("X-bapi-sign"), expected_signature)
        self.assertEqual(captured["timeout"], 4.0)
        self.assertEqual(balance.account_type, "UNIFIED")
        self.assertEqual(balance.total_equity, Decimal("100.25"))
        self.assertEqual(balance.total_wallet_balance, Decimal("99.75"))
        self.assertEqual(balance.total_margin_balance, Decimal("100.00"))
        self.assertEqual(balance.total_available_balance, Decimal("80.5"))
        self.assertEqual(balance.total_initial_margin, Decimal("10.25"))
        self.assertEqual(balance.total_maintenance_margin, Decimal("5.125"))
        self.assertEqual(balance.total_perp_upl, Decimal("0.5"))

    def test_fetch_wallet_balance_parses_coin_entries(self) -> None:
        def fake_urlopen(request, timeout: int):
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            {
                                "accountType": "UNIFIED",
                                "coin": [
                                    {
                                        "coin": "USDT",
                                        "equity": "20",
                                        "usdValue": "20",
                                        "walletBalance": "18",
                                        "availableToWithdraw": "17",
                                        "locked": "1",
                                        "borrowAmount": "0",
                                        "accruedInterest": "0",
                                        "totalOrderIM": "0.25",
                                        "totalPositionIM": "0.75",
                                        "totalPositionMM": "0.125",
                                        "unrealisedPnl": "-0.5",
                                    }
                                ],
                            }
                        ]
                    },
                }
            )

        balance = fetch_bybit_wallet_balance(
            api_key="api_key",
            api_secret="api_secret",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )

        coin = balance.coins[0]
        self.assertEqual(coin.coin, "USDT")
        self.assertEqual(coin.equity, Decimal("20"))
        self.assertEqual(coin.usd_value, Decimal("20"))
        self.assertEqual(coin.wallet_balance, Decimal("18"))
        self.assertEqual(coin.available_to_withdraw, Decimal("17"))
        self.assertEqual(coin.locked, Decimal("1"))
        self.assertEqual(coin.borrow_amount, Decimal("0"))
        self.assertEqual(coin.accrued_interest, Decimal("0"))
        self.assertEqual(coin.total_order_im, Decimal("0.25"))
        self.assertEqual(coin.total_position_im, Decimal("0.75"))
        self.assertEqual(coin.total_position_mm, Decimal("0.125"))
        self.assertEqual(coin.unrealised_pnl, Decimal("-0.5"))
        self.assertEqual(coin.raw_payload["coin"], "USDT")

    def test_fetch_wallet_balance_empty_strings_become_none(self) -> None:
        def fake_urlopen(request, timeout: int):
            return _Response(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            {
                                "accountType": "UNIFIED",
                                "totalEquity": "",
                                "totalWalletBalance": "",
                                "totalMarginBalance": "",
                                "totalAvailableBalance": "",
                                "totalInitialMargin": "",
                                "totalMaintenanceMargin": "",
                                "totalPerpUPL": "",
                                "coin": [
                                    {
                                        "coin": "USDT",
                                        "equity": "",
                                        "usdValue": "",
                                        "walletBalance": "",
                                        "availableToWithdraw": "",
                                        "locked": "",
                                        "borrowAmount": "",
                                        "accruedInterest": "",
                                        "totalOrderIM": "",
                                        "totalPositionIM": "",
                                        "totalPositionMM": "",
                                        "unrealisedPnl": "",
                                    }
                                ],
                            }
                        ]
                    },
                }
            )

        balance = fetch_bybit_wallet_balance(
            api_key="api_key",
            api_secret="api_secret",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )

        coin = balance.coins[0]
        self.assertIsNone(balance.total_equity)
        self.assertIsNone(balance.total_wallet_balance)
        self.assertIsNone(balance.total_margin_balance)
        self.assertIsNone(balance.total_available_balance)
        self.assertIsNone(balance.total_initial_margin)
        self.assertIsNone(balance.total_maintenance_margin)
        self.assertIsNone(balance.total_perp_upl)
        self.assertIsNone(coin.equity)
        self.assertIsNone(coin.usd_value)
        self.assertIsNone(coin.wallet_balance)
        self.assertIsNone(coin.available_to_withdraw)
        self.assertIsNone(coin.locked)
        self.assertIsNone(coin.borrow_amount)
        self.assertIsNone(coin.accrued_interest)
        self.assertIsNone(coin.total_order_im)
        self.assertIsNone(coin.total_position_im)
        self.assertIsNone(coin.total_position_mm)
        self.assertIsNone(coin.unrealised_pnl)

    def test_fetch_wallet_balance_non_zero_ret_code_raises_bybit_error(self) -> None:
        def fake_urlopen(request, timeout: int):
            return _Response({"retCode": 10001, "retMsg": "Invalid accountType"})

        with self.assertRaises(BybitApiError):
            fetch_bybit_wallet_balance(
                api_key="api_key",
                api_secret="api_secret",
                timestamp_ms=1_676_360_412_362,
                urlopen=fake_urlopen,
            )

    def test_fetch_wallet_balance_passes_multiple_coin_string(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout: int):
            captured["request"] = request
            return _Response({"retCode": 0, "retMsg": "OK", "result": {"list": []}})

        balance = fetch_bybit_wallet_balance(
            api_key="api_key",
            api_secret="api_secret",
            account_type="UNIFIED",
            coin="USDT,USDC",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )

        parsed_url = urllib.parse.urlparse(captured["request"].full_url)
        query = urllib.parse.parse_qs(parsed_url.query)
        self.assertEqual(parsed_url.path, "/v5/account/wallet-balance")
        self.assertEqual(query["accountType"], ["UNIFIED"])
        self.assertEqual(query["coin"], ["USDT,USDC"])
        self.assertEqual(balance.account_type, "UNIFIED")
        self.assertEqual(balance.coins, ())

    def test_fetch_wallet_balance_omits_empty_coin(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout: int):
            captured["request"] = request
            return _Response({"retCode": 0, "retMsg": "OK", "result": {"list": []}})

        balance = fetch_bybit_wallet_balance(
            api_key="api_key",
            api_secret="api_secret",
            account_type="UNIFIED",
            coin="",
            timestamp_ms=1_676_360_412_362,
            urlopen=fake_urlopen,
        )

        parsed_url = urllib.parse.urlparse(captured["request"].full_url)
        query = urllib.parse.parse_qs(parsed_url.query)
        self.assertEqual(query, {"accountType": ["UNIFIED"]})
        self.assertEqual(balance.total_equity, None)
        self.assertEqual(balance.raw_payload, {"list": []})


if __name__ == "__main__":
    unittest.main()
