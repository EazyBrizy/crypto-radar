"""create pending entry intents

Revision ID: 202606040001
Revises: 202606010003
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202606040001"
down_revision = "202606010003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_entry_intents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("entry_min", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_max", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_price_policy", sa.Text(), nullable=False),
        sa.Column("stop_loss", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "targets_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "accepted_trade_plan_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("accepted_trade_plan_hash", sa.Text(), nullable=False),
        sa.Column("accepted_signal_status", sa.Text(), nullable=False),
        sa.Column("accepted_signal_version", sa.Text(), nullable=True),
        sa.Column("accepted_signal_fingerprint", sa.Text(), nullable=True),
        sa.Column(
            "execution_profile_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "request_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_trade_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("mode IN ('virtual', 'real')", name="ck_pending_entry_intents_mode"),
        sa.CheckConstraint(
            "status IN ("
            "'pending', 'triggered', 'filling', 'filled', 'failed', "
            "'cancelled', 'expired', 'requires_reconfirmation'"
            ")",
            name="ck_pending_entry_intents_status",
        ),
        sa.CheckConstraint("side IN ('long', 'short')", name="ck_pending_entry_intents_side"),
        sa.CheckConstraint("length(trim(exchange)) > 0", name="ck_pending_entry_intents_exchange_not_blank"),
        sa.CheckConstraint("length(trim(symbol)) > 0", name="ck_pending_entry_intents_symbol_not_blank"),
        sa.CheckConstraint(
            "length(trim(entry_price_policy)) > 0",
            name="ck_pending_entry_intents_entry_policy_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(accepted_trade_plan_hash)) > 0",
            name="ck_pending_entry_intents_trade_plan_hash_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(accepted_signal_status)) > 0",
            name="ck_pending_entry_intents_signal_status_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="ck_pending_entry_intents_idempotency_key_not_blank",
        ),
        sa.CheckConstraint("entry_min > 0", name="ck_pending_entry_intents_entry_min_positive"),
        sa.CheckConstraint("entry_max > 0", name="ck_pending_entry_intents_entry_max_positive"),
        sa.CheckConstraint("entry_max >= entry_min", name="ck_pending_entry_intents_entry_range_order"),
        sa.CheckConstraint("stop_loss > 0", name="ck_pending_entry_intents_stop_loss_positive"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_pending_entry_intents_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["trading_signals.id"],
            name="fk_pending_entry_intents_signal_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategy_templates.id"],
            name="fk_pending_entry_intents_strategy_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_pending_entry_intents_idempotency_key"),
    )
    op.create_index(
        "idx_pending_entry_intents_market_status",
        "pending_entry_intents",
        ["exchange", "symbol", "status"],
    )
    op.create_index(
        "idx_pending_entry_intents_user_signal_status",
        "pending_entry_intents",
        ["user_id", "signal_id", "status"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pending_entry_intents_active_user_signal_mode "
        "ON pending_entry_intents (user_id, signal_id, mode) "
        "WHERE status IN ('pending', 'triggered', 'filling', 'requires_reconfirmation')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_pending_entry_intents_active_user_signal_mode")
    op.drop_index("idx_pending_entry_intents_user_signal_status", table_name="pending_entry_intents")
    op.drop_index("idx_pending_entry_intents_market_status", table_name="pending_entry_intents")
    op.drop_table("pending_entry_intents")
