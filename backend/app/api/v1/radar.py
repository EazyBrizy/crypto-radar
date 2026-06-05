from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.candle import RadarConfig, RadarConfigUpdate
from app.schemas.risk import RadarDisplayMode
from app.schemas.signal import RadarResponse
from app.services.candle_service import candle_service
from app.services.message_broker import publish_realtime_event_background, realtime_event_broker
from app.services.current_user import current_user_identity_service
from app.services.radar_config_service import radar_config_service
from app.services.radar_service import RadarFilters, radar_service
from app.services.realtime_events import radar_status_event

router = APIRouter(prefix="/radar", tags=["radar"])


@router.get("", response_model=RadarResponse)
async def get_radar(
    request: Request,
    user_id: str | None = Query(default=None),
    radar_display_mode: RadarDisplayMode | None = Query(default=None),
    exchange: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    include_action_state: bool = Query(default=False),
) -> RadarResponse:
    try:
        current_user = current_user_identity_service.resolve_from_request(request)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    return radar_service.list_signals(
        user_id=user_id or current_user.user_id,
        mode=radar_display_mode,
        filters=RadarFilters(exchange=exchange, symbol=symbol, timeframe=timeframe),
        include_action_state=include_action_state,
    )


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
    candle_service.configure_timeframes(radar_config_service.selected_timeframes())
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
    publish_realtime_event_background(
        radar_status_event(status),
        broker=realtime_event_broker,
    )
    return status


@router.post("/scanner/stop")
async def stop_scanner(request: Request) -> dict[str, object]:
    runner = getattr(request.app.state, "scanner_runner", None)
    if runner is not None:
        await runner.stop()
    status = _scanner_status(runner)
    publish_realtime_event_background(
        radar_status_event(status),
        broker=realtime_event_broker,
    )
    return status


def _scanner_status(
    runner: object | None,
    *,
    scanner_enabled: bool | None = None,
) -> dict[str, object]:
    enabled = runner is not None if scanner_enabled is None else scanner_enabled
    config_status = _scanner_config_status()
    if runner is not None:
        runner_status = dict(runner.scanner_status)
        return {
            "status": "ok",
            "scanner_enabled": enabled,
            **config_status,
            **_scanner_runtime_defaults(
                scanner_running=bool(runner_status.get("scanner_running")),
            ),
            **runner_status,
        }

    return {
        "status": "ok",
        "scanner_enabled": enabled,
        "scanner_running": False,
        "scanner_stopping": False,
        "scanner_subscription_hash": config_status["scanner_subscription_hash"],
        "strategy_config_hash": radar_config_service.strategy_config_hash(),
        "processed_signals": 0,
        **_scanner_runtime_defaults(scanner_running=False),
        "exchanges": [],
        "symbols": [],
        "scan_pairs": config_status["scan_pairs"],
        "scanner_pairs_count": config_status["scanner_pairs_count"],
        "scanner_universe_source": config_status["scanner_universe_source"],
        "scanner_universe_warning": config_status["scanner_universe_warning"],
        "max_scanner_pairs": config_status["max_scanner_pairs"],
        "estimated_strategy_checks": config_status["estimated_strategy_checks"],
        "timeframes": [],
        "strategies": [],
        "ticks_processed": 0,
        "candles_updated": 0,
        "features_built": 0,
        "strategy_evaluations": 0,
        "signals_found": 0,
        "candles_seeded": 0,
        "last_signal_at": None,
        "last_exchange": None,
        "last_symbol": None,
        "last_price": None,
        "candle_history": {},
    }


def _scanner_config_status() -> dict[str, object]:
    try:
        universe = radar_config_service.scanner_universe(truncate_over_limit=True)
        subscription_hash = radar_config_service.scanner_subscription_hash(universe)
    except Exception as exc:
        return {
            "scanner_subscription_hash": "blocked",
            "scan_pairs": [],
            "scanner_pairs_count": 0,
            "scanner_universe_source": "blocked",
            "scanner_universe_warning": str(exc),
            "max_scanner_pairs": None,
            "estimated_strategy_checks": 0,
        }
    return {
        "scanner_subscription_hash": subscription_hash,
        "scan_pairs": [f"{exchange}:{symbol}" for exchange, symbol in universe.pairs],
        "scanner_pairs_count": len(universe.pairs),
        "scanner_universe_source": universe.source,
        "scanner_universe_warning": universe.warning,
        "max_scanner_pairs": universe.max_pairs,
        "estimated_strategy_checks": universe.estimated_strategy_checks,
    }


def _scanner_runtime_defaults(*, scanner_running: bool) -> dict[str, object]:
    return {
        "stage": "starting" if scanner_running else "stopped",
        "market_data_status": "waiting" if scanner_running else "offline",
        "warmup_total": 0,
        "warmup_completed": 0,
        "warmup_failed": 0,
        "warmup_started_at": None,
        "warmup_finished_at": None,
        "last_tick_at": None,
        "last_tick_age_seconds": None,
        "last_error": None,
        "market_stream_connected": False,
        "ws_connected": False,
    }
