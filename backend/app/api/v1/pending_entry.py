from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.schemas.pending_entry import PendingEntryIntentRead
from app.schemas.trade import ManualConfirmRequest
from app.services.pending_entry import pending_entry_intent_service
from app.services.signal_risk_reward import StrategyRiskRewardBlocked
from app.services.signal_service import signal_service

router = APIRouter(tags=["pending-entry"])


class PendingEntryActionRequest(BaseModel):
    user_id: str = "demo_user"


@router.post("/signals/{signal_id}/pending-entry", response_model=PendingEntryIntentRead)
async def arm_pending_entry(
    signal_id: str,
    request: ManualConfirmRequest | None = None,
) -> PendingEntryIntentRead:
    try:
        return pending_entry_intent_service.arm_signal_workflow(
            signal_id=signal_id,
            request=request,
            auto_entry_arm=signal_service.arm_auto_entry,
        )
    except StrategyRiskRewardBlocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.reason,
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/signals/{signal_id}/pending-entry", response_model=list[PendingEntryIntentRead])
async def list_pending_entries_for_signal(
    signal_id: str,
    user_id: str = Query(default="demo_user"),
) -> list[PendingEntryIntentRead]:
    try:
        return pending_entry_intent_service.list_active_for_signal_user(
            signal_id=signal_id,
            user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/pending-entry/{intent_id}/cancel", response_model=PendingEntryIntentRead)
async def cancel_pending_entry(
    intent_id: str,
    request: PendingEntryActionRequest | None = None,
) -> PendingEntryIntentRead:
    request = request or PendingEntryActionRequest()
    try:
        return pending_entry_intent_service.cancel_intent(
            intent_id,
            user_id=request.user_id,
            reason="Cancelled by user.",
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/pending-entry/{intent_id}/reconfirm", response_model=PendingEntryIntentRead)
async def reconfirm_pending_entry(
    intent_id: str,
    request: ManualConfirmRequest | None = None,
) -> PendingEntryIntentRead:
    try:
        return pending_entry_intent_service.reconfirm_intent(
            intent_id,
            request=request,
            auto_entry_arm=signal_service.arm_auto_entry,
        )
    except StrategyRiskRewardBlocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.reason,
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
