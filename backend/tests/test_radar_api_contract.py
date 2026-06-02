import unittest

from app.api.v1.radar import get_radar


class _FakeSignalService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    def list_open_signals_for_radar(
        self,
        *,
        user_id: str = "demo_user",
        radar_display_mode: str | None = None,
    ) -> list:
        self.calls.append(
            {
                "user_id": user_id,
                "radar_display_mode": radar_display_mode,
            }
        )
        return []


class RadarApiContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_radar_endpoint_passes_display_mode_override_to_service(self) -> None:
        fake_service = _FakeSignalService()

        import app.api.v1.radar as radar_api

        original_service = radar_api.signal_service
        radar_api.signal_service = fake_service
        try:
            response = await get_radar(
                user_id="demo_user",
                radar_display_mode="execution_ready",
            )
        finally:
            radar_api.signal_service = original_service

        self.assertEqual(response.signals, [])
        self.assertEqual(
            fake_service.calls,
            [{"user_id": "demo_user", "radar_display_mode": "execution_ready"}],
        )


if __name__ == "__main__":
    unittest.main()
