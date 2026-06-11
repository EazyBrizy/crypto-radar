"""add rejected signal status

Revision ID: 202606060003
Revises: 202606050002
Create Date: 2026-06-06
"""

from alembic import op


revision = "202606060003"
down_revision = "202606050002"
branch_labels = None
depends_on = None


NEW_STATUS_CHECK = (
    "status IN ("
    "'new', 'active', 'watchlist', 'ready', 'actionable', 'wait_for_pullback', "
    "'entry_touched', 'confirmed', 'rejected', 'expired', 'invalidated', 'closed'"
    ")"
)

OLD_STATUS_CHECK = (
    "status IN ("
    "'new', 'active', 'watchlist', 'ready', 'actionable', 'wait_for_pullback', "
    "'entry_touched', 'confirmed', 'expired', 'invalidated', 'closed'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint("ck_trading_signals_status", "trading_signals", type_="check")
    op.create_check_constraint(
        "ck_trading_signals_status",
        "trading_signals",
        NEW_STATUS_CHECK,
    )


def downgrade() -> None:
    op.execute("UPDATE trading_signals SET status = 'invalidated' WHERE status = 'rejected'")
    op.drop_constraint("ck_trading_signals_status", "trading_signals", type_="check")
    op.create_check_constraint(
        "ck_trading_signals_status",
        "trading_signals",
        OLD_STATUS_CHECK,
    )
