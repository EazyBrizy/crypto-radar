import unittest
from uuid import UUID

from app.schemas.exchange_connection import (
    ExchangeConnectionCreateRequest,
    ExchangeConnectionResponse,
    ExchangeFeeRateResponse,
)
from app.services.exchange_connection_service import ExchangeConnectionService, StubSecretRefProvider


class ExchangeConnectionServiceContractTest(unittest.TestCase):
    def test_stub_secret_provider_returns_key_ref_without_raw_credentials(self) -> None:
        provider = StubSecretRefProvider()

        key_ref = provider.store_exchange_credentials(
            user_id=UUID("ba520631-d035-4f95-a4c0-3b40553dd524"),
            exchange_code="bybit",
            label="Main spot",
            credentials={
                "api_key": "public_api_key_value",
                "api_secret": "super_secret_value",
                "api_passphrase": "passphrase_value",
            },
        )

        self.assertTrue(key_ref.startswith("vault://stub/exchange/"))
        self.assertNotIn("public_api_key_value", key_ref)
        self.assertNotIn("super_secret_value", key_ref)
        self.assertNotIn("passphrase_value", key_ref)
        self.assertEqual(
            provider.load_exchange_credentials(key_ref),
            {
                "api_key": "public_api_key_value",
                "api_secret": "super_secret_value",
                "api_passphrase": "passphrase_value",
            },
        )

    def test_response_exposes_key_ref_not_raw_secret_fields(self) -> None:
        fields = set(ExchangeConnectionResponse.model_fields)

        self.assertIn("key_ref", fields)
        self.assertNotIn("api_key", fields)
        self.assertNotIn("api_secret", fields)
        self.assertNotIn("api_passphrase", fields)

    def test_service_loads_credentials_through_secret_provider_boundary(self) -> None:
        provider = StubSecretRefProvider()
        service = ExchangeConnectionService(secret_provider=provider)
        key_ref = provider.store_exchange_credentials(
            user_id=UUID("ba520631-d035-4f95-a4c0-3b40553dd524"),
            exchange_code="bybit",
            label="Main",
            credentials={"api_key": "public", "api_secret": "private"},
        )

        self.assertEqual(
            service.load_credentials(key_ref),
            {"api_key": "public", "api_secret": "private"},
        )

    def test_fee_rate_response_exposes_maker_and_taker_rates(self) -> None:
        fields = set(ExchangeFeeRateResponse.model_fields)

        self.assertIn("maker_fee_rate", fields)
        self.assertIn("taker_fee_rate", fields)
        self.assertIn("account_type", fields)
        self.assertIn("source", fields)

    def test_create_request_accepts_staged_real_trading_modes(self) -> None:
        for mode in (
            "disabled",
            "dry_run",
            "dry_run_orders",
            "testnet_real_orders",
            "mainnet_small_size",
            "mainnet_scaled",
            "live",
        ):
            request = ExchangeConnectionCreateRequest(
                exchange_code="bybit",
                label=f"Bybit {mode}",
                api_key="key",
                api_secret="secret",
                order_placement_mode=mode,
            )

            self.assertEqual(request.order_placement_mode, mode)


if __name__ == "__main__":
    unittest.main()
