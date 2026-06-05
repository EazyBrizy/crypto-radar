from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.schemas.pending_entry import PendingEntryIntentMode, PendingEntryIntentRead
from app.schemas.trade import ManualConfirmRequest
from app.services.pending_entry import RealPendingEntryNotImplemented, pending_entry_intent_service
from app.services.signal_risk_reward import StrategyRiskRewardBlocked
from app.services.current_user import current_user_identity_service
from app.services.signal_views import annotate_pending_entry_view

router = APIRouter(tags=["pending-entry"])


class PendingEntryActionRequest(BaseModel):
    user_id: str | None = None


@router.get("/pending-entry", response_model=list[PendingEntryIntentRead])
async def list_pending_entries(
    request: Request,
    user_id: str | None = Query(default=None),
    scope: Literal["active", "history"] = Query(default="active"),
    mode: PendingEntryIntentMode | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[PendingEntryIntentRead]:
    try:
        resolved_user_id = user_id or _current_user_id(request)
        if scope == "history":
            return [
                annotate_pending_entry_view(intent)
                for intent in pending_entry_intent_service.list_history_for_user(
                    user_id=resolved_user_id,
                    mode=mode,
                    limit=limit,
                )
            ]
        return [
            annotate_pending_entry_view(intent)
            for intent in pending_entry_intent_service.list_active_for_user(
                user_id=resolved_user_id,
                mode=mode,
                limit=limit,
            )
        ]
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
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


@router.post("/signals/{signal_id}/pending-entry", response_model=PendingEntryIntentRead)
async def arm_pending_entry(
    signal_id: str,
    fastapi_request: Request,
    request: ManualConfirmRequest | None = None,
) -> PendingEntryIntentRead:
    try:
        request = _request_for_current_user(fastapi_request, request)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    try:
        return annotate_pending_entry_view(pending_entry_intent_service.arm_signal_workflow(
            signal_id=signal_id,
            request=request,
        ))
    except StrategyRiskRewardBlocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.reason,
        ) from exc
    except RealPendingEntryNotImplemented as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "reason_code": exc.reason_code},
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
    request: Request,
    user_id: str | None = Query(default=None),
    mode: PendingEntryIntentMode = Query(default="virtual"),
) -> PendingEntryIntentRead | None:
    try:
        resolved_user_id = user_id or _current_user_id(request)
        intent = pending_entry_intent_service.get_active_for_signal(
            signal_id=signal_id,
            user_id=resolved_user_id,
            mode=mode,
        )
        return annotate_pending_entry_view(intent) if intent is not None else None
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
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


@router.get("/signals/{signal_id}/pending-entry/history", response_model=list[PendingEntryIntentRead])
async def list_pending_entry_history_for_signal(
    signal_id: str,
    request: Request,
    user_id: str | None = Query(default=None),
    mode: PendingEntryIntentMode = Query(default="virtual"),
) -> list[PendingEntryIntentRead]:
    try:
        resolved_user_id = user_id or _current_user_id(request)
        return [
            annotate_pending_entry_view(intent)
            for intent in pending_entry_intent_service.list_history_for_signal(
                signal_id=signal_id,
                user_id=resolved_user_id,
                mode=mode,
            )
        ]
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
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


@router.post("/pending-entry/{intent_id}/cancel", response_model=PendingEntryIntentRead)
async def cancel_pending_entry(
    intent_id: str,
    fastapi_request: Request,
    request: PendingEntryActionRequest | None = None,
) -> PendingEntryIntentRead:
    try:
        resolved_user_id = _current_user_id(fastapi_request)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    try:
        return annotate_pending_entry_view(pending_entry_intent_service.cancel_intent(
            intent_id,
            user_id=resolved_user_id,
            reason="Cancelled by user.",
        ))
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
    fastapi_request: Request,
    request: ManualConfirmRequest | None = None,
) -> PendingEntryIntentRead:
    try:
        request = _request_for_current_user(fastapi_request, request)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    try:
        return annotate_pending_entry_view(pending_entry_intent_service.reconfirm_intent(
            intent_id,
            request=request,
        ))
    except StrategyRiskRewardBlocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.reason,
        ) from exc
    except RealPendingEntryNotImplemented as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "reason_code": exc.reason_code},
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


def _current_user_id(request: Request) -> str:
    return current_user_identity_service.resolve_from_request(request).user_id


def _request_for_current_user(
    fastapi_request: Request,
    request: ManualConfirmRequest | None,
) -> ManualConfirmRequest:
    user_id = _current_user_id(fastapi_request)
    if request is None:
        return ManualConfirmRequest(user_id=user_id)
    return request.model_copy(update={"user_id": user_id})
