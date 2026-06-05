import inspect
import unittest

from app.api.v1.radar import get_radar
from app.schemas.signal import RadarResponse
from starlette.requests import Request


class _FakeRadarService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def list_signals(
        self,
        *,
        user_id: str = "demo_user",
        mode: str | None = None,
        filters=None,
        include_action_state: bool = False,
    ) -> RadarResponse:
        self.calls.append(
            {
                "user_id": user_id,
                "mode": mode,
                "exchange": filters.exchange,
                "symbol": filters.symbol,
                "timeframe": filters.timeframe,
                "include_action_state": include_action_state,
            }
        )
        return RadarResponse(signals=[])


class RadarApiContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_radar_endpoint_passes_query_contract_to_service(self) -> None:
        fake_service = _FakeRadarService()

        import app.api.v1.radar as radar_api

        original_service = radar_api.radar_service
        radar_api.radar_service = fake_service
        try:
            response = await get_radar(
                _request(),
                user_id="demo_user",
                radar_display_mode="execution_ready",
                exchange="bybit",
                symbol="BTCUSDT",
                timeframe="15m",
                include_action_state=True,
            )
        finally:
            radar_api.radar_service = original_service

        self.assertEqual(response.signals, [])
        self.assertEqual(
            fake_service.calls,
            [
                {
                    "user_id": "demo_user",
                    "mode": "execution_ready",
                    "exchange": "bybit",
                    "symbol": "BTCUSDT",
                    "timeframe": "15m",
                    "include_action_state": True,
                }
            ],
        )

    async def test_radar_endpoint_has_no_business_filtering(self) -> None:
        source = inspect.getsource(get_radar)

        self.assertNotIn("list_open_signals", source)
        self.assertNotIn("RiskGate", source)
        self.assertNotIn("if ", source)
        self.assertNotIn("for ", source)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/radar",
            "headers": [],
        }
    )


if __name__ == "__main__":
    unittest.main()
