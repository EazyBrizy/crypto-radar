from datetime import datetime, timezone
from uuid import UUID
import unittest

from app.api.v1.users import router
from app.schemas.user import UserProfileResponse, UserSettingsPatchRequest


class UserProfileContractTest(unittest.TestCase):
    def test_user_profile_response_exposes_postgres_profile_fields(self) -> None:
        response = UserProfileResponse(
            id=UUID("ba520631-d035-4f95-a4c0-3b40553dd524"),
            email="demo@crypto-radar.local",
            username="demo_user",
            name="Demo Trader",
            display_name="Demo Trader",
            avatar_url=None,
            status="active",
            locale="ru",
            timezone="Europe/Warsaw",
            risk_profile="balanced",
            onboarding_done=True,
            settings={"theme": "dark"},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.assertEqual(response.email, "demo@crypto-radar.local")
        self.assertEqual(response.name, "Demo Trader")
        self.assertEqual(response.settings["theme"], "dark")

    def test_users_router_exposes_me_endpoint(self) -> None:
        paths = {route.path for route in router.routes}

        self.assertIn("/users/me", paths)
        self.assertIn("/users/me/settings", paths)

    def test_user_settings_patch_accepts_virtual_simulation_level(self) -> None:
        request = UserSettingsPatchRequest(virtual_simulation_level="advanced")

        self.assertEqual(request.virtual_simulation_level, "advanced")


if __name__ == "__main__":
    unittest.main()
