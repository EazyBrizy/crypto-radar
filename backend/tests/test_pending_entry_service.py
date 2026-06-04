import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.user import AppUser
from app.schemas.pending_entry import PendingEntryIntentCreate, PendingEntryIntentRead
from app.schemas.risk import ResolvedExecutionProfile
from app.schemas.signal import RadarSignal
from app.schemas.trade import ManualConfirmRequest
from app.schemas.user import RiskManagementSettings
from app.services.pending_entry import PendingEntryService

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
        self.assertEqual(intent.request_snapshot["auto_enter_on_confirmation"], True)
        self.assertEqual(repository.create_calls, 1)

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
        mirror_calls: list[dict[str, object]] = []

        changed = service.reconcile_signal_trade_plan(
            _signal(entry_min=99.0, entry_max=100.0),
            auto_entry_updater=lambda signal_id, **kwargs: mirror_calls.append({"signal_id": signal_id, **kwargs}),
        )

        self.assertEqual(changed[0].status, "requires_reconfirmation")
        self.assertEqual(repository.active.status if repository.active else None, "requires_reconfirmation")
        self.assertEqual(mirror_calls[0]["status"], "requires_reconfirmation")

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

    def _service(
        self,
        repository: "_FakePendingEntryRepository",
        *,
        signal_loader: Any | None = None,
    ) -> PendingEntryService:
        return PendingEntryService(
            repository=repository,
            session_factory=self.SessionFactory,
            signal_loader=signal_loader or (lambda _signal_id: _signal()),
            risk_settings_provider=lambda _user_id: RiskManagementSettings(),
        )


class _FakePendingEntryRepository:
    def __init__(self) -> None:
        self.create_calls = 0
        self.active: PendingEntryIntentRead | None = None
        self.transitions: list[tuple[UUID, str, str | None]] = []

    def get_active_for_user_signal_mode(
        self,
        *,
        user_id: UUID,
        signal_id: UUID,
        mode: str,
    ) -> PendingEntryIntentRead | None:
        if self.active is None:
            return None
        if self.active.status not in {"pending", "triggered", "requires_reconfirmation"}:
            return None
        if self.active.user_id != user_id or self.active.signal_id != signal_id or self.active.mode != mode:
            return None
        return self.active

    def create_intent(self, intent: PendingEntryIntentCreate) -> PendingEntryIntentRead:
        self.create_calls += 1
        now = datetime.now(timezone.utc)
        self.active = PendingEntryIntentRead(
            **intent.model_dump(),
            id=UUID("ba520631-d035-4f95-a4c0-3b40553dd530"),
            created_at=now,
            updated_at=now,
        )
        return self.active

    def get_by_id(self, intent_id: UUID) -> PendingEntryIntentRead | None:
        if self.active is None or str(self.active.id) != str(intent_id):
            return None
        return self.active

    def list_active_for_signal(self, signal_id: str) -> list[PendingEntryIntentRead]:
        if self.active is None or str(self.active.signal_id) != str(signal_id):
            return []
        if self.active.status not in {"pending", "triggered", "requires_reconfirmation"}:
            return []
        return [self.active]

    def transition_status(
        self,
        intent_id: UUID,
        *,
        status: str,
        failure_reason: str | None = None,
        filled_trade_id: UUID | None = None,
        now: datetime | None = None,
    ) -> PendingEntryIntentRead | None:
        if self.active is None or self.active.id != intent_id:
            return None
        self.transitions.append((intent_id, status, failure_reason))
        self.active = self.active.model_copy(
            update={
                "status": status,
                "failure_reason": failure_reason,
                "filled_trade_id": filled_trade_id,
                "updated_at": now or datetime.now(timezone.utc),
            }
        )
        return self.active


def _signal(
    *,
    status: str = "active",
    entry_min: float | None = 100.0,
    entry_max: float | None = 101.0,
    stop_loss: float = 95.0,
    take_profit_1: float = 110.0,
    score: int = 82,
    confidence: float = 0.82,
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
        created_at=now,
        updated_at=now,
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
