from fastapi import APIRouter

from app.schemas.signal import RadarResponse
from app.services.signal_service import signal_service

router = APIRouter(prefix="/radar", tags=["radar"])


@router.get("", response_model=RadarResponse)
async def get_radar() -> RadarResponse:
    return RadarResponse(signals=signal_service.list_active_signals())
