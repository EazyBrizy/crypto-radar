from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.core.config import settings
from app.services.bootstrap_service import DEMO_AUTH_PROVIDER_SUBJECT


@dataclass(frozen=True)
class CurrentUserIdentity:
    user_id: str
    source: str


class CurrentUserIdentityService:
    """Resolves the app user reference for backend-owned action requests."""

    AUTH_HEADER_CANDIDATES = (
        "x-auth-user-id",
        "x-auth-subject",
    )
    DEV_HEADER_CANDIDATES = (
        "x-user-id",
        "x-dev-user",
    )

    def resolve_from_request(self, request: Request) -> CurrentUserIdentity:
        state_user_id = _user_id_from_state(request)
        if state_user_id:
            return CurrentUserIdentity(user_id=state_user_id, source="request.state")

        session_user_id = _user_id_from_session(request)
        if session_user_id:
            return CurrentUserIdentity(user_id=session_user_id, source="session")

        header_candidates = list(self.AUTH_HEADER_CANDIDATES)
        if not _is_production_environment(settings.app_env):
            header_candidates.extend(self.DEV_HEADER_CANDIDATES)
        for header in header_candidates:
            value = _clean_user_id(request.headers.get(header))
            if value:
                return CurrentUserIdentity(user_id=value, source=f"header:{header}")

        if _is_production_environment(settings.app_env):
            raise PermissionError("Authenticated user is required for signal actions.")

        return CurrentUserIdentity(
            user_id=DEMO_AUTH_PROVIDER_SUBJECT,
            source="dev_identity",
        )


def _is_production_environment(value: str) -> bool:
    return value.strip().lower() in {"prod", "production"}


def _user_id_from_state(request: Request) -> str | None:
    for attr in ("user_id", "auth_user_id", "auth_subject"):
        value = _clean_user_id(getattr(request.state, attr, None))
        if value:
            return value
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        for key in ("id", "user_id", "sub", "subject"):
            value = _clean_user_id(user.get(key))
            if value:
                return value
    for attr in ("id", "user_id", "sub", "subject"):
        value = _clean_user_id(getattr(user, attr, None))
        if value:
            return value
    return None


def _user_id_from_session(request: Request) -> str | None:
    try:
        session = request.session
    except (AssertionError, AttributeError):
        return None
    for key in ("user_id", "auth_user_id", "sub", "subject"):
        value = _clean_user_id(session.get(key))
        if value:
            return value
    user = session.get("user")
    if isinstance(user, dict):
        for key in ("id", "user_id", "sub", "subject"):
            value = _clean_user_id(user.get(key))
            if value:
                return value
    return None


def _clean_user_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


current_user_identity_service = CurrentUserIdentityService()


def resolve_current_user(request: Request) -> CurrentUserIdentity:
    return current_user_identity_service.resolve_from_request(request)
