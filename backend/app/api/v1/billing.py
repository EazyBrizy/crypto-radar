from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.schemas.billing import (
    BillingCheckoutRequest,
    BillingPlanResponse,
    BillingPortalRequest,
    BillingProviderActionResponse,
    BillingProviderNotReadyResponse,
    BillingSubscriptionResponse,
    BillingWebhookRequest,
)
from app.services.billing_service import BillingProviderNotReadyError, billing_service

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans", response_model=list[BillingPlanResponse])
async def list_billing_plans() -> list[BillingPlanResponse]:
    return billing_service.list_plans()


@router.get("/subscription", response_model=BillingSubscriptionResponse)
async def get_billing_subscription(user_id: str = "demo_user") -> BillingSubscriptionResponse:
    try:
        return billing_service.subscription_status(user_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/checkout",
    response_model=BillingProviderActionResponse,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"model": BillingProviderNotReadyResponse}},
)
async def create_billing_checkout(request: BillingCheckoutRequest) -> BillingProviderActionResponse | JSONResponse:
    try:
        return billing_service.create_checkout_session(request)
    except BillingProviderNotReadyError as exc:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=exc.response.model_dump(mode="json"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/customer-portal",
    response_model=BillingProviderActionResponse,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"model": BillingProviderNotReadyResponse}},
)
async def create_billing_customer_portal(
    request: BillingPortalRequest,
) -> BillingProviderActionResponse | JSONResponse:
    try:
        return billing_service.create_customer_portal(request)
    except BillingProviderNotReadyError as exc:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=exc.response.model_dump(mode="json"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/webhooks/{provider}",
    response_model=BillingProviderActionResponse,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"model": BillingProviderNotReadyResponse}},
)
async def handle_billing_webhook(
    provider: str,
    request: BillingWebhookRequest | None = None,
) -> BillingProviderActionResponse | JSONResponse:
    payload = (request or BillingWebhookRequest(provider=provider)).model_copy(update={"provider": provider})
    try:
        return billing_service.handle_webhook(payload)
    except BillingProviderNotReadyError as exc:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=exc.response.model_dump(mode="json"),
        )
