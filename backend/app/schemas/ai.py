from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SignalAIExplanationResponse(BaseModel):
    id: UUID
    signal_id: UUID
    model_provider: str
    model_name: str
    prompt_hash: str
    explanation_md: str
    risk_notes: str | None
    created_at: datetime


class SignalAIExplanationCreate(BaseModel):
    signal_id: UUID
    model_provider: str = Field(..., min_length=1)
    model_name: str = Field(..., min_length=1)
    prompt_hash: str = Field(..., min_length=1)
    explanation_md: str = Field(..., min_length=1)
    risk_notes: str | None = None


class SignalAIExplanationGenerateRequest(BaseModel):
    user_id: str = "demo_user"
    model_provider: str = "stub"
    model_name: str = "not-configured"
    context: dict[str, Any] = Field(default_factory=dict)


class AIExplanationNotReadyResponse(BaseModel):
    status: Literal["not_implemented"] = "not_implemented"
    message: str
    signal_id: UUID | None = None
    model_provider: str
    model_name: str
    storage_target: str = "signal_ai_explanations"
    orchestrator_required: bool = True
    details: dict[str, Any] = Field(default_factory=dict)
