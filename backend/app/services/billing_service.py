from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.core.database import SessionLocal
from app.models.user import SubscriptionPlan, UserSubscription
from app.schemas.billing import (
    BillingCheckoutRequest,
    BillingPlanResponse,
    BillingPortalRequest,
    BillingProviderActionResponse,
    BillingProviderNotReadyResponse,
    BillingSubscriptionResponse,
    BillingWebhookRequest,
)
from app.services.user_identity import resolve_app_user


class BillingProvider(Protocol):
    provider: str

    def create_checkout_session(self, request: BillingCheckoutRequest) -> BillingProviderActionResponse:
        ...

    def create_customer_portal(self, request: BillingPortalRequest) -> BillingProviderActionResponse:
        ...

    def handle_webhook(self, request: BillingWebhookRequest) -> BillingProviderActionResponse:
        ...


class BillingProviderNotReadyError(NotImplementedError):
    def __init__(self, response: BillingProviderNotReadyResponse) -> None:
        super().__init__(response.message)
        self.response = response


class BillingService:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        provider: BillingProvider | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider

    def list_plans(self) -> list[BillingPlanResponse]:
        with self._session_factory() as session:
            plans = session.scalars(
                select(SubscriptionPlan)
                .where(SubscriptionPlan.is_active.is_(True))
                .order_by(SubscriptionPlan.price_monthly.asc(), SubscriptionPlan.created_at.asc())
            ).all()
            return [_plan_to_response(plan) for plan in plans]

    def subscription_status(self, user_id: str = "demo_user") -> BillingSubscriptionResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, user_id)
            subscription = session.scalars(
                select(UserSubscription)
                .options(joinedload(UserSubscription.plan))
                .where(UserSubscription.user_id == user.id)
                .order_by(UserSubscription.created_at.desc())
                .limit(1)
            ).one_or_none()
            if subscription is None:
                return BillingSubscriptionResponse(
                    user_id=user.id,
                    state="none",
                    tier="free",
                    plan_id=None,
                    plan_code=None,
                    plan_name=None,
                    current_period_start=None,
                    current_period_end=None,
                    external_provider=None,
                    external_id=None,
                    limits={},
                    features={},
                )
            plan = subscription.plan
            return BillingSubscriptionResponse(
                user_id=user.id,
                state=subscription.status,
                tier=plan.code,
                plan_id=plan.id,
                plan_code=plan.code,
                plan_name=plan.name,
                current_period_start=subscription.current_period_start,
                current_period_end=subscription.current_period_end,
                external_provider=subscription.external_provider,
                external_id=subscription.external_id,
                limits=plan.limits,
                features=plan.features,
            )

    def create_checkout_session(self, request: BillingCheckoutRequest) -> BillingProviderActionResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, request.user_id)
            plan = _resolve_plan(session, request.plan_code)
        if self._provider is None:
            raise BillingProviderNotReadyError(
                BillingProviderNotReadyResponse(
                    message=(
                        "Billing checkout provider integration is not implemented yet. "
                        "Subscription state remains in PostgreSQL user_subscriptions."
                    ),
                    provider="stub",
                    details={
                        "user_id": str(user.id),
                        "plan_code": plan.code,
                        "success_url_present": bool(request.success_url),
                        "cancel_url_present": bool(request.cancel_url),
                    },
                )
            )
        return self._provider.create_checkout_session(request)

    def create_customer_portal(self, request: BillingPortalRequest) -> BillingProviderActionResponse:
        with self._session_factory() as session:
            user = resolve_app_user(session, request.user_id)
            subscription = session.scalars(
                select(UserSubscription)
                .where(UserSubscription.user_id == user.id)
                .order_by(UserSubscription.created_at.desc())
                .limit(1)
            ).one_or_none()
        if self._provider is None:
            raise BillingProviderNotReadyError(
                BillingProviderNotReadyResponse(
                    message="Billing customer portal provider integration is not implemented yet.",
                    provider="stub",
                    details={
                        "user_id": str(user.id),
                        "subscription_id": str(subscription.id) if subscription else None,
                        "external_provider": subscription.external_provider if subscription else None,
                        "return_url_present": bool(request.return_url),
                    },
                )
            )
        return self._provider.create_customer_portal(request)

    def handle_webhook(self, request: BillingWebhookRequest) -> BillingProviderActionResponse:
        if self._provider is None:
            raise BillingProviderNotReadyError(
                BillingProviderNotReadyResponse(
                    message=(
                        "Billing webhook handling is not implemented yet. "
                        "Provider events will update user_subscriptions and emit outbox events later."
                    ),
                    provider=request.provider,
                    details={
                        "event_id": request.event_id,
                        "payload_keys": sorted(request.payload.keys()),
                    },
                )
            )
        return self._provider.handle_webhook(request)


def _resolve_plan(session: Session, plan_code: str) -> SubscriptionPlan:
    plan = session.scalars(
        select(SubscriptionPlan).where(
            SubscriptionPlan.code == plan_code.strip().lower(),
            SubscriptionPlan.is_active.is_(True),
        )
    ).one_or_none()
    if plan is None:
        raise LookupError(f"Subscription plan is not seeded: {plan_code}")
    return plan


def _plan_to_response(plan: SubscriptionPlan) -> BillingPlanResponse:
    return BillingPlanResponse(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        price_monthly=plan.price_monthly,
        currency=plan.currency,
        limits=plan.limits,
        features=plan.features,
        is_active=plan.is_active,
        created_at=plan.created_at,
    )

billing_service = BillingService()
