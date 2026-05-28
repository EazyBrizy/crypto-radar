import unittest

from sqlalchemy.dialects.postgresql import INET, JSONB

from app.models.audit import AuditLog
from app.models.notification import Notification, NotificationDelivery
from app.models.outbox import OutboxEvent


class NotificationOutboxAuditModelsTest(unittest.TestCase):
    def test_notification_payload_is_jsonb_and_user_delete_cascades(self) -> None:
        self.assertIsInstance(Notification.__table__.c.payload.type, JSONB)
        foreign_key = next(iter(Notification.__table__.c.user_id.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_notification_delivery_cascades_on_notification_delete(self) -> None:
        foreign_key = next(iter(NotificationDelivery.__table__.c.notification_id.foreign_keys))
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_notification_indexes_are_present(self) -> None:
        index_names = {index.name for index in Notification.__table__.indexes}
        self.assertIn("idx_notifications_user_read", index_names)

    def test_outbox_event_is_partitioned_by_created_at(self) -> None:
        self.assertEqual(
            OutboxEvent.__table__.dialect_options["postgresql"]["partition_by"],
            "RANGE (created_at)",
        )

    def test_outbox_primary_key_includes_partition_key(self) -> None:
        primary_key_columns = {column.name for column in OutboxEvent.__table__.primary_key.columns}
        self.assertEqual(primary_key_columns, {"id", "created_at"})

    def test_outbox_payload_is_jsonb_and_pending_index_exists(self) -> None:
        self.assertIsInstance(OutboxEvent.__table__.c.payload.type, JSONB)
        index_names = {index.name for index in OutboxEvent.__table__.indexes}
        self.assertIn("idx_outbox_pending", index_names)

    def test_audit_log_is_partitioned_by_created_at(self) -> None:
        self.assertEqual(
            AuditLog.__table__.dialect_options["postgresql"]["partition_by"],
            "RANGE (created_at)",
        )

    def test_audit_log_primary_key_includes_partition_key(self) -> None:
        primary_key_columns = {column.name for column in AuditLog.__table__.primary_key.columns}
        self.assertEqual(primary_key_columns, {"id", "created_at"})

    def test_audit_log_uses_inet_and_jsonb_types(self) -> None:
        self.assertIsInstance(AuditLog.__table__.c.ip_address.type, INET)
        self.assertIsInstance(AuditLog.__table__.c.payload.type, JSONB)


if __name__ == "__main__":
    unittest.main()
