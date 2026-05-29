"""add risk protection reset windows

Revision ID: 202605280013
Revises: 202605280012
Create Date: 2026-05-29 00:13:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "202605280013"
down_revision = "202605280012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE risk_protection_state
        ADD COLUMN IF NOT EXISTS daily_window_start TIMESTAMPTZ NULL
        """
    )
    op.execute(
        """
        ALTER TABLE risk_protection_state
        ADD COLUMN IF NOT EXISTS weekly_window_start TIMESTAMPTZ NULL
        """
    )
    op.execute(
        """
        ALTER TABLE risk_protection_state
        ADD COLUMN IF NOT EXISTS window_timezone TEXT NOT NULL DEFAULT 'UTC'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE risk_protection_state DROP COLUMN IF EXISTS window_timezone")
    op.execute("ALTER TABLE risk_protection_state DROP COLUMN IF EXISTS weekly_window_start")
    op.execute("ALTER TABLE risk_protection_state DROP COLUMN IF EXISTS daily_window_start")
