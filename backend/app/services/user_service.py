from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import SessionLocal
from app.models.user import AppUser, UserProfile
from app.schemas.user import UserProfileResponse, UserSettingsPatchRequest
from app.services.bootstrap_service import DEMO_USERNAME


class UserService:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def get_profile(self, user_id: str = "demo_user") -> UserProfileResponse:
        with self._session_factory() as session:
            user = _resolve_user(session, user_id)
            return _profile_response(user)

    def update_settings(
        self,
        patch: UserSettingsPatchRequest,
        user_id: str = "demo_user",
    ) -> UserProfileResponse:
        with self._session_factory() as session:
            user = _resolve_user(session, user_id)
            profile = _ensure_profile(session, user)
            settings = dict(profile.settings or {})
            if patch.virtual_simulation_level is not None:
                virtual_trading = dict(settings.get("virtual_trading") or {})
                virtual_trading["simulation_level"] = patch.virtual_simulation_level
                virtual_trading["simulation_level_status"] = (
                    "active" if patch.virtual_simulation_level == "mvp" else "stub"
                )
                virtual_trading["effective_simulation_level"] = (
                    patch.virtual_simulation_level
                    if patch.virtual_simulation_level == "mvp"
                    else "mvp"
                )
                settings["virtual_trading"] = virtual_trading
            profile.settings = settings
            profile.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(user)
            return _profile_response(user)


def _resolve_user(session: Session, user_id: str) -> AppUser:
    user_uuid = _parse_uuid(user_id)
    if user_uuid is not None:
        user = session.scalars(
            select(AppUser).options(joinedload(AppUser.profile)).where(AppUser.id == user_uuid)
        ).one_or_none()
        if user is not None:
            return user
    user = session.scalars(
        select(AppUser)
        .options(joinedload(AppUser.profile))
        .where((AppUser.username == user_id) | (AppUser.email == user_id))
    ).one_or_none()
    if user is not None:
        return user
    if user_id == "demo_user":
        user = session.scalars(
            select(AppUser).options(joinedload(AppUser.profile)).where(AppUser.username == DEMO_USERNAME)
        ).one_or_none()
        if user is not None:
            return user
    raise LookupError(f"User is not seeded: {user_id}")


def _ensure_profile(session: Session, user: AppUser) -> UserProfile:
    if user.profile is not None:
        return user.profile
    profile = UserProfile(user_id=user.id, settings=_default_settings())
    session.add(profile)
    session.flush()
    user.profile = profile
    return profile


def _profile_response(user: AppUser) -> UserProfileResponse:
    profile = user.profile
    display_name = profile.display_name if profile else None
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        name=display_name or user.username or user.email,
        display_name=display_name,
        avatar_url=profile.avatar_url if profile else None,
        status=user.status,
        locale=user.locale,
        timezone=user.timezone,
        risk_profile=user.risk_profile,
        onboarding_done=profile.onboarding_done if profile else False,
        settings=_settings_with_defaults(profile.settings if profile else {}),
        created_at=user.created_at,
        updated_at=profile.updated_at if profile else user.updated_at,
    )


def _settings_with_defaults(settings: dict) -> dict:
    merged = dict(settings or {})
    virtual_trading = dict(merged.get("virtual_trading") or {})
    level = virtual_trading.get("simulation_level") or "mvp"
    if level not in {"mvp", "advanced", "pro"}:
        level = "mvp"
    virtual_trading["simulation_level"] = level
    virtual_trading["simulation_level_status"] = "active" if level == "mvp" else "stub"
    virtual_trading["effective_simulation_level"] = level if level == "mvp" else "mvp"
    merged["virtual_trading"] = virtual_trading
    return merged


def _default_settings() -> dict:
    return _settings_with_defaults({})


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


user_service = UserService()
