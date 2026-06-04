from __future__ import annotations

from pydantic import BaseModel


class LifecycleTrace(BaseModel):
    signal_id: str | None = None
    pending_entry_intent_id: str | None = None
    risk_decision_id: str | None = None
    audit_id: str | None = None
    virtual_trade_id: str | None = None
    real_order_id: str | None = None
    exit_event_id: str | None = None
