from fastapi import APIRouter, HTTPException, status

from app.schemas.signal import RadarSignal
from app.services.signal_service import signal_service

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


@router.post("/{signal_id}/confirm", response_model=RadarSignal)
async def confirm_signal(signal_id: str) -> RadarSignal:
    signal = signal_service.confirm_signal(signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сигнал не найден",
        )
    return signal


@router.post("/{signal_id}/reject", response_model=RadarSignal)
async def reject_signal(signal_id: str) -> RadarSignal:
    signal = signal_service.reject_signal(signal_id)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сигнал не найден",
        )
    return signal
