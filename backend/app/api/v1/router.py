from fastapi import APIRouter

from app.api.v1 import candles, exchanges, radar, signals

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(candles.router)
api_router.include_router(exchanges.router)
api_router.include_router(radar.router)
api_router.include_router(signals.router)
