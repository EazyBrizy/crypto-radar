from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BillingPlanResponse(BaseModel):
    id: UUID
    code: str
    name: str
    price_monthly: Decimal
    currency: str
    limits: dict[str, Any]
    features: dict[str, Any]
    is_active: bool
    created_at: datetime


class BillingSubscriptionResponse(BaseModel):
    user_id: UUID
    state: Literal["active", "trialing", "past_due", "canceled", "none"]
    tier: str
    plan_id: UUID | None
    plan_code: str | None
    plan_name: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    external_provider: str | None
    external_id: str | None
    limits: dict[str, Any]
    features: dict[str, Any]


class BillingCheckoutRequest(BaseModel):
    user_id: str = "demo_user"
    plan_code: str = Field(..., min_length=1)
    success_url: str | None = None
    cancel_url: str | None = None


class BillingPortalRequest(BaseModel):
    user_id: str = "demo_user"
    return_url: str | None = None


class BillingWebhookRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    event_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class BillingProviderNotReadyResponse(BaseModel):
    status: Literal["not_implemented"] = "not_implemented"
    message: str
    provider: str
    storage_targets: list[str] = Field(default_factory=lambda: ["subscription_plans", "user_subscriptions"])
    provider_integration_required: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class BillingProviderActionResponse(BaseModel):
    status: Literal["created", "handled"]
    provider: str
    url: str | None = None
    external_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
