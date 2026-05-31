from __future__ import annotations

import logging

from app.repositories.signal_repository import SIGNAL_AUTO_ENTRY_FAILED_EVENT
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest
from app.services.execution_service import real_execution_service
from app.services.message_broker import realtime_event_broker
from app.services.realtime_events import signal_updated_event, trade_activated_event
from app.services.signal_service import SignalService, signal_service
from app.services.virtual_trading import VirtualExecutionRejected, virtual_trading_service

logger = logging.getLogger(__name__)


class SignalAutoEntryService:
    def __init__(self, signals: SignalService | None = None) -> None:
        self._signals = signals or signal_service

    async def execute_if_ready(self, signal: RadarSignal) -> RadarSignal | None:
        auto_entry = signal.auto_entry
        if auto_entry is None or not auto_entry.enabled or auto_entry.status != "pending":
            return None
        if signal.status not in {"actionable", "active", "entry_touched"}:
            return None

        request = ManualConfirmRequest.model_validate(auto_entry.request or {})
        request = request.model_copy(
            update={
                "mode": auto_entry.mode,
                "user_id": auto_entry.user_id,
                "auto_enter_on_confirmation": True,
            }
        )
        if request.mode == "virtual":
            return await self._execute_virtual(signal, request)
        return await self._execute_real(signal, request)

    async def _execute_virtual(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> RadarSignal | None:
        try:
            updated_signal, virtual_trade = virtual_trading_service.confirm_signal(signal, request)
        except VirtualExecutionRejected as exc:
            message = f"Auto-entry virtual execution rejected: {exc}"
            logger.info(message)
            updated = self._signals.update_auto_entry(
                signal.id,
                status="failed",
                message=message,
                event_type=SIGNAL_AUTO_ENTRY_FAILED_EVENT,
            )
            if updated is not None:
                await realtime_event_broker.publish(signal_updated_event(updated))
            return updated
        except ValueError as exc:
            message = f"Auto-entry virtual execution failed: {exc}"
            logger.info(message)
            updated = self._signals.update_auto_entry(
                signal.id,
                status="failed",
                message=message,
                event_type=SIGNAL_AUTO_ENTRY_FAILED_EVENT,
            )
            if updated is not None:
                await realtime_event_broker.publish(signal_updated_event(updated))
            return updated

        await realtime_event_broker.publish(signal_updated_event(updated_signal))
        await realtime_event_broker.publish(trade_activated_event(virtual_trade))
        return updated_signal

    async def _execute_real(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
    ) -> RadarSignal | None:
        real_execution = await real_execution_service.place_order(signal, request)
        if real_execution.status == "not_implemented":
            message = real_execution.message
            status = "failed"
        elif real_execution.status == "risk_failed":
            message = real_execution.message
            status = "failed"
        else:
            message = "Real auto-entry attempt finished"
            status = "triggered"

        updated = self._signals.update_auto_entry(
            signal.id,
            status=status,
            message=message,
            real_execution=real_execution.model_dump(mode="json"),
            event_type=SIGNAL_AUTO_ENTRY_FAILED_EVENT if status == "failed" else "signal.updated",
        )
        if updated is not None:
            await realtime_event_broker.publish(signal_updated_event(updated))
        return updated


auto_entry_service = SignalAutoEntryService()
