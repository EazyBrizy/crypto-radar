from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.strategy import StrategyConfigResponse, StrategyConfigUpdateRequest
from app.services.strategy_config_service import strategy_config_service

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/configs", response_model=list[StrategyConfigResponse])
async def list_strategy_configs(user_id: str = Query(default="demo_user")) -> list[StrategyConfigResponse]:
    try:
        return strategy_config_service.list_configs(user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/configs/{config_id}", response_model=StrategyConfigResponse)
async def update_strategy_config(
    config_id: str,
    request: StrategyConfigUpdateRequest,
) -> StrategyConfigResponse:
    try:
        return strategy_config_service.update_config(config_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
