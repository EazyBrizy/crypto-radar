from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.schemas.ai import (
    AIExplanationNotReadyResponse,
    SignalAIExplanationGenerateRequest,
    SignalAIExplanationResponse,
)
from app.services.ai_explanation_service import AIExplanationNotReadyError, ai_explanation_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/signals/{signal_id}/explanations", response_model=list[SignalAIExplanationResponse])
async def list_signal_ai_explanations(
    signal_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SignalAIExplanationResponse]:
    try:
        return ai_explanation_service.list_for_signal(signal_id, limit=limit)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/signals/{signal_id}/explanations/generate",
    response_model=SignalAIExplanationResponse,
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"model": AIExplanationNotReadyResponse}},
)
async def generate_signal_ai_explanation(
    signal_id: str,
    request: SignalAIExplanationGenerateRequest | None = None,
) -> SignalAIExplanationResponse | JSONResponse:
    try:
        return ai_explanation_service.generate_for_signal(
            signal_id,
            request or SignalAIExplanationGenerateRequest(),
        )
    except AIExplanationNotReadyError as exc:
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=exc.response.model_dump(mode="json"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
