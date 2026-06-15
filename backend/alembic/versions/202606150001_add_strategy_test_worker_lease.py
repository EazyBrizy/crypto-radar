"""add strategy test worker lease fields

Revision ID: 202606150001
Revises: 202606120001
Create Date: 2026-06-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202606150001"
down_revision = "202606120001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("strategy_test_runs", sa.Column("worker_id", sa.Text(), nullable=True))
    op.add_column(
        "strategy_test_runs",
        sa.Column("worker_attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "strategy_test_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "strategy_test_runs",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_strategy_test_runs_status_lease",
        "strategy_test_runs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_test_runs_status_lease", table_name="strategy_test_runs")
    op.drop_column("strategy_test_runs", "claimed_at")
    op.drop_column("strategy_test_runs", "lease_expires_at")
    op.drop_column("strategy_test_runs", "worker_attempt")
    op.drop_column("strategy_test_runs", "worker_id")
