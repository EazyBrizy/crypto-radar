"""create notifications outbox and audit tables

Revision ID: 202605280011
Revises: 202605280010
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605280011"
down_revision = "202605280010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(trim(type)) > 0", name="ck_notifications_type_not_blank"),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_notifications_title_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_notifications_user_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_notifications_user_read",
        "notifications",
        ["user_id", "is_read", sa.text("created_at DESC")],
    )
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "notification_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider_msg_id", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("length(trim(channel)) > 0", name="ck_notification_deliveries_channel_not_blank"),
        sa.CheckConstraint("length(trim(status)) > 0", name="ck_notification_deliveries_status_not_blank"),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name="fk_notification_deliveries_notification_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_notification_deliveries_notification_id",
        "notification_deliveries",
        ["notification_id"],
    )
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])

    op.create_table(
        "outbox_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(trim(aggregate_type)) > 0", name="ck_outbox_events_aggregate_type_not_blank"),
        sa.CheckConstraint("length(trim(event_type)) > 0", name="ck_outbox_events_event_type_not_blank"),
        sa.CheckConstraint("length(trim(status)) > 0", name="ck_outbox_events_status_not_blank"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts_non_negative"),
        sa.PrimaryKeyConstraint("id", "created_at", name="pk_outbox_events"),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.execute("CREATE TABLE outbox_events_default PARTITION OF outbox_events DEFAULT")
    op.execute(
        "CREATE INDEX idx_outbox_pending "
        "ON outbox_events (status, next_retry_at, created_at) "
        "WHERE status = 'pending'"
    )
    op.execute(
        "CREATE INDEX ix_outbox_events_aggregate "
        "ON outbox_events (aggregate_type, aggregate_id, created_at DESC)"
    )

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("length(trim(action)) > 0", name="ck_audit_log_action_not_blank"),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], name="fk_audit_log_user_id"),
        sa.PrimaryKeyConstraint("id", "created_at", name="pk_audit_log"),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.execute("CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT")
    op.execute("CREATE INDEX ix_audit_log_user_time ON audit_log (user_id, created_at DESC)")
    op.execute("CREATE INDEX ix_audit_log_entity_time ON audit_log (entity_type, entity_id, created_at DESC)")
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")

    op.execute("CREATE INDEX idx_orders_user_created ON orders (user_id, created_at DESC)")
    op.execute("CREATE INDEX idx_orders_status ON orders (status, created_at DESC)")
    op.execute("CREATE INDEX idx_positions_user_status ON positions (user_id, status, opened_at DESC)")
    op.execute("CREATE INDEX idx_external_trades_user_time ON external_exchange_trades (user_id, traded_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_external_trades_user_time")
    op.execute("DROP INDEX IF EXISTS idx_positions_user_status")
    op.execute("DROP INDEX IF EXISTS idx_orders_status")
    op.execute("DROP INDEX IF EXISTS idx_orders_user_created")

    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_entity_time")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_user_time")
    op.drop_table("audit_log_default")
    op.drop_table("audit_log")

    op.execute("DROP INDEX IF EXISTS ix_outbox_events_aggregate")
    op.execute("DROP INDEX IF EXISTS idx_outbox_pending")
    op.drop_table("outbox_events_default")
    op.drop_table("outbox_events")

    op.drop_index("ix_notification_deliveries_status", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_notification_id", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")

    op.execute("ALTER TABLE notifications DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_notifications_user_read", table_name="notifications")
    op.drop_table("notifications")
