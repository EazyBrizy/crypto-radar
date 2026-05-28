from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class UserProfileResponse(BaseModel):
    id: UUID
    email: str
    username: str | None
    name: str | None
    display_name: str | None
    avatar_url: str | None
    status: str
    locale: str
    timezone: str
    risk_profile: str | None
    onboarding_done: bool
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
