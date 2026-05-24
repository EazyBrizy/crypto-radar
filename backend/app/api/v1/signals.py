from fastapi import APIRouter, HTTPException, status

from app.schemas.signal import RadarSignal
from app.schemas.trade import (
    ManualConfirmRequest,
    ManualDecisionResponse,
    ManualRejectRequest,
)
from app.services.execution_service import real_execution_service
from app.services.signal_service import signal_service
from app.services.trade_service import trade_service

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("", response_model=list[RadarSignal])
async def list_signals() -> list[RadarSignal]:
    return signal_service.list_signals()


@router.get("/{signal_id}", response_model=RadarSignal)
async def get_signal(signal_id: str) -> RadarSignal:
    signal = signal_service.get_signal(signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сигнал не найден",
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
            detail="Сигнал не найден",
        )
    if signal.status in {"rejected", "expired", "invalidated"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нельзя подтвердить сигнал в текущем статусе",
        )

    if request.mode == "real":
        real_execution = await real_execution_service.place_order(signal, request)
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=real_execution.message,
        )

    try:
        virtual_trade = trade_service.open_virtual_trade(signal, request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    updated_signal = signal_service.confirm_signal(
        signal_id,
        trade_id=virtual_trade.id,
        mode="virtual",
        note="Пользователь подтвердил сигнал в virtual mode",
    )
    if updated_signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сигнал не найден",
        )

    return ManualDecisionResponse(
        signal=updated_signal,
        virtual_trade=virtual_trade,
        message="Виртуальная сделка открыта",
    )


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
            detail="Сигнал не найден",
        )
    if current_signal.status == "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нельзя отклонить уже подтвержденный сигнал",
        )

    signal = signal_service.reject_signal(signal_id, note=request.reason)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сигнал не найден",
        )
    return ManualDecisionResponse(
        signal=signal,
        message="Сигнал отклонен",
    )
