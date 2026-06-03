import unittest
from datetime import datetime, timezone
from uuid import UUID

from app.schemas.exchange_connection import ExchangeFeeRateResponse
from app.schemas.user import RiskManagementSettings
from app.services.risk_fee_rate import RiskFeeRateService


class _FeeProvider:
    def __init__(self, rates=None, exc: Exception | None = None) -> None:
        self.rates = rates or []
        self.exc = exc
        self.calls = []

    def get_fee_rates_for_user(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return self.rates


class RiskFeeRateServiceTest(unittest.TestCase):
    def test_resolves_cached_taker_fee_for_exchange_based_risk(self) -> None:
        provider = _FeeProvider(
            rates=[
                ExchangeFeeRateResponse(
                    connection_id=UUID("00000000-0000-0000-0000-000000000001"),
                    exchange_code="bybit",
                    account_type="linear",
                    category="linear",
                    symbol="BTCUSDT",
                    maker_fee_rate=0.0002,
                    taker_fee_rate=0.00055,
                    source="cache",
                    fetched_at=datetime.now(timezone.utc),
                )
            ]
        )
        service = RiskFeeRateService(provider=provider, fallback_fee_rate=0.001)

        snapshot = service.resolve(
            user_id="demo_user",
            exchange="bybit",
            mode="virtual",
            instrument_type="futures",
            symbol="BTCUSDT",
            risk_settings=RiskManagementSettings(),
            requested_fee_rate=0,
        )

        self.assertEqual(snapshot.fee_rate, 0.00055)
        self.assertEqual(snapshot.source, "cache")
        self.assertEqual(snapshot.warnings, ())
        self.assertEqual(provider.calls[0]["category"], "linear")
        self.assertEqual(provider.calls[0]["symbol"], "BTCUSDT")

    def test_uses_conservative_fallback_with_warning_when_cache_unavailable(self) -> None:
        service = RiskFeeRateService(provider=_FeeProvider(exc=ValueError("no credentials")), fallback_fee_rate=0.001)

        snapshot = service.resolve(
            user_id="demo_user",
            exchange="bybit",
            mode="real",
            instrument_type="futures",
            symbol="ETHUSDT",
            risk_settings=RiskManagementSettings(),
            requested_fee_rate=0.0003,
        )

        self.assertEqual(snapshot.fee_rate, 0.001)
        self.assertEqual(snapshot.source, "conservative_fallback")
        self.assertTrue(snapshot.warnings)

    def test_manual_virtual_fee_model_uses_request_fee(self) -> None:
        service = RiskFeeRateService(provider=_FeeProvider(), fallback_fee_rate=0.001)
        settings = RiskManagementSettings(virtual_fee_model="manual")

        snapshot = service.resolve(
            user_id="demo_user",
            exchange="bybit",
            mode="virtual",
            instrument_type="spot",
            symbol="BTCUSDT",
            risk_settings=settings,
            requested_fee_rate=0.0004,
        )

        self.assertEqual(snapshot.fee_rate, 0.0004)
        self.assertEqual(snapshot.source, "manual_request")


if __name__ == "__main__":
    unittest.main()
