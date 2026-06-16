from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrategyTestWorkerLeaseState(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "idle"
    worker_id: str | None = None
    run_id: UUID | None = None
    run_status: str | None = None
    test_type: str | None = None
    worker_attempt: int = Field(default=0, ge=0)
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    lease_active: bool = False
    lease_expires_in_seconds: float | None = None
    runtime_status: str | None = None
    last_heartbeat_reason: str | None = None
    last_forward_event: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    scanner_enabled: bool = False
    scanner_running: bool = False
    scanner_stopping: bool = False
    forward_strategy_test_running: bool = False
    forward_strategy_test_stopping: bool = False
    forward_strategy_test_last_result: dict[str, Any] = Field(default_factory=dict)
    strategy_test_worker: StrategyTestWorkerLeaseState = Field(default_factory=StrategyTestWorkerLeaseState)
