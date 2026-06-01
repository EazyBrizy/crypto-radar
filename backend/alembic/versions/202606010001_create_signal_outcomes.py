"""create signal outcomes

Revision ID: 202606010001
Revises: 202605310002
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202606010001"
down_revision = "202605310002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_outcomes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("strategy", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("signal_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("entry_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_min", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_max", sa.Numeric(38, 18), nullable=False),
        sa.Column("stop_loss", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "targets",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("selected_rr", sa.Numeric(10, 4), nullable=True),
        sa.Column("realized_r", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("mfe_r", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("mae_r", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("bars_to_entry", sa.Integer(), nullable=True),
        sa.Column("bars_to_outcome", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint("length(trim(exchange)) > 0", name="ck_signal_outcomes_exchange_not_blank"),
        sa.CheckConstraint("length(trim(symbol)) > 0", name="ck_signal_outcomes_symbol_not_blank"),
        sa.CheckConstraint("length(trim(timeframe)) > 0", name="ck_signal_outcomes_timeframe_not_blank"),
        sa.CheckConstraint("length(trim(strategy)) > 0", name="ck_signal_outcomes_strategy_not_blank"),
        sa.CheckConstraint("direction IN ('long', 'short')", name="ck_signal_outcomes_direction"),
        sa.CheckConstraint(
            "status IN ("
            "'tracking', 'entry_touched', 'tp1', 'tp2', 'tp3', "
            "'stop_loss', 'expired', 'invalidated', 'time_stop'"
            ")",
            name="ck_signal_outcomes_status",
        ),
        sa.CheckConstraint(
            "outcome IN ('win', 'loss', 'breakeven', 'expired', 'invalidated', 'open')",
            name="ck_signal_outcomes_outcome",
        ),
        sa.CheckConstraint("signal_score >= 0 AND signal_score <= 100", name="ck_signal_outcomes_signal_score"),
        sa.CheckConstraint("entry_price > 0", name="ck_signal_outcomes_entry_price_positive"),
        sa.CheckConstraint("stop_loss > 0", name="ck_signal_outcomes_stop_loss_positive"),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["trading_signals.id"],
            name="fk_signal_outcomes_signal_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("signal_id", name="uq_signal_outcomes_signal_id"),
    )
    op.create_index(
        "idx_signal_outcomes_open_series",
        "signal_outcomes",
        ["exchange", "symbol", "timeframe", "outcome"],
    )
    op.execute("CREATE INDEX idx_signal_outcomes_created_at ON signal_outcomes (created_at DESC)")


def downgrade() -> None:
    op.drop_index("idx_signal_outcomes_created_at", table_name="signal_outcomes")
    op.drop_index("idx_signal_outcomes_open_series", table_name="signal_outcomes")
    op.drop_table("signal_outcomes")
