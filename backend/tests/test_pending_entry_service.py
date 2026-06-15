import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.user import AppUser
from app.schemas.pending_entry import PendingEntryIntentCreate, PendingEntryIntentRead
from app.schemas.risk import ResolvedExecutionProfile
from app.schemas.signal import RadarSignal, SignalEdgeSnapshot
from app.schemas.trade import ManualConfirmRequest
from app.schemas.user import RiskManagementSettings
from app.services.pending_entry import (
    TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
    PendingEntryService,
)
from app.services.signal_views import annotate_pending_entry_view

USER_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd524")
SIGNAL_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd527")


class PendingEntryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.SessionFactory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            future=True,
        )
        _create_sqlite_user_tables(self.engine)
        _seed_demo_user(self.SessionFactory)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_arm_from_signal_creates_pending_intent_with_snapshot_hash(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)

        intent = service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        self.assertEqual(intent.status, "pending")
        self.assertEqual(intent.entry_min, Decimal("100"))
        self.assertEqual(intent.entry_max, Decimal("101"))
        self.assertEqual(intent.stop_loss, Decimal("95"))
        self.assertEqual(intent.targets_snapshot[0]["price"], "110")
        self.assertEqual(intent.execution_profile_snapshot["risk_mode"], "percent")
        self.assertTrue(intent.accepted_trade_plan_hash.startswith("sha256:"))
        self.assertEqual(intent.accepted_trade_plan_snapshot["entry"]["min_price"], "100")
        self.assertEqual(intent.accepted_trade_plan_snapshot["exchange"], "bybit")
        self.assertEqual(intent.accepted_trade_plan_snapshot["symbol"], "BTCUSDT")
        self.assertEqual(intent.accepted_trade_plan_snapshot["side"], "long")
        self.assertEqual(intent.accepted_trade_plan_snapshot["accepted_signal"]["score"], 82)
        self.assertEqual(intent.accepted_trade_plan_snapshot["execution_profile_snapshot"]["risk_mode"], "percent")
        self.assertIn("material_change_policy", intent.accepted_trade_plan_snapshot)
        self.assertEqual(intent.request_snapshot["auto_enter_on_confirmation"], True)
        self.assertEqual(repository.create_calls, 1)

    def test_arm_from_signal_persists_accepted_edge_snapshot(self) -> None:
        repository = _FakePendingEntryRepository()
        signal = _signal(edge=_positive_edge())
        service = self._service(repository, signal_loader=lambda _signal_id: signal)

        intent = service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        accepted_edge = intent.accepted_trade_plan_snapshot["accepted_signal"]["edge"]
        self.assertEqual(accepted_edge["status"], "positive")
        self.assertEqual(accepted_edge["sample_size"], 80)
        self.assertEqual(accepted_edge["source"], "outcome")

    def test_arm_from_signal_publishes_pending_entry_update(self) -> None:
        repository = _FakePendingEntryRepository()
        publisher = _FakePendingEntryEventPublisher()
        service = self._service(repository, event_publisher=publisher)

        intent = service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        self.assertEqual(len(publisher.events), 1)
        self.assertEqual(publisher.events[0]["pending_entry_id"], str(intent.id))
        self.assertEqual(publisher.events[0]["signal_id"], str(SIGNAL_ID))
        self.assertEqual(publisher.events[0]["user_id"], str(USER_ID))
        self.assertEqual(publisher.events[0]["status"], "pending")
        self.assertEqual(publisher.events[0]["mode"], "virtual")

    def test_event_publish_failure_does_not_rollback_transition(self) -> None:
        repository = _FakePendingEntryRepository()
        created = self._service(repository).arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        service = self._service(repository, event_publisher=_FailingPendingEntryEventPublisher())

        with self.assertLogs("app.services.pending_entry", level="WARNING") as logs:
            cancelled = service.cancel_intent(created.id, user_id=USER_ID)

        self.assertEqual(cancelled.status, "cancelled")
        self.assertIn("Pending entry realtime event publish failed", "\n".join(logs.output))

    def test_terminal_pending_entry_is_recorded_as_signal_outcome(self) -> None:
        repository = _FakePendingEntryRepository()
        outcome_recorder = _FakePendingEntryOutcomeRecorder()
        created = self._service(repository).arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        service = self._service(repository, pending_entry_outcomes=outcome_recorder)

        expired = service.transition_status(
            created.id,
            status="expired",
            failure_reason="Pending entry intent expired before entry touch.",
            reason_code="pending_entry_expired_before_touch",
        )

        self.assertEqual(expired.status, "expired")
        self.assertEqual(expired.reason_code, "pending_entry_expired_before_touch")
        self.assertEqual(
            outcome_recorder.calls,
            [
                (
                    created.id,
                    "expired",
                    "Pending entry intent expired before entry touch.",
                    "pending_entry_expired_before_touch",
                )
            ],
        )

    def test_duplicate_arm_returns_existing_active_intent(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)

        first = service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        second = service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        self.assertEqual(second.id, first.id)
        self.assertEqual(repository.create_calls, 1)

    def test_missing_entry_zone_fails_validation(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(
            repository,
            signal_loader=lambda _signal_id: _signal(entry_min=None, entry_max=None),
        )

        with self.assertRaises(ValueError) as exc:
            service.arm_from_signal(
                user_id=USER_ID,
                signal_id=SIGNAL_ID,
                mode="virtual",
                request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
                execution_profile=_execution_profile(),
            )

        self.assertIn("entry_min", str(exc.exception))
        self.assertEqual(repository.create_calls, 0)

    def test_invalidated_signal_does_not_create_pending_intent(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(
            repository,
            signal_loader=lambda _signal_id: _signal(status="invalidated"),
        )

        with self.assertRaises(ValueError) as exc:
            service.arm_from_signal(
                user_id=USER_ID,
                signal_id=SIGNAL_ID,
                mode="virtual",
                request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
                execution_profile=_execution_profile(),
            )

        self.assertIn("terminal", str(exc.exception))
        self.assertEqual(repository.create_calls, 0)

    def test_reconcile_same_plan_hash_keeps_pending_intent(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        intent = service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        changed = service.reconcile_signal_trade_plan(_signal(score=95, confidence=0.95))

        self.assertEqual(changed, [])
        self.assertEqual(repository.active.status if repository.active else None, intent.status)
        self.assertEqual(repository.transitions, [])

    def test_reconcile_changed_entry_requires_reconfirmation(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        changed = service.reconcile_signal_trade_plan(
            _signal(entry_min=99.0, entry_max=100.0),
        )

        self.assertEqual(changed[0].status, "requires_reconfirmation")
        self.assertEqual(repository.active.status if repository.active else None, "requires_reconfirmation")

    def test_reconcile_changed_stop_requires_reconfirmation(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        changed = service.reconcile_signal_trade_plan(_signal(stop_loss=94.0))

        self.assertEqual(changed[0].status, "requires_reconfirmation")

    def test_reconcile_changed_target_requires_reconfirmation(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        service.arm_from_signal(
            user_id=USER_ID,
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id=str(USER_ID), auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        changed = service.reconcile_signal_trade_plan(_signal(take_profit_1=111.0))

        self.assertEqual(changed[0].status, "requires_reconfirmation")

    def test_arm_from_signal_accepts_usr_demo_alias(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)

        intent = service.arm_from_signal(
            user_id="usr_demo",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="usr_demo", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        self.assertEqual(intent.user_id, USER_ID)
        self.assertEqual(repository.create_calls, 1)

    def test_list_active_accepts_usr_demo_alias(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        created = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        intents = service.list_active_for_signal_user(
            signal_id=SIGNAL_ID,
            user_id="usr_demo",
        )

        self.assertEqual([intent.id for intent in intents], [created.id])

    def test_list_user_queue_accepts_usr_demo_alias(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        active = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        cancelled = service.cancel_intent(active.id, user_id="demo_user")

        active_queue = service.list_active_for_user(user_id="usr_demo")
        history = service.list_history_for_user(user_id="usr_demo")

        self.assertEqual(active_queue, [])
        self.assertEqual([intent.id for intent in history], [cancelled.id])

    def test_list_active_for_user_sweeps_expired_intents_to_history(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        created = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        expired_active = created.model_copy(
            update={
                "status": "requires_reconfirmation",
                "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
            }
        )
        repository.records = [expired_active]
        repository.active = expired_active

        active_queue = service.list_active_for_user(user_id="usr_demo")
        history = service.list_history_for_user(user_id="usr_demo")

        self.assertEqual(active_queue, [])
        self.assertEqual([intent.id for intent in history], [created.id])
        self.assertEqual(history[0].status, "expired")
        self.assertEqual(history[0].reason_code, "pending_entry_expired_before_touch")
        self.assertEqual(repository.transitions[0][1], "expired")

    def test_list_active_for_user_uses_patchable_clock_for_future_expiration(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        created = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        fixed_now = datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc)
        future_active = created.model_copy(update={"expires_at": fixed_now + timedelta(minutes=15)})
        repository.records = [future_active]
        repository.active = future_active

        with patch("app.services.pending_entry._utc_now", return_value=fixed_now):
            active_queue = service.list_active_for_user(user_id="usr_demo")

        self.assertEqual([intent.id for intent in active_queue], [created.id])
        self.assertEqual(repository.transitions, [])

    def test_list_active_for_user_expires_intent_under_patchable_clock(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        created = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        fixed_now = datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc)
        expired_active = created.model_copy(update={"expires_at": fixed_now - timedelta(seconds=1)})
        repository.records = [expired_active]
        repository.active = expired_active

        with patch("app.services.pending_entry._utc_now", return_value=fixed_now):
            active_queue = service.list_active_for_user(user_id="usr_demo")

        history = service.list_history_for_user(user_id="usr_demo")
        self.assertEqual(active_queue, [])
        self.assertEqual([intent.id for intent in history], [created.id])
        self.assertEqual(history[0].status, "expired")
        self.assertEqual(history[0].reason_code, "pending_entry_expired_before_touch")
        self.assertEqual(repository.transitions[0][1], "expired")

    def test_cancel_accepts_usr_demo_alias(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        created = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        cancelled = service.cancel_intent(created.id, user_id="usr_demo")

        self.assertEqual(cancelled.status, "cancelled")

    def test_reconfirm_accepts_usr_demo_alias(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        created = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        reconfirmed = service.reconfirm_intent(
            created.id,
            request=ManualConfirmRequest(user_id="usr_demo", auto_enter_on_confirmation=True),
        )

        self.assertEqual(reconfirmed.id, created.id)

    def test_pending_entry_view_preserves_specific_reason_code_over_placeholder_snapshot(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        created = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        requires = service.transition_status(
            created.id,
            status="requires_reconfirmation",
            failure_reason="Edge degraded after acceptance.",
            reason_code="edge_degraded_after_acceptance",
        )
        assert requires is not None
        poisoned = requires.model_copy(
            update={
                "request_snapshot": {
                    **requires.request_snapshot,
                    "reason_code": "no_backend_reason",
                    "code": "-",
                }
            }
        )

        annotated = annotate_pending_entry_view(poisoned)

        self.assertEqual(annotated.view.reason_code if annotated.view else None, "edge_degraded_after_acceptance")
        self.assertEqual(annotated.view.reason if annotated.view else None, "edge_degraded_after_acceptance")

    def test_reconfirm_updates_existing_intent_with_current_trade_plan(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        created = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )
        old_snapshot = created.accepted_trade_plan_snapshot
        old_hash = created.accepted_trade_plan_hash
        requires = repository.transition_status(
            created.id,
            status="requires_reconfirmation",
            failure_reason=TRADE_PLAN_RECONFIRMATION_REQUIRED_REASON,
        )
        self.assertIsNotNone(requires)
        changed_service = self._service(
            repository,
            signal_loader=lambda _signal_id: _signal(entry_min=99.0, entry_max=100.0, stop_loss=94.0, take_profit_1=111.0),
        )

        reconfirmed = changed_service.reconfirm_intent(
            created.id,
            request=ManualConfirmRequest(user_id="usr_demo", auto_enter_on_confirmation=True),
        )

        self.assertEqual(reconfirmed.id, created.id)
        self.assertEqual(reconfirmed.status, "pending")
        self.assertIsNone(reconfirmed.failure_reason)
        self.assertEqual(reconfirmed.entry_min, Decimal("99"))
        self.assertEqual(reconfirmed.entry_max, Decimal("100"))
        self.assertEqual(reconfirmed.stop_loss, Decimal("94"))
        self.assertEqual(reconfirmed.targets_snapshot[0]["price"], "111")
        self.assertNotEqual(reconfirmed.accepted_trade_plan_hash, old_hash)
        self.assertEqual(reconfirmed.accepted_trade_plan_snapshot["entry"]["min_price"], "99")
        self.assertEqual(reconfirmed.accepted_signal_status, "active")
        self.assertIsNotNone(reconfirmed.accepted_signal_fingerprint)
        event = reconfirmed.request_snapshot["pending_entry_lifecycle_events"][-1]
        self.assertEqual(event["event"], "pending_entry.reconfirmed")
        self.assertEqual(event["previous_accepted_trade_plan_hash"], old_hash)
        self.assertEqual(event["previous_accepted_trade_plan_snapshot"], old_snapshot)

    def test_cancelled_intent_is_history_not_active_and_can_rearm(self) -> None:
        repository = _FakePendingEntryRepository()
        service = self._service(repository)
        created = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        cancelled = service.cancel_intent(created.id, user_id="demo_user")

        self.assertEqual(cancelled.status, "cancelled")
        self.assertIsNone(
            service.get_active_for_signal(
                signal_id=SIGNAL_ID,
                user_id="usr_demo",
                mode="virtual",
            )
        )
        history = service.list_history_for_signal(
            signal_id=SIGNAL_ID,
            user_id="usr_demo",
            mode="virtual",
        )
        self.assertEqual([intent.id for intent in history], [created.id])

        rearmed = service.arm_from_signal(
            user_id="demo_user",
            signal_id=SIGNAL_ID,
            mode="virtual",
            request=ManualConfirmRequest(user_id="demo_user", auto_enter_on_confirmation=True),
            execution_profile=_execution_profile(),
        )

        self.assertEqual(rearmed.status, "pending")
        self.assertNotEqual(rearmed.id, created.id)
        self.assertEqual(repository.create_calls, 2)
        self.assertNotEqual(repository.idempotency_keys[0], repository.idempotency_keys[1])

    def _service(
        self,
        repository: "_FakePendingEntryRepository",
        *,
        signal_loader: Any | None = None,
        event_publisher: Any | None = None,
        pending_entry_outcomes: Any | None = None,
    ) -> PendingEntryService:
        return PendingEntryService(
            repository=repository,
            session_factory=self.SessionFactory,
            signal_loader=signal_loader or (lambda _signal_id: _signal()),
            risk_settings_provider=lambda _user_id: RiskManagementSettings(),
            event_publisher=event_publisher or _FakePendingEntryEventPublisher(),
            pending_entry_outcomes=pending_entry_outcomes,
        )


class _FakePendingEntryOutcomeRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, str | None, str | None]] = []

    def record_pending_entry_terminal(self, intent: PendingEntryIntentRead) -> None:
        self.calls.append((intent.id, intent.status, intent.failure_reason, intent.reason_code))


class _FakePendingEntryRepository:
    def __init__(self) -> None:
        self.create_calls = 0
        self.active: PendingEntryIntentRead | None = None
        self.records: list[PendingEntryIntentRead] = []
        self.idempotency_keys: list[str] = []
        self.transitions: list[tuple[UUID, str, str | None]] = []
        self.reconfirmation_updates = 0

    def get_active_for_user_signal_mode(
        self,
        *,
        user_id: UUID,
        signal_id: UUID,
        mode: str,
    ) -> PendingEntryIntentRead | None:
        return next(
            (
                intent
                for intent in self.records
                if intent.status in {"pending", "triggered", "filling", "requires_reconfirmation"}
                and intent.user_id == user_id
                and intent.signal_id == signal_id
                and intent.mode == mode
            ),
            None,
        )

    def create_intent(self, intent: PendingEntryIntentCreate) -> PendingEntryIntentRead:
        self.create_calls += 1
        self.idempotency_keys.append(intent.idempotency_key)
        now = datetime.now(timezone.utc)
        self.active = PendingEntryIntentRead(
            **intent.model_dump(),
            id=UUID(f"ba520631-d035-4f95-a4c0-3b40553dd5{29 + self.create_calls:02d}"),
            created_at=now,
            updated_at=now,
        )
        self.records.append(self.active)
        return self.active

    def get_by_id(self, intent_id: UUID) -> PendingEntryIntentRead | None:
        return next((intent for intent in self.records if str(intent.id) == str(intent_id)), None)

    def list_active_for_signal(self, signal_id: str) -> list[PendingEntryIntentRead]:
        return [
            intent
            for intent in self.records
            if str(intent.signal_id) == str(signal_id)
            and intent.status in {"pending", "triggered", "filling", "requires_reconfirmation"}
        ]

    def list_history_for_user_signal_mode(
        self,
        *,
        signal_id: UUID,
        user_id: UUID,
        mode: str,
    ) -> list[PendingEntryIntentRead]:
        return [
            intent
            for intent in self.records
            if intent.signal_id == signal_id
            and intent.user_id == user_id
            and intent.mode == mode
            and intent.status in {"filled", "failed", "cancelled", "expired"}
        ]

    def list_active_for_user(
        self,
        *,
        user_id: UUID,
        mode: str | None = None,
        limit: int = 100,
    ) -> list[PendingEntryIntentRead]:
        return [
            intent
            for intent in self.records
            if intent.user_id == user_id
            and (mode is None or intent.mode == mode)
            and intent.status in {"pending", "triggered", "filling", "requires_reconfirmation"}
        ][:limit]

    def list_history_for_user(
        self,
        *,
        user_id: UUID,
        mode: str | None = None,
        limit: int = 50,
    ) -> list[PendingEntryIntentRead]:
        return [
            intent
            for intent in self.records
            if intent.user_id == user_id
            and (mode is None or intent.mode == mode)
            and intent.status in {"filled", "failed", "cancelled", "expired"}
        ][:limit]

    def transition_status(
        self,
        intent_id: UUID,
        *,
        status: str,
        failure_reason: str | None = None,
        filled_trade_id: UUID | None = None,
        reason_code: str | None = None,
        gate_snapshot: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        existing = self.get_by_id(intent_id)
        if existing is None:
            return None
        self.transitions.append((intent_id, status, failure_reason))
        request_snapshot = dict(existing.request_snapshot or {})
        if reason_code is not None:
            request_snapshot["pending_entry_last_reason_code"] = reason_code
            if status in {"failed", "cancelled", "expired"}:
                request_snapshot["pending_entry_terminal_reason_code"] = reason_code
        if gate_snapshot is not None:
            request_snapshot["pending_entry_gate_snapshot"] = gate_snapshot
        updated = existing.model_copy(
            update={
                "status": status,
                "failure_reason": failure_reason,
                "filled_trade_id": filled_trade_id,
                "request_snapshot": request_snapshot,
                "reason_code": reason_code,
                "updated_at": now or datetime.now(timezone.utc),
            }
        )
        self.records = [updated if intent.id == intent_id else intent for intent in self.records]
        self.active = updated if updated.status in {"pending", "triggered", "filling", "requires_reconfirmation"} else None
        return updated

    def update_market_review_snapshot(
        self,
        intent_id: UUID,
        *,
        request_snapshot: dict[str, Any],
    ) -> PendingEntryIntentRead | None:
        existing = self.get_by_id(intent_id)
        if existing is None:
            return None
        updated = existing.model_copy(
            update={
                "request_snapshot": request_snapshot,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.records = [updated if intent.id == intent_id else intent for intent in self.records]
        self.active = updated if updated.status in {"pending", "triggered", "filling", "requires_reconfirmation"} else None
        return updated

    def update_reconfirmed_acceptance(
        self,
        intent_id: UUID,
        **updates: Any,
    ) -> PendingEntryIntentRead | None:
        existing = self.get_by_id(intent_id)
        if existing is None:
            return None
        self.reconfirmation_updates += 1
        updated = existing.model_copy(
            update={
                **updates,
                "status": "pending",
                "failure_reason": None,
                "triggered_at": None,
                "filled_at": None,
                "filled_trade_id": None,
                "updated_at": updates.get("now") or datetime.now(timezone.utc),
            }
        )
        self.records = [updated if intent.id == intent_id else intent for intent in self.records]
        self.active = updated
        return updated


class _FakePendingEntryEventPublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, str | None]] = []

    def publish_update(self, intent: PendingEntryIntentRead, *, message: str | None = None) -> None:
        reason = message if message is not None else intent.failure_reason
        self.events.append(
            {
                "pending_entry_id": str(intent.id),
                "signal_id": str(intent.signal_id),
                "user_id": str(intent.user_id),
                "status": intent.status,
                "mode": intent.mode,
                "reason": reason,
                "message": reason,
            }
        )


class _FailingPendingEntryEventPublisher:
    def publish_update(self, intent: PendingEntryIntentRead, *, message: str | None = None) -> None:
        raise RuntimeError("broker unavailable")


def _signal(
    *,
    status: str = "active",
    entry_min: float | None = 100.0,
    entry_max: float | None = 101.0,
    stop_loss: float = 95.0,
    take_profit_1: float = 110.0,
    score: int = 82,
    confidence: float = 0.82,
    edge: SignalEdgeSnapshot | None = None,
) -> RadarSignal:
    now = datetime.now(timezone.utc)
    return RadarSignal(
        id=str(SIGNAL_ID),
        symbol="BTCUSDT",
        exchange="bybit",
        strategy="trend_pullback_continuation",
        direction="long",
        confidence=confidence,
        status=status,
        score=score,
        timeframe="15m",
        entry_min=entry_min,
        entry_max=entry_max,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        edge=edge,
        created_at=now,
        updated_at=now,
    )


def _positive_edge() -> SignalEdgeSnapshot:
    return SignalEdgeSnapshot(
        status="positive",
        sample_size=80,
        min_sample_size=50,
        expectancy_after_costs_r=0.18,
        profit_factor=1.4,
        confidence_score=0.8,
        source="outcome",
    )


def _execution_profile() -> ResolvedExecutionProfile:
    return ResolvedExecutionProfile(
        execution_mode="virtual",
        instrument_type="spot",
        risk_mode="percent",
        risk_percent=Decimal("1.0"),
        fixed_risk_currency="USDT",
        leverage=Decimal("1"),
        rr_guard_mode="soft",
        min_rr_ratio=Decimal("2.0"),
        rr_target="final",
        radar_display_mode="all_market_opportunities",
    )


def _create_sqlite_user_tables(engine: Any) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE app_users (
                    id UUID PRIMARY KEY,
                    email TEXT NOT NULL,
                    username TEXT,
                    status TEXT,
                    locale TEXT,
                    timezone TEXT,
                    risk_profile TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE user_auth_identities (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    provider TEXT NOT NULL,
                    provider_subject TEXT NOT NULL,
                    email TEXT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(user_id) REFERENCES app_users(id),
                    UNIQUE(provider, provider_subject)
                )
                """
            )
        )


def _seed_demo_user(session_factory: Any) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            AppUser(
                id=USER_ID,
                email="demo@crypto-radar.local",
                username="demo",
                status="active",
                locale="ru",
                timezone="Europe/Warsaw",
                risk_profile="balanced",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


if __name__ == "__main__":
    unittest.main()
