import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import pending_entry as pending_entry_api
from app.schemas.pending_entry import PendingEntryIntentRead

USER_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd524")
SIGNAL_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd527")
INTENT_ID = UUID("ba520631-d035-4f95-a4c0-3b40553dd530")


class PendingEntryApiTest(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(pending_entry_api.router)
        self.client = TestClient(app)

    def test_arm_pending_entry_endpoint_returns_intent(self) -> None:
        service = _FakePendingEntryService()
        with patch("app.api.v1.pending_entry.pending_entry_intent_service", service):
            response = self.client.post(
                f"/signals/{SIGNAL_ID}/pending-entry",
                json={"mode": "virtual", "user_id": str(USER_ID), "auto_enter_on_confirmation": True},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(INTENT_ID))
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(service.arm_calls, 1)

    def test_arm_pending_entry_endpoint_accepts_usr_demo(self) -> None:
        service = _FakePendingEntryService()
        with patch("app.api.v1.pending_entry.pending_entry_intent_service", service):
            response = self.client.post(
                f"/signals/{SIGNAL_ID}/pending-entry",
                json={"mode": "virtual", "user_id": "usr_demo", "auto_enter_on_confirmation": True},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(INTENT_ID))
        self.assertEqual(service.arm_user_ids, ["usr_demo"])

    def test_double_arm_endpoint_returns_existing_intent(self) -> None:
        service = _FakePendingEntryService()
        with patch("app.api.v1.pending_entry.pending_entry_intent_service", service):
            first = self.client.post(
                f"/signals/{SIGNAL_ID}/pending-entry",
                json={"mode": "virtual", "user_id": str(USER_ID)},
            )
            second = self.client.post(
                f"/signals/{SIGNAL_ID}/pending-entry",
                json={"mode": "virtual", "user_id": str(USER_ID)},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(service.created_intent_count, 1)

    def test_active_pending_entry_endpoint_returns_active_intent(self) -> None:
        service = _FakePendingEntryService()
        with patch("app.api.v1.pending_entry.pending_entry_intent_service", service):
            response = self.client.get(
                f"/signals/{SIGNAL_ID}/pending-entry",
                params={"user_id": str(USER_ID)},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(INTENT_ID))
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(service.active_calls, [(str(SIGNAL_ID), str(USER_ID), "virtual")])

    def test_active_pending_entry_endpoint_returns_null_without_active_intent(self) -> None:
        service = _FakePendingEntryService()
        service.intent = None
        with patch("app.api.v1.pending_entry.pending_entry_intent_service", service):
            response = self.client.get(
                f"/signals/{SIGNAL_ID}/pending-entry",
                params={"user_id": str(USER_ID)},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    def test_pending_entry_history_endpoint_returns_terminal_intents(self) -> None:
        service = _FakePendingEntryService()
        cancelled = _pending_intent().model_copy(
            update={
                "status": "cancelled",
                "failure_reason": "Cancelled by user.",
                "updated_at": datetime.now(timezone.utc),
            }
        )
        service.intent = None
        service.history = [cancelled]
        with patch("app.api.v1.pending_entry.pending_entry_intent_service", service):
            response = self.client.get(
                f"/signals/{SIGNAL_ID}/pending-entry/history",
                params={"user_id": str(USER_ID)},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [str(INTENT_ID)])
        self.assertEqual(response.json()[0]["status"], "cancelled")
        self.assertEqual(service.history_calls, [(str(SIGNAL_ID), str(USER_ID), "virtual")])

    def test_pending_entry_queue_endpoint_returns_active_intents(self) -> None:
        service = _FakePendingEntryService()
        with patch("app.api.v1.pending_entry.pending_entry_intent_service", service):
            response = self.client.get(
                "/pending-entry",
                params={"user_id": str(USER_ID), "scope": "active", "limit": "25"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [str(INTENT_ID)])
        self.assertEqual(response.json()[0]["status"], "pending")
        self.assertEqual(service.queue_active_calls, [(str(USER_ID), None, 25)])

    def test_pending_entry_queue_endpoint_returns_history_intents(self) -> None:
        service = _FakePendingEntryService()
        cancelled = _pending_intent().model_copy(
            update={
                "status": "cancelled",
                "failure_reason": "Cancelled by user.",
                "updated_at": datetime.now(timezone.utc),
            }
        )
        service.history = [cancelled]
        with patch("app.api.v1.pending_entry.pending_entry_intent_service", service):
            response = self.client.get(
                "/pending-entry",
                params={"user_id": str(USER_ID), "scope": "history", "mode": "virtual"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [str(INTENT_ID)])
        self.assertEqual(response.json()[0]["status"], "cancelled")
        self.assertEqual(service.queue_history_calls, [(str(USER_ID), "virtual", 50)])

    def test_cancel_pending_entry_endpoint_returns_cancelled_intent(self) -> None:
        service = _FakePendingEntryService()
        with patch("app.api.v1.pending_entry.pending_entry_intent_service", service):
            response = self.client.post(
                f"/pending-entry/{INTENT_ID}/cancel",
                json={"user_id": str(USER_ID)},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(response.json()["failure_reason"], "Cancelled by user.")
        self.assertEqual(service.cancel_calls, [(str(INTENT_ID), str(USER_ID))])


class _FakePendingEntryService:
    def __init__(self) -> None:
        self.intent = _pending_intent()
        self.created_intent_count = 0
        self.arm_calls = 0
        self.arm_user_ids: list[str] = []
        self.active_calls: list[tuple[str, str, str]] = []
        self.history_calls: list[tuple[str, str, str]] = []
        self.queue_active_calls: list[tuple[str, str | None, int]] = []
        self.queue_history_calls: list[tuple[str, str | None, int]] = []
        self.cancel_calls: list[tuple[str, str]] = []
        self.history: list[PendingEntryIntentRead] = []

    def arm_signal_workflow(self, *, signal_id, request, auto_entry_arm=None) -> PendingEntryIntentRead:
        self.arm_calls += 1
        self.arm_user_ids.append(request.user_id)
        if self.intent is None:
            self.created_intent_count += 1
            self.intent = _pending_intent(
                UUID(f"ba520631-d035-4f95-a4c0-3b40553dd5{30 + self.created_intent_count:02d}")
            )
        elif self.created_intent_count == 0:
            self.created_intent_count = 1
        return self.intent

    def get_active_for_signal(self, *, signal_id, user_id, mode="virtual") -> PendingEntryIntentRead | None:
        self.active_calls.append((str(signal_id), str(user_id), str(mode)))
        return self.intent

    def list_history_for_signal(self, *, signal_id, user_id, mode="virtual") -> list[PendingEntryIntentRead]:
        self.history_calls.append((str(signal_id), str(user_id), str(mode)))
        return self.history

    def list_active_for_user(self, *, user_id, mode=None, limit=100) -> list[PendingEntryIntentRead]:
        self.queue_active_calls.append((str(user_id), mode, limit))
        return [self.intent] if self.intent is not None else []

    def list_history_for_user(self, *, user_id, mode=None, limit=50) -> list[PendingEntryIntentRead]:
        self.queue_history_calls.append((str(user_id), mode, limit))
        return self.history

    def cancel_intent(self, intent_id, *, user_id, reason: str) -> PendingEntryIntentRead:
        self.cancel_calls.append((str(intent_id), str(user_id)))
        assert self.intent is not None
        cancelled = self.intent.model_copy(
            update={
                "status": "cancelled",
                "failure_reason": reason,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.history.insert(0, cancelled)
        self.intent = None
        return cancelled

    def reconfirm_intent(self, intent_id, *, request=None, auto_entry_arm=None) -> PendingEntryIntentRead:
        return self.intent


def _pending_intent(intent_id: UUID = INTENT_ID) -> PendingEntryIntentRead:
    now = datetime.now(timezone.utc)
    return PendingEntryIntentRead(
        id=intent_id,
        user_id=USER_ID,
        signal_id=SIGNAL_ID,
        mode="virtual",
        status="pending",
        exchange="bybit",
        symbol="BTCUSDT",
        side="long",
        entry_min=Decimal("100"),
        entry_max=Decimal("101"),
        entry_price_policy="accepted_entry_zone",
        stop_loss=Decimal("95"),
        targets_snapshot=[{"label": "TP1", "price": "110"}],
        accepted_trade_plan_snapshot={"entry": {"min_price": "100", "max_price": "101"}},
        accepted_trade_plan_hash="sha256:test",
        accepted_signal_status="ready",
        execution_profile_snapshot={"rr_guard_mode": "soft"},
        request_snapshot={"auto_enter_on_confirmation": True},
        idempotency_key="pending-entry:test",
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
