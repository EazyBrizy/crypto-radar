from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import SessionLocal
from app.models.user import AppUser
from app.schemas.user import UserProfileResponse
from app.services.bootstrap_service import DEMO_USERNAME


class UserService:
    def __init__(self, session_factory: sessionmaker[Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def get_profile(self, user_id: str = "demo_user") -> UserProfileResponse:
        with self._session_factory() as session:
            user = _resolve_user(session, user_id)
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
                settings=profile.settings if profile else {},
                created_at=user.created_at,
                updated_at=profile.updated_at if profile else user.updated_at,
            )


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


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


user_service = UserService()
