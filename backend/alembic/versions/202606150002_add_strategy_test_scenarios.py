"""add strategy test scenario checkpoints

Revision ID: 202606150002
Revises: 202606150001
Create Date: 2026-06-15 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "202606150002"
down_revision = "202606150001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_test_scenarios",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_key", sa.Text(), nullable=False),
        sa.Column("scenario_index", sa.Integer(), nullable=False),
        sa.Column("strategy_code", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("bars_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("bars_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_written_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_strategy_test_scenarios_status",
        ),
        sa.CheckConstraint("bars_total >= 0", name="ck_strategy_test_scenarios_bars_total_non_negative"),
        sa.CheckConstraint("bars_processed >= 0", name="ck_strategy_test_scenarios_bars_processed_non_negative"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["strategy_test_runs.id"],
            name="fk_strategy_test_scenarios_run_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "scenario_key", name="uq_strategy_test_scenarios_run_key"),
    )
    op.create_index(
        "ix_strategy_test_scenarios_run_status",
        "strategy_test_scenarios",
        ["run_id", "status"],
    )
    op.create_index(
        "ix_strategy_test_scenarios_run_index",
        "strategy_test_scenarios",
        ["run_id", "scenario_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_test_scenarios_run_index", table_name="strategy_test_scenarios")
    op.drop_index("ix_strategy_test_scenarios_run_status", table_name="strategy_test_scenarios")
    op.drop_table("strategy_test_scenarios")
