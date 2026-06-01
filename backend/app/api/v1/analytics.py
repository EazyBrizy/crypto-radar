from fastapi import APIRouter, Query

from app.schemas.strategy_performance import StrategyEdgeProfile
from app.services.strategy_performance_service import strategy_performance_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/edge-profile", response_model=StrategyEdgeProfile)
async def get_strategy_edge_profile(
    strategy: str,
    exchange: str,
    symbol: str,
    timeframe: str,
    market_regime: str | None = None,
    score: float | None = Query(default=None, ge=0, le=100),
) -> StrategyEdgeProfile:
    return await strategy_performance_service.get_edge_profile(
        strategy=strategy,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        market_regime=market_regime,
        score=score,
    )
