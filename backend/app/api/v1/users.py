from fastapi import APIRouter, HTTPException, status

from app.schemas.user import UserProfileResponse, UserSettingsPatchRequest
from app.services.user_service import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(user_id: str = "demo_user") -> UserProfileResponse:
    try:
        return user_service.get_profile(user_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/me/settings", response_model=UserProfileResponse)
async def update_current_user_settings(
    request: UserSettingsPatchRequest,
    user_id: str = "demo_user",
) -> UserProfileResponse:
    try:
        return user_service.update_settings(request, user_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
