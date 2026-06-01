from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import SessionLocal
from app.models.user import AppUser, UserProfile
from app.schemas.user import UserProfileResponse, UserSettingsPatchRequest
from app.services.bootstrap_service import DEMO_USERNAME
from app.services.risk_management import (
    apply_risk_management_patch,
    normalize_risk_management_settings,
)
from app.services.trade_repository import sync_virtual_starting_balance


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
            previous_risk_management = normalize_risk_management_settings(
                settings.get("risk_management"),
                user.risk_profile,
            )
            if patch.virtual_simulation_level is not None:
                settings = _apply_virtual_simulation_level_patch(
                    settings,
                    patch.virtual_simulation_level,
                )
            risk_management = apply_risk_management_patch(
                current_settings=settings.get("risk_management"),
                current_user_profile=user.risk_profile,
                patch=patch.risk_management,
                risk_profile=patch.risk_profile,
            )
            if risk_management is not None:
                user.risk_profile = risk_management["risk_profile"]
                _sync_virtual_balance_if_changed(
                    session=session,
                    user=user,
                    previous_settings=previous_risk_management,
                    next_settings=risk_management,
                )
                settings["risk_management"] = risk_management
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
        settings=_settings_with_defaults(profile.settings if profile else {}, user.risk_profile),
        created_at=user.created_at,
        updated_at=profile.updated_at if profile else user.updated_at,
    )


def _settings_with_defaults(settings: dict, risk_profile: str | None = None) -> dict:
    merged = dict(settings or {})
    virtual_trading = dict(merged.get("virtual_trading") or {})
    level = virtual_trading.get("simulation_level") or "mvp"
    if level not in {"mvp", "advanced", "pro"}:
        level = "mvp"
    virtual_trading["simulation_level"] = level
    virtual_trading["simulation_level_status"] = "active" if level == "mvp" else "stub"
    virtual_trading["effective_simulation_level"] = level if level == "mvp" else "mvp"
    merged["virtual_trading"] = virtual_trading
    merged["risk_management"] = normalize_risk_management_settings(
        merged.get("risk_management"),
        risk_profile,
    )
    return merged


def _apply_virtual_simulation_level_patch(settings: dict, simulation_level: str) -> dict:
    merged = dict(settings or {})
    virtual_trading = dict(merged.get("virtual_trading") or {})
    virtual_trading["simulation_level"] = simulation_level
    virtual_trading["simulation_level_status"] = (
        "active" if simulation_level == "mvp" else "stub"
    )
    virtual_trading["effective_simulation_level"] = (
        simulation_level
        if simulation_level == "mvp"
        else "mvp"
    )
    merged["virtual_trading"] = virtual_trading
    return merged


def _sync_virtual_balance_if_changed(
    *,
    session: Session,
    user: AppUser,
    previous_settings: dict,
    next_settings: dict,
) -> None:
    previous_balance = Decimal(str(previous_settings.get("virtual_starting_balance", 0)))
    next_balance = Decimal(str(next_settings.get("virtual_starting_balance", 0)))
    if next_balance > 0 and next_balance != previous_balance:
        sync_virtual_starting_balance(session, user, next_balance)


def _default_settings() -> dict:
    return _settings_with_defaults({}, "balanced")


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


user_service = UserService()
