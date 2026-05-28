import asyncio

from fastapi import APIRouter

from app.core.health import get_storage_health

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def get_api_health() -> dict[str, object]:
    storage = await asyncio.to_thread(get_storage_health)
    return {
        "status": storage["status"],
        "storage": storage,
    }


@router.get("/storage")
async def get_storage_health_status() -> dict[str, object]:
    return await asyncio.to_thread(get_storage_health)
