from fastapi import APIRouter

from app.services.radar_config_service import SUPPORTED_EXCHANGES
from app.services.market_scanner import DEFAULT_SYMBOLS
from app.schemas.candle import DEFAULT_TIMEFRAMES

router = APIRouter(prefix="/exchanges", tags=["exchanges"])


@router.get("")
async def list_exchanges() -> dict[str, list[str]]:
    return {
        "supported_exchanges": SUPPORTED_EXCHANGES,
        "supported_symbols": list(DEFAULT_SYMBOLS),
        "supported_timeframes": list(DEFAULT_TIMEFRAMES),
    }
