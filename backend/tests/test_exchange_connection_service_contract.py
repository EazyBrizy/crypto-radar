import unittest
from uuid import UUID

from app.schemas.exchange_connection import ExchangeConnectionResponse
from app.services.exchange_connection_service import StubSecretRefProvider


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

    def test_response_exposes_key_ref_not_raw_secret_fields(self) -> None:
        fields = set(ExchangeConnectionResponse.model_fields)

        self.assertIn("key_ref", fields)
        self.assertNotIn("api_key", fields)
        self.assertNotIn("api_secret", fields)
        self.assertNotIn("api_passphrase", fields)


if __name__ == "__main__":
    unittest.main()
