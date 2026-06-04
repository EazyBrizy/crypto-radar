from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import AppUser, UserAuthIdentity
from app.services.bootstrap_service import DEMO_USERNAME

DEMO_USER_ALIASES = {"demo_user", "usr_demo", "demo", "demo@crypto-radar.local"}


def resolve_app_user(session: Session, user_ref: str | UUID) -> AppUser:
    user_uuid = _parse_uuid(user_ref)
    if user_uuid is not None:
        user = session.get(AppUser, user_uuid)
        if user is not None:
            return user

    user_key = str(user_ref)
    user = session.scalars(select(AppUser).where(AppUser.username == user_key)).one_or_none()
    if user is not None:
        return user

    user = session.scalars(select(AppUser).where(AppUser.email == user_key)).one_or_none()
    if user is not None:
        return user

    user = (
        session.scalars(
            select(AppUser)
            .join(UserAuthIdentity)
            .where(UserAuthIdentity.provider_subject == user_key)
        )
        .unique()
        .one_or_none()
    )
    if user is not None:
        return user

    if user_key in DEMO_USER_ALIASES:
        user = session.scalars(select(AppUser).where(AppUser.username == DEMO_USERNAME)).one_or_none()
        if user is not None:
            return user

    raise LookupError(f"User is not seeded: {user_ref}")


def resolve_app_user_uuid(session: Session, user_ref: str | UUID) -> UUID:
    return resolve_app_user(session, user_ref).id


def _parse_uuid(value: str | UUID) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
