"""add oi to derivative snapshots

Revision ID: 202606010002
Revises: 202606010001
Create Date: 2026-06-01
"""

from alembic import op
import sqlalchemy as sa


revision = "202606010002"
down_revision = "202606010001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_derivative_snapshots",
        sa.Column("open_interest", sa.Numeric(38, 18), nullable=True),
    )
    op.add_column(
        "market_derivative_snapshots",
        sa.Column("open_interest_value", sa.Numeric(38, 18), nullable=True),
    )
    op.add_column(
        "market_derivative_snapshots",
        sa.Column("oi_change", sa.Numeric(18, 10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("market_derivative_snapshots", "oi_change")
    op.drop_column("market_derivative_snapshots", "open_interest_value")
    op.drop_column("market_derivative_snapshots", "open_interest")
