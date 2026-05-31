"""create trade invalidation actions

Revision ID: 202605310001
Revises: 202605290001
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202605310001"
down_revision = "202605290001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_invalidation_actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trade_id", sa.Text(), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "alert_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("mode IN ('virtual', 'real')", name="ck_trade_invalidation_actions_mode"),
        sa.CheckConstraint(
            "action IN ('close_market', 'keep_stop_loss', 'dismissed')",
            name="ck_trade_invalidation_actions_action",
        ),
        sa.CheckConstraint("length(trim(fingerprint)) > 0", name="ck_trade_invalidation_actions_fingerprint_not_blank"),
        sa.CheckConstraint("length(trim(trade_id)) > 0", name="ck_trade_invalidation_actions_trade_id_not_blank"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_trade_invalidation_actions_user_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["trading_signals.id"],
            name="fk_trade_invalidation_actions_signal_id",
            ondelete="SET NULL",
        ),
    )
    op.execute(
        "CREATE INDEX idx_trade_invalidation_actions_trade_fingerprint_time "
        "ON trade_invalidation_actions (trade_id, fingerprint, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_trade_invalidation_actions_user_time "
        "ON trade_invalidation_actions (user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.drop_index("idx_trade_invalidation_actions_user_time", table_name="trade_invalidation_actions")
    op.drop_index("idx_trade_invalidation_actions_trade_fingerprint_time", table_name="trade_invalidation_actions")
    op.drop_table("trade_invalidation_actions")
