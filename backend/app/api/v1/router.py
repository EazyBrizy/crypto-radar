from fastapi import APIRouter

from app.api.v1 import (
    ai,
    analytics,
    backtests,
    billing,
    candles,
    exchanges,
    health,
    notifications,
    radar,
    realtime,
    risk,
    signals,
    strategies,
    strategy_lab,
    strategy_tests,
    trades,
    users,
    watchlists,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(ai.router)
api_router.include_router(analytics.router)
api_router.include_router(backtests.router)
api_router.include_router(billing.router)
api_router.include_router(candles.router)
api_router.include_router(exchanges.router)
api_router.include_router(health.router)
api_router.include_router(notifications.router)
api_router.include_router(radar.router)
api_router.include_router(realtime.router)
api_router.include_router(risk.router)
api_router.include_router(signals.router)
api_router.include_router(strategies.router)
api_router.include_router(strategy_lab.router)
api_router.include_router(strategy_tests.router)
api_router.include_router(trades.router)
api_router.include_router(users.router)
api_router.include_router(watchlists.router)
