from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationDeliveryResponse(BaseModel):
    id: UUID
    notification_id: UUID
    channel: str
    status: str
    provider_msg_id: str | None
    sent_at: datetime | None
    error: str | None


class NotificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    type: str
    title: str
    body: str | None
    payload: dict[str, Any]
    is_read: bool
    created_at: datetime
    deliveries: list[NotificationDeliveryResponse] = Field(default_factory=list)


class NotificationCreateRequest(BaseModel):
    user_id: str = "demo_user"
    type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    body: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    channels: list[str] = Field(default_factory=lambda: ["websocket"])


class NotificationUpdateRequest(BaseModel):
    is_read: bool | None = None


class NotificationTestRequest(BaseModel):
    user_id: str = "demo_user"
    channels: list[str] = Field(default_factory=lambda: ["websocket", "email", "telegram"])
