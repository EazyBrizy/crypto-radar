"""create strategy test runs

Revision ID: 202606010003
Revises: 202606010002
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202606010003"
down_revision = "202606010002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_test_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_user_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("requested_strategies", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "requested_pairs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("requested_timeframes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metric_set",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['backtest']::text[]"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_strategy_test_runs_status",
        ),
        sa.CheckConstraint(
            "mode IN ('discovery', 'research_virtual', 'production_like')",
            name="ck_strategy_test_runs_mode",
        ),
        sa.CheckConstraint("end_at > start_at", name="ck_strategy_test_runs_time_range"),
        sa.CheckConstraint(
            "coalesce(array_length(requested_strategies, 1), 0) > 0",
            name="ck_strategy_test_runs_requested_strategies_non_empty",
        ),
        sa.CheckConstraint(
            "coalesce(array_length(requested_timeframes, 1), 0) > 0",
            name="ck_strategy_test_runs_requested_timeframes_non_empty",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_strategy_test_runs_user_id",
            ondelete="CASCADE",
        ),
    )
    op.execute("CREATE INDEX ix_strategy_test_runs_user_created ON strategy_test_runs (user_id, created_at DESC)")
    op.execute("CREATE INDEX ix_strategy_test_runs_status_created ON strategy_test_runs (status, created_at DESC)")
    op.create_index("ix_strategy_test_runs_mode", "strategy_test_runs", ["mode"])


def downgrade() -> None:
    op.drop_index("ix_strategy_test_runs_mode", table_name="strategy_test_runs")
    op.drop_index("ix_strategy_test_runs_status_created", table_name="strategy_test_runs")
    op.drop_index("ix_strategy_test_runs_user_created", table_name="strategy_test_runs")
    op.drop_table("strategy_test_runs")
