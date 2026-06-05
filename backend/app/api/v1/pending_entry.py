from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.schemas.pending_entry import PendingEntryIntentMode, PendingEntryIntentRead
from app.schemas.trade import ManualConfirmRequest
from app.services.pending_entry import pending_entry_intent_service
from app.services.signal_risk_reward import StrategyRiskRewardBlocked
from app.services.signal_service import signal_service

router = APIRouter(tags=["pending-entry"])


class PendingEntryActionRequest(BaseModel):
    user_id: str = "demo_user"


@router.get("/pending-entry", response_model=list[PendingEntryIntentRead])
async def list_pending_entries(
    user_id: str = Query(default="demo_user"),
    scope: Literal["active", "history"] = Query(default="active"),
    mode: PendingEntryIntentMode | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[PendingEntryIntentRead]:
    try:
        if scope == "history":
            return pending_entry_intent_service.list_history_for_user(
                user_id=user_id,
                mode=mode,
                limit=limit,
            )
        return pending_entry_intent_service.list_active_for_user(
            user_id=user_id,
            mode=mode,
            limit=limit,
        )
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


@router.get("/signals/{signal_id}/pending-entry", response_model=PendingEntryIntentRead | None)
async def get_active_pending_entry_for_signal(
    signal_id: str,
    user_id: str = Query(default="demo_user"),
    mode: PendingEntryIntentMode = Query(default="virtual"),
) -> PendingEntryIntentRead | None:
    try:
        return pending_entry_intent_service.get_active_for_signal(
            signal_id=signal_id,
            user_id=user_id,
            mode=mode,
        )
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


@router.get("/signals/{signal_id}/pending-entry/history", response_model=list[PendingEntryIntentRead])
async def list_pending_entry_history_for_signal(
    signal_id: str,
    user_id: str = Query(default="demo_user"),
    mode: PendingEntryIntentMode = Query(default="virtual"),
) -> list[PendingEntryIntentRead]:
    try:
        return pending_entry_intent_service.list_history_for_signal(
            signal_id=signal_id,
            user_id=user_id,
            mode=mode,
        )
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
