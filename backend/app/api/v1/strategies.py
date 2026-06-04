from fastapi import APIRouter, HTTPException, Query, Request, status

from app.schemas.strategy import StrategyConfigResponse, StrategyConfigUpdateRequest
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import radar_status_event
from app.services.strategy_config_service import StrategyConfigValidationError, strategy_config_service

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/configs", response_model=list[StrategyConfigResponse])
async def list_strategy_configs(user_id: str = Query(default="demo_user")) -> list[StrategyConfigResponse]:
    try:
        return strategy_config_service.list_configs(user_id=user_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/configs/{config_id}", response_model=StrategyConfigResponse)
async def update_strategy_config(
    config_id: str,
    request: StrategyConfigUpdateRequest,
    app_request: Request,
) -> StrategyConfigResponse:
    try:
        config = strategy_config_service.update_config(config_id, request)
        await _reconfigure_scanner(app_request)
        return config
    except StrategyConfigValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def _reconfigure_scanner(request: Request) -> None:
    runner = getattr(request.app.state, "scanner_runner", None)
    if runner is None:
        return
    await runner.reconfigure()
    await realtime_event_broker.publish(radar_status_event({"status": "ok", **runner.scanner_status}))
