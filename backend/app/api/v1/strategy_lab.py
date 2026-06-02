from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.strategy_lab import (
    StrategyLabComparisonResult,
    StrategyLabMatrixRequest,
    StrategyLabRunRequest,
)
from app.services.strategy_test_lab import StrategyTestLabService, strategy_test_lab_service


router = APIRouter(prefix="/strategy-lab", tags=["strategy-lab"])


def get_strategy_test_lab_service() -> StrategyTestLabService:
    return strategy_test_lab_service


@router.post("/run", response_model=StrategyLabComparisonResult)
async def run_strategy_lab(
    request: StrategyLabRunRequest,
    service: StrategyTestLabService = Depends(get_strategy_test_lab_service),
) -> StrategyLabComparisonResult:
    try:
        return service.run(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/matrix", response_model=StrategyLabComparisonResult)
async def run_strategy_lab_matrix(
    request: StrategyLabMatrixRequest,
    service: StrategyTestLabService = Depends(get_strategy_test_lab_service),
) -> StrategyLabComparisonResult:
    try:
        return service.run_matrix(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
