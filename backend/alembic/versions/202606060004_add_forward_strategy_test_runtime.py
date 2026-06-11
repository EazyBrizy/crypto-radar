"""add forward strategy test runtime

Revision ID: 202606060004
Revises: 202606060003
Create Date: 2026-06-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202606060004"
down_revision = "202606060003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_test_runs",
        sa.Column("test_type", sa.Text(), nullable=False, server_default=sa.text("'historical_backtest'")),
    )
    op.add_column(
        "strategy_test_runs",
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "strategy_test_runs",
        sa.Column(
            "runtime_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "strategy_test_runs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("ck_strategy_test_runs_status", "strategy_test_runs", type_="check")
    op.create_check_constraint(
        "ck_strategy_test_runs_status",
        "strategy_test_runs",
        "status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'stopping')",
    )
    op.create_check_constraint(
        "ck_strategy_test_runs_test_type",
        "strategy_test_runs",
        "test_type IN ('historical_backtest', 'forward_virtual')",
    )
    op.create_index("ix_strategy_test_runs_test_type", "strategy_test_runs", ["test_type"])


def downgrade() -> None:
    op.drop_index("ix_strategy_test_runs_test_type", table_name="strategy_test_runs")
    op.drop_constraint("ck_strategy_test_runs_test_type", "strategy_test_runs", type_="check")
    op.drop_constraint("ck_strategy_test_runs_status", "strategy_test_runs", type_="check")
    op.create_check_constraint(
        "ck_strategy_test_runs_status",
        "strategy_test_runs",
        "status IN ('queued', 'running', 'completed', 'failed')",
    )
    op.drop_column("strategy_test_runs", "last_heartbeat_at")
    op.drop_column("strategy_test_runs", "runtime_state")
    op.drop_column("strategy_test_runs", "summary")
    op.drop_column("strategy_test_runs", "test_type")
