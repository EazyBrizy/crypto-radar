from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.risk import RiskPreviewRequest, RiskPreviewResponse, RiskStateResponse
from app.services.risk_preview import risk_preview_service
from app.services.risk_state import risk_state_service

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/preview", response_model=RiskPreviewResponse)
async def preview_risk(request: RiskPreviewRequest) -> RiskPreviewResponse:
    try:
        return risk_preview_service.preview(request)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/state", response_model=RiskStateResponse)
async def get_risk_state(
    user_id: str = "demo_user",
    mode: str | None = Query(default=None, pattern="^(virtual|real)$"),
    exchange: str | None = None,
    symbol: str | None = None,
    side: str | None = Query(default=None, pattern="^(long|short)$"),
    instrument_type: str | None = Query(default=None, pattern="^(spot|futures|virtual)$"),
) -> RiskStateResponse:
    try:
        return risk_state_service.get_state(
            user_id=user_id,
            mode=mode,
            exchange=exchange,
            symbol=symbol,
            side=side,
            instrument_type=instrument_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
