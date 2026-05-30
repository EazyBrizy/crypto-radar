"""expand strategy signal statuses

Revision ID: 202605290001
Revises: 202605280013
Create Date: 2026-05-29
"""

from alembic import op


revision = "202605290001"
down_revision = "202605280013"
branch_labels = None
depends_on = None


NEW_STATUS_CHECK = (
    "status IN ("
    "'new', 'active', 'watchlist', 'ready', 'actionable', 'wait_for_pullback', "
    "'entry_touched', 'confirmed', 'expired', 'invalidated', 'closed'"
    ")"
)

OLD_STATUS_CHECK = "status IN ('new', 'active', 'confirmed', 'expired', 'invalidated', 'closed')"


def upgrade() -> None:
    op.drop_constraint("ck_trading_signals_status", "trading_signals", type_="check")
    op.create_check_constraint(
        "ck_trading_signals_status",
        "trading_signals",
        NEW_STATUS_CHECK,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE trading_signals "
        "SET status = CASE "
        "WHEN status IN ('watchlist', 'ready', 'wait_for_pullback') THEN 'new' "
        "WHEN status IN ('actionable', 'entry_touched') THEN 'active' "
        "ELSE status END"
    )
    op.drop_constraint("ck_trading_signals_status", "trading_signals", type_="check")
    op.create_check_constraint(
        "ck_trading_signals_status",
        "trading_signals",
        OLD_STATUS_CHECK,
    )
