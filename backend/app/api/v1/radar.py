from fastapi import APIRouter, Request

from app.schemas.candle import RadarConfig, RadarConfigUpdate
from app.schemas.signal import RadarResponse
from app.services.candle_service import candle_service
from app.services.radar_config_service import radar_config_service
from app.services.signal_service import signal_service

router = APIRouter(prefix="/radar", tags=["radar"])


@router.get("", response_model=RadarResponse)
async def get_radar() -> RadarResponse:
    return RadarResponse(signals=signal_service.list_active_signals())


@router.get("/config", response_model=RadarConfig)
async def get_radar_config() -> RadarConfig:
    return radar_config_service.get_config()


@router.put("/config", response_model=RadarConfig)
async def update_radar_config(
    update: RadarConfigUpdate,
    request: Request,
) -> RadarConfig:
    config = radar_config_service.update_config(update)
    candle_service.configure_timeframes(config.timeframes)
    runner = getattr(request.app.state, "scanner_runner", None)
    if runner is not None:
        await runner.reconfigure()
    return config
