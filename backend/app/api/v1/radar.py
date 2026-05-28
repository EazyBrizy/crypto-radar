from fastapi import APIRouter, Request

from app.schemas.candle import RadarConfig, RadarConfigUpdate
from app.schemas.signal import RadarResponse
from app.services.candle_service import candle_service
from app.services.message_broker import realtime_event_broker
from app.services.radar_config_service import radar_config_service
from app.services.realtime_events import radar_status_event
from app.services.signal_service import signal_service

router = APIRouter(prefix="/radar", tags=["radar"])


@router.get("", response_model=RadarResponse)
async def get_radar() -> RadarResponse:
    return RadarResponse(signals=signal_service.list_active_signals())


@router.get("/config", response_model=RadarConfig)
async def get_radar_config() -> RadarConfig:
    return radar_config_service.get_config()


@router.get("/status")
async def get_radar_status(request: Request) -> dict[str, object]:
    runner = getattr(request.app.state, "scanner_runner", None)
    return _scanner_status(runner)


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


@router.post("/scanner/start")
async def start_scanner(request: Request) -> dict[str, object]:
    runner = getattr(request.app.state, "scanner_runner", None)
    if runner is not None:
        runner.start()
    status = _scanner_status(runner)
    await realtime_event_broker.publish(radar_status_event(status))
    return status


@router.post("/scanner/stop")
async def stop_scanner(request: Request) -> dict[str, object]:
    runner = getattr(request.app.state, "scanner_runner", None)
    if runner is not None:
        await runner.stop()
    status = _scanner_status(runner)
    await realtime_event_broker.publish(radar_status_event(status))
    return status


def _scanner_status(
    runner: object | None,
    *,
    scanner_enabled: bool | None = None,
) -> dict[str, object]:
    enabled = runner is not None if scanner_enabled is None else scanner_enabled
    if runner is not None:
        return {
            "status": "ok",
            "scanner_enabled": enabled,
            **runner.scanner_status,
        }

    return {
        "status": "ok",
        "scanner_enabled": enabled,
        "scanner_running": False,
        "scanner_stopping": False,
        "processed_signals": 0,
        "exchanges": [],
        "symbols": [],
        "timeframes": [],
        "strategies": [],
        "ticks_processed": 0,
        "candles_updated": 0,
        "features_built": 0,
        "strategy_evaluations": 0,
        "signals_found": 0,
        "candles_seeded": 0,
        "last_tick_at": None,
        "last_signal_at": None,
        "last_exchange": None,
        "last_symbol": None,
        "last_price": None,
        "candle_history": {},
    }
