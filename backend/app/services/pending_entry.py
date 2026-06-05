from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.database import SessionLocal
from app.domain.pending_entry_intent import is_terminal_pending_entry_intent_status
from app.domain.signal_status import is_market_opportunity_status, is_terminal_signal_status
from app.models.pending_entry import PendingEntryIntent
from app.repositories.pending_entry_repository import PendingEntryIntentRepository
from app.schemas.pending_entry import (
    PendingEntryIntentCreate,
    PendingEntryIntentMode,
    PendingEntryIntentRead,
    PendingEntryIntentStatus,
)
from app.schemas.risk import ResolvedExecutionProfile
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest
from app.schemas.trade_plan import TradePlan, build_trade_plan_from_legacy_fields
from app.services.trade_plan_fingerprint import (
    default_material_change_policy,
    evaluate_pending_entry_material_change,
    material_change_policy_from_snapshot,
    normalized_pending_entry_payload,
    fingerprint_signal_trade_plan,
)
from app.schemas.user import RiskManagementSettings
from app.services.risk_management import (
    execution_profile_resolver,
    get_user_risk_management_settings,
    request_risk_override_to_execution_settings,
)
from app.services.pending_entry_events import PendingEntryUpdatePublisher, pending_entry_update_publisher
from app.services.signal_risk_reward import ensure_signal_execution_eligible
from app.services.strategy_config_service import strategy_config_service
from app.services.user_identity import resolve_app_user_uuid

SignalLoader = Callable[[str], RadarSignal | None]
RiskSettingsProvider = Callable[[str], RiskManagementSettings]
UserProfileProvider = Callable[[str], Any]
AutoEntryUpdater = Callable[..., Any]
AutoEntryArm = Callable[..., Any]

TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON = (
    "Trade plan changed after acceptance; reconfirmation required."
)
REAL_PENDING_NOT_IMPLEMENTED_REASON_CODE = "REAL_PENDING_NOT_IMPLEMENTED"


class RealPendingEntryNotImplemented(ValueError):
    reason_code = REAL_PENDING_NOT_IMPLEMENTED_REASON_CODE

    def __init__(self) -> None:
        super().__init__("Tick-driven real pending entry execution is not implemented.")

logger = logging.getLogger(__name__)


class PendingEntryService:
    publishes_pending_entry_events = True

    def __init__(
        self,
        repository: PendingEntryIntentRepository | None = None,
        *,
        session_factory: sessionmaker[Session] | None = None,
        signal_loader: SignalLoader | None = None,
        user_profile_provider: UserProfileProvider | None = None,
        risk_settings_provider: RiskSettingsProvider | None = None,
        event_publisher: PendingEntryUpdatePublisher | None = None,
    ) -> None:
        self._repository = repository or PendingEntryIntentRepository()
        self._session_factory = session_factory or getattr(self._repository, "_session_factory", SessionLocal)
        self._signal_loader = signal_loader
        self._user_profile_provider = user_profile_provider
        self._risk_settings_provider = risk_settings_provider or get_user_risk_management_settings
        self._event_publisher = event_publisher or pending_entry_update_publisher

    def create_intent(self, intent: PendingEntryIntentCreate) -> PendingEntryIntentRead:
        created = self._repository.create_intent(intent)
        self._publish_update(created)
        return created

    def get_by_id(self, intent_id: str | UUID) -> PendingEntryIntentRead | None:
        return self._repository.get_by_id(intent_id)

    def list_pending_for_market(self, exchange: str, symbol: str) -> list[PendingEntryIntentRead]:
        return self._repository.list_pending_for_market(exchange, symbol)

    def list_active_for_user(
        self,
        *,
        user_id: str | UUID,
        mode: PendingEntryIntentMode | None = None,
        limit: int = 100,
    ) -> list[PendingEntryIntentRead]:
        user_uuid = self._resolve_user_uuid(user_id)
        list_active = getattr(self._repository, "list_active_for_user", None)
        if list_active is None:
            return []
        return list_active(user_id=user_uuid, mode=mode, limit=limit)

    def list_history_for_user(
        self,
        *,
        user_id: str | UUID,
        mode: PendingEntryIntentMode | None = None,
        limit: int = 50,
    ) -> list[PendingEntryIntentRead]:
        user_uuid = self._resolve_user_uuid(user_id)
        list_history = getattr(self._repository, "list_history_for_user", None)
        if list_history is None:
            return []
        return list_history(user_id=user_uuid, mode=mode, limit=limit)

    def transition_status(
        self,
        intent_id: str | UUID,
        *,
        status: PendingEntryIntentStatus,
        failure_reason: str | None = None,
        filled_trade_id: str | UUID | None = None,
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        updated = self._repository.transition_status(
            intent_id,
            status=status,
            failure_reason=failure_reason,
            filled_trade_id=filled_trade_id,
            now=now,
        )
        if updated is not None:
            self._publish_update(updated)
        return updated

    def lock_for_trigger(self, intent_id: str | UUID, *, session: Session) -> PendingEntryIntent | None:
        return self._repository.lock_for_trigger(intent_id, session=session)

    def get_active_for_signal(
        self,
        *,
        signal_id: str | UUID,
        user_id: str | UUID,
        mode: PendingEntryIntentMode = "virtual",
    ) -> PendingEntryIntentRead | None:
        user_uuid = self._resolve_user_uuid(user_id)
        return self._get_active_intent(
            user_id=user_uuid,
            signal_id=signal_id,
            mode=_pending_entry_mode(mode),
        )

    def list_history_for_signal(
        self,
        *,
        signal_id: str | UUID,
        user_id: str | UUID,
        mode: PendingEntryIntentMode = "virtual",
    ) -> list[PendingEntryIntentRead]:
        user_uuid = self._resolve_user_uuid(user_id)
        list_history = getattr(self._repository, "list_history_for_user_signal_mode", None)
        if list_history is None:
            return []
        return list_history(
            signal_id=signal_id,
            user_id=user_uuid,
            mode=_pending_entry_mode(mode),
        )

    def list_active_for_signal_user(
        self,
        *,
        signal_id: str | UUID,
        user_id: str | UUID,
    ) -> list[PendingEntryIntentRead]:
        user_uuid = self._resolve_user_uuid(user_id)
        list_for_user = getattr(self._repository, "list_active_for_signal_user", None)
        if list_for_user is not None:
            return list_for_user(signal_id=signal_id, user_id=user_uuid)
        return [
            intent
            for intent in self._repository.list_active_for_signal(signal_id)
            if intent.user_id == user_uuid
        ]

    def cancel_intent(
        self,
        intent_id: str | UUID,
        *,
        user_id: str | UUID,
        reason: str = "Cancelled by user.",
    ) -> PendingEntryIntentRead:
        intent = self._get_visible_intent(intent_id, user_id=user_id)
        if is_terminal_pending_entry_intent_status(intent.status):
            return intent
        updated = self.transition_status(
            intent.id,
            status="cancelled",
            failure_reason=reason,
        )
        if updated is None:
            raise LookupError("Pending entry intent is not found")
        return updated

    def arm_signal_workflow(
        self,
        *,
        signal_id: str | UUID,
        request: ManualConfirmRequest | dict[str, Any] | None = None,
        auto_entry_arm: AutoEntryArm | None = None,
    ) -> PendingEntryIntentRead:
        request_model = _manual_confirm_request(request)
        raw_mode = str(request_model.mode or "virtual").strip().lower()
        mode: PendingEntryIntentMode = "real" if raw_mode == "real" else "virtual"
        if mode == "real":
            raise RealPendingEntryNotImplemented()
        signal = self._load_signal(signal_id)
        if signal is None:
            raise LookupError("Signal is not found")
        execution_profile = self.resolve_execution_profile(signal, request_model, mode=mode)
        ensure_signal_execution_eligible(
            signal,
            mode=mode,
            rr_guard_mode=execution_profile.rr_guard_mode,
        )
        intent = self.arm_from_signal(
            user_id=request_model.user_id,
            signal_id=signal.id,
            mode=mode,
            request=request_model,
            execution_profile=execution_profile,
        )
        if auto_entry_arm is not None:
            mirror_request = request_model.model_dump(mode="json")
            auto_entry_arm(str(signal.id), mirror_request, pending_entry_intent=intent)
        return intent

    def reconfirm_intent(
        self,
        intent_id: str | UUID,
        *,
        request: ManualConfirmRequest | dict[str, Any] | None = None,
        auto_entry_arm: AutoEntryArm | None = None,
    ) -> PendingEntryIntentRead:
        request_model = _manual_confirm_request(request)
        intent = self._get_visible_intent(intent_id, user_id=request_model.user_id)
        if intent.mode == "real":
            raise RealPendingEntryNotImplemented()
        if intent.status != "requires_reconfirmation":
            if is_terminal_pending_entry_intent_status(intent.status):
                existing = self._get_active_intent(
                    user_id=intent.user_id,
                    signal_id=intent.signal_id,
                    mode=intent.mode,
                )
                if existing is not None:
                    return existing
                raise ValueError("Terminal pending entry intent cannot be reconfirmed")
            return intent

        signal = self._load_signal(intent.signal_id)
        if signal is None:
            raise LookupError("Signal is not found")
        if is_terminal_signal_status(signal.status):
            raise ValueError("Signal cannot be reconfirmed for pending entry in terminal status")
        if not is_market_opportunity_status(signal.status):
            raise ValueError("Signal is not a market opportunity")

        next_request = request_model.model_copy(
            update={
                "mode": intent.mode,
                "user_id": str(intent.user_id),
                "auto_enter_on_confirmation": True,
            }
        )
        execution_profile = self.resolve_execution_profile(signal, next_request, mode=intent.mode)
        ensure_signal_execution_eligible(
            signal,
            mode=intent.mode,
            rr_guard_mode=execution_profile.rr_guard_mode,
        )
        accepted_plan = _accepted_trade_plan(signal)
        trade_plan_hash = accepted_trade_plan_hash(signal)
        accepted_snapshot = _accepted_execution_envelope(
            accepted_plan.snapshot,
            signal=signal,
            trade_plan_hash=trade_plan_hash,
            execution_profile_snapshot=execution_profile.model_dump(mode="json"),
            accepted_at=datetime.now(timezone.utc),
        )
        request_snapshot = _request_snapshot(next_request, mode=intent.mode)
        request_snapshot = _with_reconfirmation_lifecycle_event(
            request_snapshot=request_snapshot,
            previous_snapshot=intent.request_snapshot,
            previous_intent=intent,
            accepted_trade_plan_hash=trade_plan_hash,
            signal=signal,
        )
        update_reconfirmed = getattr(self._repository, "update_reconfirmed_acceptance", None)
        if update_reconfirmed is None:
            raise RuntimeError("Pending entry repository does not support reconfirmation updates")
        updated = update_reconfirmed(
            intent.id,
            entry_min=accepted_plan.entry_min,
            entry_max=accepted_plan.entry_max,
            entry_price_policy=accepted_plan.entry_price_policy,
            stop_loss=accepted_plan.stop_loss,
            targets_snapshot=accepted_plan.targets_snapshot,
            accepted_trade_plan_snapshot=accepted_snapshot,
            accepted_trade_plan_hash=trade_plan_hash,
            accepted_signal_status=signal.status,
            accepted_signal_version=accepted_plan.signal_version,
            accepted_signal_fingerprint=_signal_fingerprint(signal, trade_plan_hash),
            execution_profile_snapshot=execution_profile.model_dump(mode="json"),
            request_snapshot=request_snapshot,
            expires_at=signal.expires_at,
        )
        if updated is None:
            raise LookupError("Pending entry intent is not found")
        self._publish_update(updated, message="Pending entry reconfirmed.")
        if auto_entry_arm is not None:
            auto_entry_arm(
                str(signal.id),
                next_request.model_dump(mode="json"),
                pending_entry_intent=updated,
            )
        return updated

    def reconcile_signal_trade_plan(
        self,
        signal: RadarSignal,
        *,
        auto_entry_updater: AutoEntryUpdater | None = None,
    ) -> list[PendingEntryIntentRead]:
        list_active = getattr(self._repository, "list_active_for_signal", None)
        if list_active is None:
            return []

        changed: list[PendingEntryIntentRead] = []
        for intent in list_active(signal.id):
            if intent.status == "requires_reconfirmation":
                continue
            if is_terminal_signal_status(signal.status):
                status: PendingEntryIntentStatus = "expired" if signal.status == "expired" else "cancelled"
                reason = f"Signal is terminal during pending entry reconciliation: {signal.status}."
                self._update_current_market_review(
                    intent,
                    signal=signal,
                    material_summary=_terminal_signal_change_summary(signal),
                    material_change_pending_review=True,
                )
                updated = self.transition_status(
                    intent.id,
                    status=status,
                    failure_reason=reason,
                )
                if updated is not None:
                    changed.append(updated)
                continue

            material = _material_change_evaluation(intent, signal)
            if not material.material:
                if (
                    material.current_hash is not None
                    and intent.accepted_trade_plan_hash != material.current_hash
                ):
                    self._update_current_market_review(
                        intent,
                        signal=signal,
                        material_summary=material.summary,
                        material_change_pending_review=False,
                    )
                continue
            reason = _reconfirmation_reason(material.error)
            self._update_current_market_review(
                intent,
                signal=signal,
                material_summary=material.summary,
                material_change_pending_review=True,
            )
            updated = self.transition_status(
                intent.id,
                status="requires_reconfirmation",
                failure_reason=reason,
            )
            if updated is not None:
                changed.append(updated)

        if changed and auto_entry_updater is not None:
            auto_entry_updater(
                str(signal.id),
                status=changed[0].status,
                message=changed[0].failure_reason,
            )
        return changed

    def resolve_execution_profile(
        self,
        signal: RadarSignal,
        request: ManualConfirmRequest,
        *,
        mode: PendingEntryIntentMode,
    ) -> ResolvedExecutionProfile:
        risk_settings = self._risk_settings_provider(request.user_id)
        strategy_risk_settings, _ = _strategy_risk_settings(signal, user_id=request.user_id)
        return execution_profile_resolver.resolve(
            user_risk_settings=risk_settings,
            strategy_execution_settings=strategy_risk_settings,
            request_override=request_risk_override_to_execution_settings(request.risk_override),
            mode=mode,
            instrument_type=_request_instrument_type(request),
            strategy=signal.strategy,
        )

    def arm_from_signal(
        self,
        *,
        user_id: str | UUID,
        signal_id: str | UUID,
        mode: PendingEntryIntentMode,
        request: ManualConfirmRequest | dict[str, Any],
        execution_profile: ResolvedExecutionProfile,
    ) -> PendingEntryIntentRead:
        signal = self._load_signal(signal_id)
        if signal is None:
            raise LookupError("Signal is not found")
        if mode == "real":
            raise RealPendingEntryNotImplemented()
        if is_terminal_signal_status(signal.status):
            raise ValueError("Signal cannot be armed for pending entry in terminal status")
        if not is_market_opportunity_status(signal.status):
            raise ValueError("Signal is not a market opportunity")

        user_uuid = self._resolve_user_uuid(user_id)
        signal_uuid = _parse_uuid_or_raise(signal.id, "signal_id")
        request_snapshot = _request_snapshot(request, mode=mode)
        accepted_plan = _accepted_trade_plan(signal)
        trade_plan_hash = accepted_trade_plan_hash(signal)
        accepted_snapshot = _accepted_execution_envelope(
            accepted_plan.snapshot,
            signal=signal,
            trade_plan_hash=trade_plan_hash,
            execution_profile_snapshot=execution_profile.model_dump(mode="json"),
            accepted_at=datetime.now(timezone.utc),
        )
        existing = self._get_active_intent(
            user_id=user_uuid,
            signal_id=signal_uuid,
            mode=mode,
        )
        if existing is not None:
            return existing
        idempotency_key = _idempotency_key(
            user_id=user_uuid,
            signal_id=signal_uuid,
            mode=mode,
            trade_plan_hash=trade_plan_hash,
            attempt=self._next_idempotency_attempt(
                user_id=user_uuid,
                signal_id=signal_uuid,
                mode=mode,
                trade_plan_hash=trade_plan_hash,
            ),
        )

        intent = PendingEntryIntentCreate(
            user_id=user_uuid,
            signal_id=signal_uuid,
            strategy_id=None,
            mode=mode,
            status="pending",
            exchange=signal.exchange,
            symbol=signal.symbol,
            side=signal.direction,
            entry_min=accepted_plan.entry_min,
            entry_max=accepted_plan.entry_max,
            entry_price_policy=accepted_plan.entry_price_policy,
            stop_loss=accepted_plan.stop_loss,
            targets_snapshot=accepted_plan.targets_snapshot,
            accepted_trade_plan_snapshot=accepted_snapshot,
            accepted_trade_plan_hash=trade_plan_hash,
            accepted_signal_status=signal.status,
            accepted_signal_version=accepted_plan.signal_version,
            accepted_signal_fingerprint=_signal_fingerprint(signal, trade_plan_hash),
            execution_profile_snapshot=execution_profile.model_dump(mode="json"),
            request_snapshot=request_snapshot,
            idempotency_key=idempotency_key,
            expires_at=signal.expires_at,
        )
        return self.create_intent(intent)

    def _load_signal(self, signal_id: str | UUID) -> RadarSignal | None:
        if self._signal_loader is not None:
            return self._signal_loader(str(signal_id))
        from app.services.signal_service import signal_service

        return signal_service.get_signal(str(signal_id))

    def _resolve_user_uuid(self, user_id: str | UUID) -> UUID:
        with self._session_factory() as session:
            return resolve_app_user_uuid(session, user_id)

    def _get_active_intent(
        self,
        *,
        user_id: UUID,
        signal_id: str | UUID,
        mode: PendingEntryIntentMode,
    ) -> PendingEntryIntentRead | None:
        get_active = getattr(self._repository, "get_active_for_user_signal_mode", None)
        if get_active is None:
            return None
        return get_active(user_id=user_id, signal_id=signal_id, mode=mode)

    def _next_idempotency_attempt(
        self,
        *,
        user_id: UUID,
        signal_id: UUID,
        mode: PendingEntryIntentMode,
        trade_plan_hash: str,
    ) -> int:
        list_history = getattr(self._repository, "list_history_for_user_signal_mode", None)
        if list_history is None:
            return 0
        return sum(
            1
            for intent in list_history(signal_id=signal_id, user_id=user_id, mode=mode)
            if intent.accepted_trade_plan_hash == trade_plan_hash
        )

    def _get_visible_intent(
        self,
        intent_id: str | UUID,
        *,
        user_id: str | UUID,
    ) -> PendingEntryIntentRead:
        intent = self.get_by_id(intent_id)
        if intent is None:
            raise LookupError("Pending entry intent is not found")
        user_uuid = self._resolve_user_uuid(user_id)
        if intent.user_id != user_uuid:
            raise PermissionError("Pending entry intent belongs to another user")
        return intent

    def _publish_update(
        self,
        intent: PendingEntryIntentRead,
        *,
        message: str | None = None,
    ) -> None:
        try:
            self._event_publisher.publish_update(intent, message=message)
        except Exception as exc:
            logger.warning("Pending entry realtime event publish failed: %s", exc)

    def _update_current_market_review(
        self,
        intent: PendingEntryIntentRead,
        *,
        signal: RadarSignal,
        material_summary: dict[str, Any],
        material_change_pending_review: bool,
    ) -> PendingEntryIntentRead | None:
        updater = getattr(self._repository, "update_market_review_snapshot", None)
        if updater is None:
            return None
        request_snapshot = _request_snapshot_with_market_review(
            intent.request_snapshot,
            signal=signal,
            material_summary=material_summary,
            material_change_pending_review=material_change_pending_review,
        )
        try:
            return updater(intent.id, request_snapshot=request_snapshot)
        except Exception as exc:
            logger.warning("Pending entry market review snapshot update failed: %s", exc)
            return None


PendingEntryIntentService = PendingEntryService


def accepted_trade_plan_hash(signal: RadarSignal) -> str:
    return fingerprint_signal_trade_plan(signal).hash


class _AcceptedTradePlan:
    def __init__(
        self,
        *,
        snapshot: dict[str, Any],
        entry_min: Decimal,
        entry_max: Decimal,
        entry_price_policy: str,
        stop_loss: Decimal,
        targets_snapshot: list[dict[str, Any]],
        signal_version: str | None,
    ) -> None:
        self.snapshot = snapshot
        self.entry_min = entry_min
        self.entry_max = entry_max
        self.entry_price_policy = entry_price_policy
        self.stop_loss = stop_loss
        self.targets_snapshot = targets_snapshot
        self.signal_version = signal_version


def _accepted_trade_plan(signal: RadarSignal) -> _AcceptedTradePlan:
    trade_plan = _trade_plan_from_signal(signal)
    entry_min = _positive_decimal(
        _first_present(trade_plan.entry.min_price, signal.entry_min, trade_plan.entry.price),
        "entry_min",
    )
    entry_max = _positive_decimal(
        _first_present(trade_plan.entry.max_price, signal.entry_max, trade_plan.entry.price),
        "entry_max",
    )
    if entry_max < entry_min:
        raise ValueError("Pending entry requires entry_max greater than or equal to entry_min")
    stop_loss = _positive_decimal(
        _first_present(
            trade_plan.stop_loss,
            signal.stop_loss,
            trade_plan.invalidation.hard_stop if trade_plan.invalidation is not None else None,
            trade_plan.invalidation.price if trade_plan.invalidation is not None else None,
        ),
        "stop_loss",
    )
    targets_snapshot = _targets_snapshot(trade_plan)
    if not targets_snapshot:
        raise ValueError("Pending entry requires at least one take-profit target price")

    snapshot = trade_plan.model_dump(mode="json", exclude_none=True)
    entry_snapshot = dict(snapshot.get("entry") or {})
    entry_snapshot.update(
        {
            "min_price": _decimal_string(entry_min),
            "max_price": _decimal_string(entry_max),
            "price": _decimal_string((entry_min + entry_max) / Decimal("2")),
        }
    )
    snapshot.update(
        {
            "entry": entry_snapshot,
            "stop_loss": _decimal_string(stop_loss),
            "targets": targets_snapshot,
            "accepted_legacy_fields": {
                "entry_min": _decimal_string(entry_min),
                "entry_max": _decimal_string(entry_max),
                "stop_loss": _decimal_string(stop_loss),
                "take_profit_1": _decimal_string_or_none(signal.take_profit_1),
                "take_profit_2": _decimal_string_or_none(signal.take_profit_2),
            },
        }
    )
    return _AcceptedTradePlan(
        snapshot=snapshot,
        entry_min=entry_min,
        entry_max=entry_max,
        entry_price_policy="accepted_entry_zone",
        stop_loss=stop_loss,
        targets_snapshot=targets_snapshot,
        signal_version=_signal_version(trade_plan),
    )


def _accepted_execution_envelope(
    snapshot: dict[str, Any],
    *,
    signal: RadarSignal,
    trade_plan_hash: str,
    execution_profile_snapshot: dict[str, Any],
    accepted_at: datetime,
) -> dict[str, Any]:
    envelope = dict(snapshot)
    material_policy = material_change_policy_from_snapshot(envelope)
    signal_snapshot = {
        "id": str(signal.id),
        "status": signal.status,
        "version": _signal_version(_trade_plan_from_signal(signal)),
        "fingerprint": _signal_fingerprint(signal, trade_plan_hash),
        "created_at": signal.created_at.isoformat(),
        "updated_at": signal.updated_at.isoformat(),
        "expires_at": signal.expires_at.isoformat() if signal.expires_at is not None else None,
        "score": signal.score,
        "confidence": signal.confidence,
        "risk_reward": signal.risk_reward,
        "first_target_rr": signal.first_target_rr,
        "final_target_rr": signal.final_target_rr,
        "selected_rr": signal.selected_rr,
        "selected_rr_target": signal.selected_rr_target,
        "min_rr_ratio": signal.min_rr_ratio,
    }
    envelope.update(
        {
            "exchange": signal.exchange.strip().lower(),
            "symbol": signal.symbol.replace("/", "").replace(":PERP", "").upper(),
            "side": signal.direction,
            "accepted_at": accepted_at.isoformat(),
            "accepted_created_at": accepted_at.isoformat(),
            "accepted_expires_at": signal.expires_at.isoformat() if signal.expires_at is not None else None,
            "accepted_trade_plan_hash": trade_plan_hash,
            "accepted_signal": signal_snapshot,
            "execution_profile_snapshot": execution_profile_snapshot,
            "material_change_policy": material_policy,
        }
    )
    return envelope


def _material_change_evaluation(intent: PendingEntryIntentRead, signal: RadarSignal):
    accepted_payload = normalized_pending_entry_payload(
        exchange=intent.exchange,
        symbol=intent.symbol,
        side=intent.side,
        entry_min=intent.entry_min,
        entry_max=intent.entry_max,
        stop_loss=intent.stop_loss,
        targets_snapshot=intent.targets_snapshot,
    )
    return evaluate_pending_entry_material_change(
        accepted_payload=accepted_payload,
        current_signal=signal,
        policy=material_change_policy_from_snapshot(intent.accepted_trade_plan_snapshot),
        execution_profile_snapshot=intent.execution_profile_snapshot,
        mode=intent.mode,
    )


def _terminal_signal_change_summary(signal: RadarSignal) -> dict[str, Any]:
    return {
        "material": True,
        "changed_fields": ["signal.status"],
        "changes": [
            {
                "field": "signal.status",
                "previous": None,
                "accepted": None,
                "current": signal.status,
                "tolerance": {"type": "non_terminal_signal"},
                "severity": "blocking",
                "reason_code": "signal_terminal",
            }
        ],
        "policy": default_material_change_policy(),
    }


def _request_snapshot_with_market_review(
    request_snapshot: dict[str, Any],
    *,
    signal: RadarSignal,
    material_summary: dict[str, Any],
    material_change_pending_review: bool,
) -> dict[str, Any]:
    snapshot = dict(request_snapshot or {})
    now = datetime.now(timezone.utc)
    current_market_snapshot = {
        "observed_at": now.isoformat(),
        "signal_id": str(signal.id),
        "status": signal.status,
        "exchange": signal.exchange,
        "symbol": signal.symbol,
        "side": signal.direction,
        "updated_at": signal.updated_at.isoformat(),
        "expires_at": signal.expires_at.isoformat() if signal.expires_at is not None else None,
        "material_change_pending_review": material_change_pending_review,
        "material_change_summary": material_summary,
    }
    if isinstance(material_summary.get("current_trade_plan_hash"), str):
        current_market_snapshot["trade_plan_hash"] = material_summary["current_trade_plan_hash"]
    snapshot["current_market_snapshot"] = current_market_snapshot
    snapshot["material_change_pending_review"] = material_change_pending_review
    raw_warnings = snapshot.get("pending_entry_warnings")
    warnings = list(raw_warnings) if isinstance(raw_warnings, list) else []
    if material_change_pending_review:
        warnings.append("Pending entry material change requires user review.")
    elif material_summary.get("current_trade_plan_hash") is not None:
        warnings.append("Pending entry live signal changed without material execution-plan impact.")
    snapshot["pending_entry_warnings"] = _dedupe_strings(warnings)[-20:]
    return snapshot


def _trade_plan_from_signal(signal: RadarSignal) -> TradePlan:
    if signal.trade_plan is not None:
        return signal.trade_plan
    return build_trade_plan_from_legacy_fields(
        entry_min=signal.entry_min,
        entry_max=signal.entry_max,
        stop_loss=signal.stop_loss,
        take_profit_1=signal.take_profit_1,
        take_profit_2=signal.take_profit_2,
        risk_reward=signal.risk_reward,
        first_target_rr=signal.first_target_rr,
        final_target_rr=signal.final_target_rr,
        selected_rr=signal.selected_rr,
        selected_rr_target=signal.selected_rr_target,
        min_rr_ratio=signal.min_rr_ratio,
        source="pending_entry_acceptance",
    )


def _targets_snapshot(trade_plan: TradePlan) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for target in trade_plan.targets:
        if target.price is None:
            continue
        price = _positive_decimal(target.price, "target.price")
        target_snapshot = target.model_dump(mode="json", exclude_none=True)
        target_snapshot["price"] = _decimal_string(price)
        targets.append(target_snapshot)
    return targets


def _request_snapshot(
    request: ManualConfirmRequest | dict[str, Any],
    *,
    mode: PendingEntryIntentMode,
) -> dict[str, Any]:
    if isinstance(request, ManualConfirmRequest):
        snapshot = request.model_dump(mode="json")
    elif hasattr(request, "model_dump"):
        snapshot = request.model_dump(mode="json")
    else:
        snapshot = dict(request)
    snapshot["mode"] = mode
    snapshot["pending_entry_flow"] = "arm_from_signal"
    return snapshot


def _with_reconfirmation_lifecycle_event(
    *,
    request_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any],
    previous_intent: PendingEntryIntentRead,
    accepted_trade_plan_hash: str,
    signal: RadarSignal,
) -> dict[str, Any]:
    updated = dict(request_snapshot)
    previous_events = previous_snapshot.get("pending_entry_lifecycle_events")
    lifecycle_events = list(previous_events) if isinstance(previous_events, list) else []
    lifecycle_events.append(
        {
            "event": "pending_entry.reconfirmed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "intent_id": str(previous_intent.id),
            "signal_id": str(previous_intent.signal_id),
            "previous_status": previous_intent.status,
            "previous_accepted_trade_plan_hash": previous_intent.accepted_trade_plan_hash,
            "previous_accepted_trade_plan_snapshot": previous_intent.accepted_trade_plan_snapshot,
            "accepted_trade_plan_hash": accepted_trade_plan_hash,
            "accepted_signal_status": signal.status,
        }
    )
    updated["pending_entry_lifecycle_events"] = lifecycle_events[-20:]
    return updated


def _manual_confirm_request(request: ManualConfirmRequest | dict[str, Any] | None) -> ManualConfirmRequest:
    if request is None:
        return ManualConfirmRequest(auto_enter_on_confirmation=True)
    if isinstance(request, ManualConfirmRequest):
        if request.auto_enter_on_confirmation:
            return request
        return request.model_copy(update={"auto_enter_on_confirmation": True})
    payload = dict(request)
    payload["auto_enter_on_confirmation"] = True
    return ManualConfirmRequest.model_validate(payload)


def _pending_entry_mode(value: str) -> PendingEntryIntentMode:
    return "real" if str(value).strip().lower() == "real" else "virtual"


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _signal_fingerprint(signal: RadarSignal, trade_plan_hash: str) -> str:
    payload = {
        "signal_id": signal.id,
        "exchange": signal.exchange,
        "symbol": signal.symbol,
        "strategy": signal.strategy,
        "timeframe": signal.timeframe,
        "direction": signal.direction,
        "status": signal.status,
        "trade_plan_hash": trade_plan_hash,
        "expires_at": signal.expires_at.isoformat() if signal.expires_at is not None else None,
    }
    return _snapshot_hash(payload)


def _reconfirmation_reason(hash_error: str | None) -> str:
    if hash_error:
        return f"Current trade plan requires reconfirmation: {hash_error}"
    return TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON


def _idempotency_key(
    *,
    user_id: UUID,
    signal_id: UUID,
    mode: PendingEntryIntentMode,
    trade_plan_hash: str,
    attempt: int = 0,
) -> str:
    payload = f"{user_id}:{signal_id}:{mode}:{trade_plan_hash}"
    if attempt > 0:
        payload = f"{payload}:attempt:{attempt}"
    return f"pending-entry:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _request_instrument_type(request: ManualConfirmRequest) -> str:
    if request.execution_profile is not None and request.execution_profile.instrument_type is not None:
        return request.execution_profile.instrument_type
    if request.risk_override is not None and request.risk_override.leverage is not None:
        return "futures" if request.risk_override.leverage > 1 else "spot"
    return "futures" if request.leverage > 1 else "spot"


def _strategy_risk_settings(signal: RadarSignal, *, user_id: str) -> tuple[dict[str, Any], str]:
    try:
        configs = strategy_config_service.list_configs(user_id=user_id)
    except Exception as exc:
        return {}, f"unavailable:{exc.__class__.__name__}"
    signal_exchange = signal.exchange.strip().lower()
    signal_symbol = signal.symbol.strip().upper()
    for config in configs:
        if config.strategy_code != signal.strategy:
            continue
        if config.timeframes and signal.timeframe not in config.timeframes:
            continue
        if config.pairs:
            pairs = {
                (pair.exchange.strip().lower(), pair.symbol.strip().upper())
                for pair in config.pairs
            }
            if (signal_exchange, signal_symbol) not in pairs:
                continue
        elif config.exchanges and signal_exchange not in {exchange.strip().lower() for exchange in config.exchanges}:
            continue
        return config.risk_settings.to_legacy_dict(), "strategy_config"
    return {}, "not_configured"


def _signal_version(trade_plan: TradePlan) -> str | None:
    for source in (trade_plan.metadata, trade_plan.risk_rules.metadata):
        value = source.get("signal_version") or source.get("strategy_version")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return trade_plan.version


def _positive_decimal(value: Any, field_name: str) -> Decimal:
    if value is None:
        raise ValueError(f"Pending entry requires {field_name}")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Pending entry requires numeric {field_name}") from exc
    if number <= 0:
        raise ValueError(f"Pending entry requires positive {field_name}")
    return number


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _decimal_string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return _decimal_string(_positive_decimal(value, "price"))


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _parse_uuid_or_raise(value: Any, field_name: str) -> UUID:
    parsed = _parse_uuid(value)
    if parsed is None:
        raise ValueError(f"Pending entry requires UUID {field_name}")
    return parsed


def _parse_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


pending_entry_intent_service = PendingEntryService()
pending_entry_service = pending_entry_intent_service
