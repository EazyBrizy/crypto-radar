from fastapi import APIRouter, HTTPException, Query, Response, status

from app.schemas.notification import (
    NotificationCreateRequest,
    NotificationResponse,
    NotificationTestRequest,
    NotificationUpdateRequest,
)
from app.services.notification_service import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    user_id: str = "demo_user",
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[NotificationResponse]:
    try:
        return notification_service.list_notifications(
            user_id,
            unread_only=unread_only,
            limit=limit,
        )
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def create_notification(request: NotificationCreateRequest) -> NotificationResponse:
    try:
        return await notification_service.create_notification(request)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/test", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def create_test_notification(request: NotificationTestRequest) -> NotificationResponse:
    try:
        return await notification_service.create_test_notification(request)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/read-all")
async def mark_all_notifications_read(user_id: str = "demo_user") -> dict[str, int]:
    try:
        return {"updated": notification_service.mark_all_read(user_id)}
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(notification_id: str) -> NotificationResponse:
    try:
        return notification_service.get_notification(notification_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.patch("/{notification_id}", response_model=NotificationResponse)
async def update_notification(
    notification_id: str,
    request: NotificationUpdateRequest,
) -> NotificationResponse:
    try:
        return notification_service.update_notification(notification_id, request)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(notification_id: str) -> Response:
    try:
        notification_service.delete_notification(notification_id)
    except (LookupError, ValueError) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
