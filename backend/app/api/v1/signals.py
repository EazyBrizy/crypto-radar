from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.signal import RadarSignal
from app.schemas.signal_action import (
    SignalActionMode,
    SignalActionRequest,
    SignalActionResponse,
    SignalActionState,
)
from app.schemas.trade import (
    ManualConfirmRequest,
    ManualDecisionResponse,
    ManualRejectRequest,
    VirtualExecutionReport,
)
from app.services.execution_service import real_execution_service
from app.services.message_broker import realtime_event_broker
from app.services.current_user import current_user_identity_service
from app.services.realtime_events import signal_invalidated_event
from app.services.signal_actions import SignalActionService, SignalActionUnavailable
from app.services.signal_service import signal_service
from app.services.virtual_trading import VirtualExecutionRejected, virtual_trading_service

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=list[RadarSignal])
async def list_signals() -> list[RadarSignal]:
    return signal_service.list_signals()


@router.get("/active", response_model=list[RadarSignal])
async def list_active_signals() -> list[RadarSignal]:
    return signal_service.list_active_signals()


@router.get("/open", response_model=list[RadarSignal])
async def list_open_signals() -> list[RadarSignal]:
    return signal_service.list_open_signals()


@router.get("/{signal_id}", response_model=RadarSignal)
async def get_signal(signal_id: str) -> RadarSignal:
    signal = signal_service.get_signal(signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal is not found",
        )
    return signal


@router.get("/{signal_id}/action-state", response_model=SignalActionState)
async def get_signal_action_state(
    signal_id: str,
    request: Request,
    mode: SignalActionMode = Query(default="virtual"),
    connection_id: str | None = Query(default=None),
) -> SignalActionState:
    try:
        current_user = current_user_identity_service.resolve_from_request(request)
        return _signal_action_service().get_action_state(
            signal_id,
            mode=mode,
            connection_id=connection_id,
            user_id=current_user.user_id,
        )
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


@router.post("/{signal_id}/actions", response_model=SignalActionResponse)
async def send_signal_action(
    signal_id: str,
    action: SignalActionRequest,
    request: Request,
) -> SignalActionResponse:
    try:
        current_user = current_user_identity_service.resolve_from_request(request)
        return await _signal_action_service().execute_action(
            signal_id,
            action,
            user_id=current_user.user_id,
        )
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
    except SignalActionUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except VirtualExecutionRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": str(exc),
                "virtual_execution": exc.report.model_dump(mode="json"),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/{signal_id}/confirm",
    response_model=ManualDecisionResponse,
    deprecated=True,
)
async def confirm_signal(
    signal_id: str,
    request: ManualConfirmRequest | None = None,
) -> ManualDecisionResponse:
    # Deprecated compatibility endpoint. Trading action logic lives in
    # SignalActionService; keep this path only while old clients migrate.
    request = request or ManualConfirmRequest()
    try:
        return await _signal_action_service().confirm_legacy(signal_id, request)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except VirtualExecutionRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": str(exc),
                "virtual_execution": exc.report.model_dump(mode="json"),
            },
        ) from exc
    except SignalActionUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{signal_id}/execution-preview", response_model=VirtualExecutionReport)
async def preview_virtual_execution(
    signal_id: str,
    request: ManualConfirmRequest | None = None,
) -> VirtualExecutionReport:
    if request is None:
        try:
            return _signal_action_service().preview_virtual_execution(
                signal_id,
                user_id="usr_demo",
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
    request = request or ManualConfirmRequest()
    signal = signal_service.get_signal(signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal is not found",
        )
    if request.mode == "real":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Real execution preview is not implemented yet",
        )
    try:
        return virtual_trading_service.preview_virtual_execution(signal, request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{signal_id}/reject", response_model=ManualDecisionResponse)
async def reject_signal(
    signal_id: str,
    request: ManualRejectRequest | None = None,
) -> ManualDecisionResponse:
    request = request or ManualRejectRequest()
    current_signal = signal_service.get_signal(signal_id)
    if current_signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal is not found",
        )
    if current_signal.status == "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Confirmed signal cannot be rejected",
        )

    signal = signal_service.reject_signal(signal_id, note=request.reason)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal is not found",
        )
    await realtime_event_broker.publish(signal_invalidated_event(signal, reason=request.reason))

    return ManualDecisionResponse(
        signal=signal,
        message="Signal rejected",
    )


def _signal_action_service() -> SignalActionService:
    from app.services.pending_entry import pending_entry_intent_service as current_pending_entry_service

    return SignalActionService(
        signals=signal_service,
        pending_entries=current_pending_entry_service,
        virtual_trading=virtual_trading_service,
        real_execution=real_execution_service,
        realtime_broker=realtime_event_broker,
    )
