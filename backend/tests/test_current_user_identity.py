import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.bootstrap_service import DEMO_AUTH_PROVIDER_SUBJECT
from app.services.current_user import CurrentUserIdentityService


class CurrentUserIdentityServiceTest(unittest.TestCase):
    def test_dev_environment_falls_back_to_seeded_demo_subject(self) -> None:
        service = CurrentUserIdentityService()

        with patch("app.services.current_user.settings.app_env", "development"):
            identity = service.resolve_from_request(_request())

        self.assertEqual(identity.user_id, DEMO_AUTH_PROVIDER_SUBJECT)
        self.assertEqual(identity.source, "dev_identity")

    def test_production_environment_requires_authenticated_identity(self) -> None:
        service = CurrentUserIdentityService()

        with patch("app.services.current_user.settings.app_env", "production"):
            with self.assertRaises(PermissionError):
                service.resolve_from_request(_request())

    def test_production_environment_accepts_auth_state_identity(self) -> None:
        service = CurrentUserIdentityService()

        with patch("app.services.current_user.settings.app_env", "production"):
            identity = service.resolve_from_request(_request(state=SimpleNamespace(user_id="usr_live")))

        self.assertEqual(identity.user_id, "usr_live")
        self.assertEqual(identity.source, "request.state")


class _RequestStub:
    def __init__(self, *, state: SimpleNamespace | None = None) -> None:
        self.headers: dict[str, str] = {}
        self.state = state or SimpleNamespace()

    @property
    def session(self):
        raise AssertionError("SessionMiddleware is not installed")


def _request(*, state: SimpleNamespace | None = None) -> _RequestStub:
    return _RequestStub(state=state)


if __name__ == "__main__":
    unittest.main()
