from fastapi import APIRouter, HTTPException, status

from app.domain.signal_status import can_signal_enter_now, is_terminal_signal_status
from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    ManualConfirmRequest,
    ManualDecisionResponse,
    ManualRejectRequest,
    VirtualExecutionReport,
)
from app.services.execution_service import real_execution_service
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import (
    signal_invalidated_event,
    signal_updated_event,
    trade_activated_event,
)
from app.services.signal_risk_reward import StrategyRiskRewardBlocked
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


@router.post("/{signal_id}/confirm", response_model=ManualDecisionResponse)
async def confirm_signal(
    signal_id: str,
    request: ManualConfirmRequest | None = None,
) -> ManualDecisionResponse:
    request = request or ManualConfirmRequest()
    signal = signal_service.get_signal(signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal is not found",
        )
    if is_terminal_signal_status(signal.status):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Signal cannot be confirmed in current status",
        )
    if request.auto_enter_on_confirmation and not can_signal_enter_now(
        signal.status,
        decision=signal.decision,
        can_enter=signal.can_enter,
        mode=request.mode,
    ):
        try:
            arm_result = signal_service.arm_auto_entry(signal.id, request.model_dump(mode="json"))
        except StrategyRiskRewardBlocked as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=exc.reason,
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except LookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        if arm_result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Signal is not found",
            )
        await realtime_event_broker.publish(signal_updated_event(arm_result.signal))
        return ManualDecisionResponse(
            signal=arm_result.signal,
            pending_entry_intent=arm_result.pending_entry_intent,
            message="Auto-entry armed; waiting for accepted entry zone",
        )
    if not can_signal_enter_now(
        signal.status,
        decision=signal.decision,
        can_enter=signal.can_enter,
        mode=request.mode,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Signal is not actionable yet. Arm auto-entry to wait for confirmation.",
        )

    if request.mode == "real":
        real_execution = await real_execution_service.place_order(signal, request)
        return ManualDecisionResponse(
            signal=signal,
            real_execution=real_execution,
            real_execution_result=real_execution,
            message=real_execution.message,
        )

    try:
        updated_signal, virtual_trade = virtual_trading_service.confirm_signal(signal, request)
    except StrategyRiskRewardBlocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.reason,
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

    await realtime_event_broker.publish(signal_updated_event(updated_signal))
    await realtime_event_broker.publish(trade_activated_event(virtual_trade))

    return ManualDecisionResponse(
        signal=updated_signal,
        virtual_trade=virtual_trade,
        message="Virtual trade opened",
    )


@router.post("/{signal_id}/execution-preview", response_model=VirtualExecutionReport)
async def preview_virtual_execution(
    signal_id: str,
    request: ManualConfirmRequest | None = None,
) -> VirtualExecutionReport:
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
